"""A step naming a connection of a kind its block does not accept is refused at plan, not at run."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.schemas import Catalog, SurfaceEntry
from dirigent_core.database import session_scope
from dirigent_core.documents import load_pipeline_text as load_text
from dirigent_core.documents import validate_against_catalog
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Connection
from dirigent_core.pipelines import PlanAction, apply_document, plan_apply
from dirigent_core.plugins import PluginHost, load_plugin_host


@pytest.fixture
def host() -> PluginHost:
    """The installed blocks and connection kinds, which are what declare the kinds they accept."""
    return load_plugin_host()


def notify(connection: str, carried: str = "") -> str:
    """A pipeline that POSTs through ``connection``, carrying the connections in ``carried``."""
    return (
        f"format: dirigent/v1\ncode: notify\n{carried}steps:\n"
        f"  notify: {{ block: webhook.post, config: {{connection: {connection}, path: /hook}} }}\n"
    )


def test_a_carried_webhook_connection_is_refused_offline_for_webhook_post(host: PluginHost) -> None:
    """Offline the only kinds known are the ones the document carries, and those are checked."""
    carried = "connections:\n  sink: {kind: webhook, config: {url: 'https://sink.example.org/hook'}}\n"

    issues = validate_against_catalog(load_text(notify("sink", carried)), host.catalog(), connections=None)

    assert [(issue.code, issue.location) for issue in issues] == [
        ("document.step_connection_for_alerts", "steps.notify.config.connection")
    ]
    assert issues[0].params["kinds"] == ["http"]
    assert issues[0].params["carrying"] == ["base_url"]
    assert issues[0].params["kind"] == "webhook"
    assert issues[0].message.startswith("webhook.post needs a connection of kind http")
    assert issues[0].message.endswith("which is for alert delivery")


def test_a_carried_http_connection_is_accepted(host: PluginHost) -> None:
    carried = "connections:\n  sink: {kind: http, config: {base_url: 'https://sink.example.org'}}\n"

    assert validate_against_catalog(load_text(notify("sink", carried)), host.catalog(), connections=None) == []


def test_an_instance_connection_is_checked_by_the_kind_the_instance_holds(host: PluginHost) -> None:
    definition = load_text(notify("sink"))

    refused = validate_against_catalog(definition, host.catalog(), connections={"sink": "webhook"})
    accepted = validate_against_catalog(definition, host.catalog(), connections={"sink": "http"})

    assert [issue.code for issue in refused] == ["document.step_connection_for_alerts"]
    assert accepted == []


def test_a_connection_whose_kind_the_caller_does_not_know_is_held_but_not_kind_checked(host: PluginHost) -> None:
    assert validate_against_catalog(load_text(notify("sink")), host.catalog(), connections={"sink": None}) == []


def test_a_kind_carrying_the_fields_an_http_block_reads_is_accepted(host: PluginHost) -> None:
    """A pack's own HTTP-backed kind fits an HTTP block by carrying a base_url, with no list to join."""
    catalog = host.catalog()
    extended = Catalog.model_validate(
        {
            **catalog.model_dump(),
            "connection_kinds": [
                *catalog.model_dump()["connection_kinds"],
                SurfaceEntry(id="acme", plugin="acme", config_schema={"properties": {"base_url": {}}}).model_dump(),
            ],
        }
    )

    assert validate_against_catalog(load_text(notify("api")), extended, connections={"api": "acme"}) == []


def test_a_kind_named_by_id_alone_refuses_every_other(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: read\nsteps:\n"
        "  read: { block: sql.query, config: {connection: api, sql: 'select 1'} }\n"
    )

    issues = validate_against_catalog(definition, host.catalog(), connections={"api": "http"})

    assert [(issue.code, issue.location) for issue in issues] == [
        ("document.step_connection_wrong_kind", "steps.read.config.connection")
    ]
    assert issues[0].params["kinds"] == ["sql"]


def test_a_signing_connection_is_held_to_its_own_kind(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: signed\nsteps:\n"
        "  notify: { block: webhook.post, config: {url: 'https://sink.example.org/hook', sign_with: sink} }\n"
    )

    issues = validate_against_catalog(definition, host.catalog(), connections={"sink": "webhook"})

    assert [issue.location for issue in issues] == ["steps.notify.config.sign_with"]


def test_a_connection_named_by_reference_is_left_to_the_run(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: notify\n"
        "params: {type: object, properties: {sink: {type: string}}}\nsteps:\n"
        "  notify: { block: webhook.post, config: {connection: '${params.sink}', path: /hook} }\n"
    )

    assert validate_against_catalog(definition, host.catalog(), connections={"sink": "webhook"}) == []


async def test_apply_refuses_a_stored_connection_of_the_wrong_kind(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        session.add(Connection(code="sink", kind="webhook", config={"url": "https://sink.example.org/hook"}))
        session.add(Connection(code="api", kind="http", config={"base_url": "https://sink.example.org"}))

    async with session_scope(sessions) as session:
        planned = await plan_apply(session, services, load_text(notify("sink")))
        refused = await apply_document(session, services, load_text(notify("sink")))
        accepted = await apply_document(session, services, load_text(notify("api")))

    assert [issue.code for issue in planned.issues] == ["document.step_connection_for_alerts"]
    assert refused.plan.action is PlanAction.INVALID
    assert accepted.plan.action is PlanAction.CREATE
