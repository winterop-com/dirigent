"""A source kind a pack contributes: listed in the catalog, applied, and called like the built-in one."""

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, ValidationError

from dirigent_client.schemas import Page, SourceInputOut
from dirigent_common import JsonMap
from dirigent_core.config import Settings
from dirigent_core.plugins import DuplicateContribution, PluginHost, load_plugin_host
from dirigent_core.sources.endpoint import EndpointSource
from dirigent_plugin import Contribution
from dirigent_plugin.sources import (
    Ignore,
    InboundRequest,
    ReceiveContext,
    ReceivedSource,
    Refusal,
    Route,
    SourceAuth,
    SourceHosting,
    SourceSpec,
)
from dirigent_server import create_app
from dirigent_testing import receive_request
from tests_support import apply_document

PREFIX = "/api/v1"


class PingConfig(BaseModel):
    """Where the pack's kind is called."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str


class PingInput(BaseModel):
    """The event a call carried."""

    model_config = ConfigDict(frozen=True)

    event: str
    received_at: datetime


class PingSource(ReceivedSource[PingConfig, PingInput]):
    """A webhook-like kind: a ping is a sign of life, and a body without an event is refused."""

    spec = SourceSpec(kind="tests.ping", summary="A test pack's webhook", hosting=SourceHosting.RECEIVED)
    config_model = PingConfig
    output_model = PingInput

    def route(self, config: PingConfig) -> Route:
        """Take POST at the configured path."""
        return Route(methods=("POST",), template=config.path)

    def auth(self, config: PingConfig) -> SourceAuth:
        """Admit anyone, as a webhook's sender is."""
        return SourceAuth(kind="public")

    def complete(self, config: PingConfig, given: JsonMap, *, received_at: datetime) -> PingInput:
        """Make a hand run's input whole."""
        return PingInput(event=str(given.get("event", "hand")), received_at=received_at)

    async def receive(
        self, config: PingConfig, request: InboundRequest, ctx: ReceiveContext
    ) -> PingInput | Ignore | Refusal:
        """Answer a ping without a run, refuse a body with no event, and take the rest."""
        body: Any = json.loads(request.body or b"{}")
        if body.get("ping") is True:
            return Ignore()
        if "event" not in body:
            return Refusal(status=422, code="tests.no_event", message="the body names no event")
        ctx.log.info("event taken", named=body["event"])
        return PingInput(event=str(body["event"]), received_at=request.received_at)


class PolledSource(PingSource):
    """A kind no worker can host here."""

    spec = SourceSpec(kind="tests.polled", summary="A polled kind", hosting=SourceHosting.POLLED)


class Pack:
    """A pack contributing one source kind."""

    def contribute(self) -> Contribution:
        """Contribute the ping kind."""
        return Contribution(sources=[PingSource()])


PIPELINE = """
format: dirigent/v1
kind: pipeline
code: pinged
steps:
  hook:
    source:
      kind: tests.ping
      path: /hook
  shape:
    block: transform.jq
    depends_on: [hook]
    config:
      input: ${steps.hook.output.event}
      program: '.'
"""


@pytest.fixture
def packed(settings: Settings, admin_token: str) -> Iterator[TestClient]:
    """A client against an instance with the test pack installed beside everything else."""
    host = PluginHost({**load_plugin_host().contributions, "pack-tests": Pack().contribute()})
    with TestClient(create_app(settings, host=host), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        yield client


def test_a_contributed_kind_is_listed_under_the_pack_that_contributed_it(packed: TestClient) -> None:
    catalog = packed.get(f"{PREFIX}/blocks").json()
    owners = {entry["kind"]: entry["plugin"] for entry in catalog["sources"]}
    assert owners["tests.ping"] == "pack-tests"
    assert owners["endpoint"] == "builtin"


def test_a_contributed_kind_takes_calls_ignores_a_ping_and_refuses_with_its_own_status(packed: TestClient) -> None:
    apply_document(packed, PIPELINE)
    assert packed.post("/endpoints/hook", json={"ping": True}, headers={"Authorization": ""}).status_code == 204
    refused = packed.post("/endpoints/hook", json={}, headers={"Authorization": ""})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "tests.no_event"
    taken = packed.post("/endpoints/hook", json={"event": "push"}, headers={"Authorization": ""})
    assert taken.status_code == 202, taken.text
    journal = (
        Page[SourceInputOut].model_validate(packed.get(f"{PREFIX}/pipelines/pinged/sources/hook/inputs").json()).items
    )
    assert [(entry.outcome, entry.status) for entry in journal] == [("accepted", 202), ("refused", 422)]


def test_a_pack_cannot_take_a_kind_dirigent_provides() -> None:
    class Taker(EndpointSource):
        """The built-in kind, contributed again."""

    with pytest.raises(DuplicateContribution):
        PluginHost({"taker": Contribution(sources=[Taker()])})


def test_a_kind_the_server_does_not_receive_is_refused_at_contribution() -> None:
    with pytest.raises(ValidationError, match="tests.polled"):
        Contribution(sources=[PolledSource()])


async def test_a_pack_tests_its_kind_without_a_server() -> None:
    request = InboundRequest(
        method="POST", path="/hook", route="/hook", body=b'{"event": "push"}', received_at=datetime(2026, 1, 1)
    )
    taken = await receive_request(PingSource(), {"path": "/hook"}, request)
    assert isinstance(taken, PingInput)
    assert taken.event == "push"
    refused = await receive_request(PingSource(), {"path": "/hook"}, request.model_copy(update={"body": b"{}"}))
    assert isinstance(refused, Refusal)
    assert refused.status == 422
