"""Boot a `dg dev --seed examples` and give it the demo half: an object store and some runs.

`dg dev --seed` is what applies the corpus and creates the connections it declares. What is
left here is what only the demo wants: the throwaway object store `s3-round-trip.yaml` names,
a document pointed at a connection nothing holds, a handful of runs so a fresh UI has every
colour, and one health check per connection. `make dev-seeded` is the target that runs this.

The instance this leaves behind is not a clean one, and that is the point: schedules land
paused, some documents are refused, and some runs fail.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FrameType
from typing import Any, Final

import yaml
from cryptography.fernet import Fernet
from pydantic import BaseModel

from dirigent_cli.main import DEV_ADMIN, DEV_PASSWORD
from dirigent_client import BlockingDirigent, DirigentError
from dirigent_core.config import STATE_DIR
from dirigent_core.protocol import Record, as_json, make

#: Blocks the seeded instance allows, because the corpus is full of them and refusing them
#: at apply would leave nothing to look at.
UNSAFE_BLOCKS: Final = '["shell.run", "docker.run"]'

#: Which connection serves `s3://`, so `s3-round-trip` validates against a registered scheme.
STORAGE_CONNECTIONS: Final = '{"s3": "artifacts"}'

#: The throwaway pair the storage lane's own rustfs container is started with. Nothing is
#: listening on this endpoint unless somebody started one, which is what makes the health
#: column red and the run fail.
S3_CONNECTION: Final[dict[str, Any]] = {
    "endpoint_url": "http://127.0.0.1:9000",
    "access_key_id": "dirigent-test-key",
    "secret_access_key": "dirigent-test-secret",
    "path_style": True,
    "bucket": "dirigent-archive",
}

#: A connection code no instance holds, which is what the unmet-needs document points at.
ABSENT_CONNECTION: Final = "warehouse-nobody-created"

#: How long the API is given to come up before the seed gives up on it.
BOOT_SECONDS: Final = 60.0

#: How long the instance's own seeding is given to reach its closing record.
SEED_SECONDS: Final = 600.0

#: How long one seeded run is given to settle before it is reported as it stands.
SETTLE_SECONDS: Final = 90.0

#: The record `dg dev --seed` closes with, which is what says the corpus is in.
DONE_KIND: Final = "seed.done"


class SeedRun(BaseModel):
    """One run the seed starts, and what it is there to show."""

    pipeline: str
    params: dict[str, Any] = {}
    window: tuple[datetime, datetime] | None = None
    """The logical interval this run covers, for a pipeline whose steps read one."""

    expect: str


#: The runs the seed starts, so a fresh UI has every colour in its listing. The failures are
#: chosen for settling quickly: `error-handler` fails its load twice a second apart,
#: `s3-round-trip` has no retry on the step that cannot reach an object store, and
#: `optional-step` fails locally and instantly. That last one is the only seeded run that
#: settles `completed_with_errors`, which is a third status and not a shade of failed.
#: `cron-windowed` is the one that carries a window, so the run panel has one to draw.
SEEDED_RUNS: Final[tuple[SeedRun, ...]] = (
    SeedRun(pipeline="hello-world", expect="succeeds"),
    SeedRun(pipeline="jq-reshape", expect="succeeds"),
    SeedRun(pipeline="error-handler", expect="fails"),
    SeedRun(pipeline="optional-step", expect="completes with errors"),
    SeedRun(pipeline="s3-round-trip", params={"day": "2026-01-01"}, expect="fails"),
    SeedRun(
        pipeline="cron-windowed",
        window=(datetime(2026, 6, 1, 3, 0, tzinfo=UTC), datetime(2026, 6, 2, 3, 0, tzinfo=UTC)),
        expect="succeeds",
    ),
)


def emit(record: Record) -> None:
    """Write one record to the stream `dg dev` is writing its own to."""
    sys.stdout.write(f"{as_json(record)}\n")
    sys.stdout.flush()


def seed_record(message: str, **fields: Any) -> None:
    """Emit one seeding record."""
    emit(make("seed", at=datetime.now(UTC), message=message, **fields))


def instance_env(root: Path) -> dict[str, str]:
    """Build the environment `dg dev` is started with, pointed at one fresh state directory.

    `dg dev` is started with --wipe-state, so the key below is minted per seeding rather than
    kept: an instance that begins empty holds no connection an older key would have to open.
    """
    state = (root / STATE_DIR).resolve()
    return os.environ | {
        "DIRIGENT_DATABASE_URL": f"sqlite+aiosqlite:///{state / 'dirigent.db'}",
        "DIRIGENT_ARTIFACT_ROOT": f"file://{state / 'artifacts'}",
        "DIRIGENT_SECRET_KEY": Fernet.generate_key().decode(),
        "DIRIGENT_ENABLED_UNSAFE_BLOCKS": UNSAFE_BLOCKS,
        "DIRIGENT_STORAGE_CONNECTIONS": STORAGE_CONNECTIONS,
    }


def demo_corpus(directory: Path, examples: Path) -> Path:
    """Write the demo's own seed directory: the object store, and a document nothing satisfies.

    Neither belongs in `examples/`, which is the set that runs, so they are written here and
    handed to `--seed` ahead of the corpus: the object store has to exist before the document
    that names it is applied.
    """
    directory.mkdir(parents=True, exist_ok=True)
    connections = {"connections": {"artifacts": {"kind": "s3", "config": S3_CONNECTION}}}
    (directory / "connections.yaml").write_text(yaml.safe_dump(connections, sort_keys=False))
    (directory / "unmet-needs.yaml").write_text(yaml.safe_dump(unmet_needs(examples), sort_keys=False))
    return directory


def unmet_needs(examples: Path) -> dict[str, Any]:
    """Build a document naming a connection nothing holds, to see what an apply does with it.

    A copy of the corpus's connection example, recoded and repointed.
    """
    text = (examples / "demo" / "requires.yaml").read_text().replace("postman-echo", ABSENT_CONNECTION)
    document: dict[str, Any] = yaml.safe_load(text)
    document["code"] = "unmet-needs"
    document["description"] = f"Names {ABSENT_CONNECTION}, which no instance holds."
    return document


def connect(url: str) -> BlockingDirigent:
    """Wait for the API to answer and log in as the development admin.

    Logging in rather than reading the token off the boot record: the development admin's
    password is fixed, so this works on an instance `dg dev` has just emptied and remade as
    well as on one started with --keep-state.
    """
    deadline = time.monotonic() + BOOT_SECONDS
    while True:
        client = BlockingDirigent(url=url)
        try:
            client.call(client.auth.login(DEV_ADMIN, DEV_PASSWORD))
        except DirigentError as error:
            client.close()
            if time.monotonic() > deadline:
                raise SystemExit(f"the instance at {url} never answered a login: {error}") from error
            time.sleep(0.25)
            continue
        return client


def relay(process: subprocess.Popen[str], seeded: threading.Event) -> None:
    """Pass the instance's stream on to this one, and say when its seeding closed.

    The instance writes to a pipe, so it writes records; this reads them for the one that
    says the corpus is in, and everything goes on to this process's own stream unchanged.
    """
    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("kind") == DONE_KIND:
            seeded.set()
    seeded.set()


def seed_runs(client: BlockingDirigent, stored: set[str]) -> dict[str, str]:
    """Start the seeded runs and wait for each to settle, reporting how it ended."""
    outcomes: dict[str, str] = {}
    started: list[tuple[str, str]] = []
    for wanted in SEEDED_RUNS:
        if wanted.pipeline not in stored:
            seed_record("run skipped", pipeline=wanted.pipeline, reason="the document was not stored")
            continue
        accepted = client.call(client.pipelines.run(wanted.pipeline, params=wanted.params, window=wanted.window))
        if accepted.run_id is None:
            seed_record("run refused", pipeline=wanted.pipeline, reason=accepted.detail or accepted.status)
            continue
        started.append((wanted.pipeline, str(accepted.run_id)))
        seed_record("run started", pipeline=wanted.pipeline, run_id=str(accepted.run_id), expect=wanted.expect)
    for pipeline, run_id in started:
        try:
            run = client.call(client.runs.wait(run_id, timeout=timedelta(seconds=SETTLE_SECONDS)))
            status = run.status.value
        except DirigentError as error:
            status = f"unsettled: {error.message}"
        outcomes[pipeline] = status
        seed_record("run settled", pipeline=pipeline, run_id=run_id, status=status)
    return outcomes


def check_connections(client: BlockingDirigent, codes: list[str]) -> dict[str, bool]:
    """Check every connection once, so the health column is populated rather than unknown."""
    health: dict[str, bool] = {}
    for code in codes:
        try:
            report = client.call(client.connections.check(code))
            health[code] = report.healthy
            seed_record("connection checked", connection=code, healthy=report.healthy, detail=report.detail)
        except DirigentError as error:
            health[code] = False
            seed_record("connection checked", connection=code, healthy=False, detail=error.message)
    return health


def pages(read: Callable[..., Any]) -> Iterator[Any]:
    """Walk a paged listing to its end."""
    after: str | None = None
    while True:
        page = read(after)
        yield from page.items
        if page.next is None:
            return
        after = page.next


def held_connections(client: BlockingDirigent) -> list[str]:
    """Name every connection the seeded instance ended up holding."""
    rows = pages(lambda after: client.call(client.connections.list(after=after)))
    return sorted(row.code for row in rows)


def held_pipelines(client: BlockingDirigent) -> set[str]:
    """Name every pipeline the seeding stored, which is what a seeded run can be started on."""
    rows = pages(lambda after: client.call(client.pipelines.list(after=after)))
    return {row.code for row in rows}


def count_schedules(client: BlockingDirigent) -> tuple[int, int]:
    """Count the clocks the instance holds, and how many of them are stopped."""
    total = 0
    paused = 0
    rows = pages(lambda after: client.call(client.pipelines.list(after=after)))
    for code in [row.code for row in rows if row.schedules]:
        for schedule in pages(lambda after, held=code: client.call(client.schedules.list(held, after=after))):
            total += 1
            paused += 1 if schedule.paused else 0
    return total, paused


def seed(url: str, seeded: threading.Event) -> None:
    """Wait for the instance's own seeding, then start the demo's runs and check its health."""
    client = connect(url)
    try:
        if not seeded.wait(SEED_SECONDS):
            seed_record("seeding unfinished", waited_seconds=SEED_SECONDS, hint="the runs below start anyway")
        outcomes = seed_runs(client, held_pipelines(client))
        health = check_connections(client, held_connections(client))
        clocks, stopped = count_schedules(client)
        seed_record(
            "seeded",
            schedules=clocks,
            schedules_paused=stopped,
            runs=outcomes,
            connections_healthy=sorted(code for code, ok in health.items() if ok),
            connections_unhealthy=sorted(code for code, ok in health.items() if not ok),
        )
    finally:
        client.close()


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the arguments the make target passes."""
    parser = argparse.ArgumentParser(description="Boot a seeded dg dev instance.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Directory holding .dirigent/state.")
    parser.add_argument("--examples", type=Path, default=Path("examples"), help="The document corpus to seed from.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3333)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start `dg dev --seed`, add the demo's own half, and then stay out of its way.

    The instance is a child in this process group, so one ctrl-c reaches both processes; its
    stream is read here for the record that says the corpus is in, and relayed on unchanged,
    so one NDJSON stream still carries both.
    """
    options = parse(argv)
    with TemporaryDirectory(prefix="dirigent-seed-") as scratch:
        demo = demo_corpus(Path(scratch) / "demo", options.examples)
        command = [
            "dg",
            "dev",
            "--wipe-state",
            "--host",
            options.host,
            "--port",
            str(options.port),
            "--seed",
            str(demo),
            "--seed",
            str(options.examples),
        ]
        process = subprocess.Popen(
            command,
            env=instance_env(options.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        def relay_signal(number: int, _frame: FrameType | None) -> None:
            """Pass a termination signal on to the instance, which owns the shutdown."""
            process.send_signal(number)

        signal.signal(signal.SIGTERM, relay_signal)
        seeded = threading.Event()
        threading.Thread(target=relay, args=(process, seeded), daemon=True).start()
        try:
            seed(f"http://{options.host}:{options.port}", seeded)
        except BaseException:
            process.terminate()
            process.wait()
            raise
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The interrupt reached the instance too; this only waits for it to finish.
                continue


if __name__ == "__main__":
    raise SystemExit(main())
