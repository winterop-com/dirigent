"""Tests for the context the engine hands a block: the client it builds, and where a capture lands."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
from pydantic import BaseModel, SecretStr

from dirigent_common import base_format_checker
from dirigent_core.engine.context import BufferedLogger, EngineStepContext, build_http_client
from dirigent_core.secrets import SecretBox
from dirigent_core.storage import Storage, build_storage
from dirigent_testing import FakeRuns


class _TokenConfig(BaseModel):
    """A pack's connection kind that authenticates with a personal access token."""

    base_url: str = "https://play.example/api"
    api_token: SecretStr | None = None


class _SchemedTokenConfig(_TokenConfig):
    """A token connection that names the scheme its token is sent under."""

    api_token_scheme: str = "Bearer"


class _BasicConfig(BaseModel):
    """A connection kind that authenticates with the basic pair alone."""

    base_url: str = "https://play.example/api"
    basic_username: str | None = None
    basic_password: SecretStr | None = None


class _BearerAndTokenConfig(_TokenConfig):
    """A connection kind that names both credential header fields."""

    bearer_token: SecretStr | None = None


class _BareConfig(BaseModel):
    """A connection kind carrying no HTTP fields at all."""

    note: str = "nothing to read"


def test_api_token_is_sent_under_the_default_scheme() -> None:
    """A config carrying only an api_token authorizes with ApiToken."""
    client = build_http_client(_TokenConfig(api_token=SecretStr("d2pat_x")))

    assert client.headers["authorization"] == "ApiToken d2pat_x"
    assert client.auth is None


def test_api_token_scheme_overrides_the_default() -> None:
    """A config that names a scheme has its token sent under that scheme."""
    client = build_http_client(_SchemedTokenConfig(api_token=SecretStr("t")))

    assert client.headers["authorization"] == "Bearer t"


def test_bearer_token_wins_over_an_api_token() -> None:
    """A config carrying both header credentials sends the bearer one."""
    client = build_http_client(_BearerAndTokenConfig(api_token=SecretStr("t"), bearer_token=SecretStr("b")))

    assert client.headers["authorization"] == "Bearer b"


def test_empty_api_token_authorizes_nothing() -> None:
    """An api_token present but empty leaves the client unauthenticated."""
    client = build_http_client(_TokenConfig(api_token=SecretStr("")))

    assert "authorization" not in client.headers


def test_basic_credentials_stay_basic_auth() -> None:
    """A config carrying only the basic pair gets httpx basic auth and no header."""
    client = build_http_client(_BasicConfig(basic_username="admin", basic_password=SecretStr("district")))

    assert isinstance(client.auth, httpx2.BasicAuth)
    assert "authorization" not in client.headers


def test_a_config_naming_no_fields_gets_a_bare_client() -> None:
    """A connection kind with none of the standard fields still yields a usable client."""
    client = build_http_client(_BareConfig())

    assert client.auth is None
    assert "authorization" not in client.headers


# -- where a captured stream lands -----------------------------------------------


def _context(
    storage: Storage, scratch: str, work_root: Path, *, attempt: int = 1, item: UUID | None = None
) -> EngineStepContext:
    """A context bound to one attempt of one step, carrying what a capture reads."""
    run_id = uuid4()
    return EngineStepContext(
        run_id=run_id,
        step="load",
        run_item_id=item,
        attempt=attempt,
        started_at=datetime.now(UTC),
        inline_capture=8 * 1024,
        params={},
        log=BufferedLogger(run_id=run_id, step_name="load", limit=100, batch=10),
        storage=storage,
        scratch=scratch,
        work_root=str(work_root),
        connections={},
        connection_models={},
        secrets=SecretBox(None),
        runs=FakeRuns(),
        format_checker=base_format_checker(),
    )


async def test_a_capture_is_named_under_the_scratch_prefix_and_reads_back(tmp_path: Path) -> None:
    scratch = f"file://{tmp_path}/runs/one"

    async with _context(build_storage(f"file://{tmp_path}"), scratch, tmp_path).capture("stdout") as sink:
        await sink.write(b"printed")

    assert sink.uri == f"{scratch}/load/attempt-1-stdout"
    assert (tmp_path / "runs/one/load/attempt-1-stdout").read_bytes() == b"printed"


async def test_two_attempts_of_one_step_capture_to_different_objects(tmp_path: Path) -> None:
    """The attempt is in the name, so a retry never writes over what the first attempt printed."""
    storage = build_storage(f"file://{tmp_path}")
    scratch = f"file://{tmp_path}/runs/one"

    async with _context(storage, scratch, tmp_path, attempt=1).capture("stdout") as first:
        await first.write(b"first")
    async with _context(storage, scratch, tmp_path, attempt=2).capture("stdout") as second:
        await second.write(b"second")

    assert first.uri != second.uri
    assert (tmp_path / "runs/one/load/attempt-1-stdout").read_bytes() == b"first"
    assert (tmp_path / "runs/one/load/attempt-2-stdout").read_bytes() == b"second"


async def test_a_fan_out_item_captures_under_its_own_path(tmp_path: Path) -> None:
    """Two items of one step run the same block at the same attempt, so the item id parts them."""
    scratch = f"file://{tmp_path}/runs/one"
    item = uuid4()

    async with _context(build_storage(f"file://{tmp_path}"), scratch, tmp_path, item=item).capture("err") as sink:
        await sink.write(b"one item")

    assert sink.uri == f"{scratch}/load/{item}/attempt-1-err"
