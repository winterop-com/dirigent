"""The catalogue mechanism, and the workspace-wide walk over every prefix it owns."""

import importlib
from typing import Final

import pytest

from dirigent_common import Catalogue, Issue, Message, MessageError, validation_issues
from dirigent_common.messages import EXTRA_FORBIDDEN

#: Every messages module the workspace holds, named so importing them all is what the walk
#: below asserts against. A new package's catalogue is added here.
MODULES: Final[tuple[str, ...]] = (
    "dirigent_common.messages",
    "dirigent_plugin.messages",
    "dirigent_client.messages",
    "dirigent_core.messages",
    "dirigent_server.messages",
    "dirigent_cli.messages",
    "dirigent_testing.messages",
    "dirigent_block_base.messages",
    "dirigent_block_execute.messages",
    "dirigent_block_http.messages",
    "dirigent_block_parquet.messages",
    "dirigent_block_queues.messages",
    "dirigent_block_sql.messages",
    "dirigent_block_sql_duckdb.messages",
    "dirigent_block_storage.messages",
    "dirigent_block_transform_jq.messages",
)

#: Which package owns each prefix. A code is public API, so a prefix has exactly one owner.
OWNED: Final[dict[str, str]] = {
    "common": "dirigent-common",
    "validation": "dirigent-common",
    "plugin": "dirigent-plugin",
    "client": "dirigent-client",
    "auth": "dirigent-core",
    "pipeline": "dirigent-core",
    "document": "dirigent-core",
    "schedule": "dirigent-core",
    "webhook": "dirigent-core",
    "alert": "dirigent-core",
    "secret": "dirigent-core",
    "artifacts": "dirigent-core",
    "run": "dirigent-core",
    "reference": "dirigent-core",
    "host": "dirigent-core",
    "parameter": "dirigent-core",
    "schema": "dirigent-core",
    "server": "dirigent-server",
    "cli": "dirigent-cli",
    "health": "dirigent-cli",
    "testing": "dirigent-testing",
    "base": "dirigent-block-base",
    "execute": "dirigent-block-execute",
    "http": "dirigent-block-http",
    "parquet": "dirigent-block-parquet",
    "queues": "dirigent-block-queues",
    "sql": "dirigent-block-sql",
    "sql.duckdb": "dirigent-block-sql-duckdb",
    "storage": "dirigent-block-storage",
    "transform.jq": "dirigent-block-transform-jq",
}


def test_a_message_renders_its_template_with_the_params_it_names() -> None:
    catalogue = Catalogue("test_render")
    message = catalogue.define("greeted", "no pipeline coded {code}")

    assert message.code == "test_render.greeted"
    assert message.render(code="'daily'") == "no pipeline coded 'daily'"


def test_a_missing_param_is_refused_at_render() -> None:
    catalogue = Catalogue("test_missing")
    message = catalogue.define("needs_one", "no pipeline coded {code}")

    with pytest.raises(MessageError, match="has no value for 'code'"):
        message.render()


def test_a_message_names_the_params_its_template_renders() -> None:
    catalogue = Catalogue("test_fields")
    message = catalogue.define("two", "{first} and {second}")

    assert message.fields == frozenset({"first", "second"})


def test_a_duplicate_name_in_one_catalogue_is_refused() -> None:
    catalogue = Catalogue("test_duplicate")
    catalogue.define("once", "said once")

    with pytest.raises(MessageError, match="defined twice"):
        catalogue.define("once", "said twice")


def test_a_name_that_is_not_lowercase_snake_is_refused() -> None:
    catalogue = Catalogue("test_names")

    with pytest.raises(MessageError, match="is not a message name"):
        catalogue.define("NotThis", "no")


def test_a_prefix_that_is_not_dotted_lowercase_is_refused() -> None:
    with pytest.raises(MessageError, match="is not a prefix"):
        Catalogue("Not This")


def test_an_issue_carries_the_code_the_message_it_rendered_owns() -> None:
    catalogue = Catalogue("test_issue")
    message = catalogue.define("wrong", "{what} is wrong")

    issue = Issue.of(message, location="steps.push", what="the method")

    assert issue.code == "test_issue.wrong"
    assert issue.message == "the method is wrong"
    assert issue.params == {"what": "the method"}
    assert str(issue) == "steps.push: the method is wrong"


def test_an_issue_with_no_place_renders_as_its_message_alone() -> None:
    catalogue = Catalogue("test_placeless")
    assert str(Issue.of(catalogue.define("plain", "just this"))) == "just this"


def test_a_pydantic_error_becomes_an_issue_coded_by_its_own_error_type() -> None:
    issues = validation_issues([{"type": "missing", "loc": ("body", "code"), "msg": "Field required", "input": {}}])

    assert issues[0].code == "validation.missing"
    assert issues[0].message == "Field required"
    assert issues[0].location == "body.code"
    assert issues[0].params["loc"] == ["body", "code"]
    assert issues[0].params["input_kind"] == "dict"


def test_a_pydantic_errors_input_value_never_reaches_the_params() -> None:
    issues = validation_issues(
        [{"type": "string_type", "loc": ("body", "token"), "msg": "Input should be a valid string", "input": "s3cret"}]
    )

    assert "s3cret" not in str(issues[0].params)
    assert issues[0].params["input_kind"] == "str"


def test_an_unknown_key_is_worded_by_us_and_carries_the_suggestion() -> None:
    from dirigent_common.messages import validation_issue

    issue = validation_issue(
        {"type": "extra_forbidden", "loc": ("steps",), "msg": "Extra inputs are not permitted"},
        suggestion=" (did you mean 'step'?)",
    )

    assert issue.code == EXTRA_FORBIDDEN.code
    assert issue.message == "unknown key (did you mean 'step'?)"


def test_every_catalogue_the_workspace_imports_owns_its_prefix_and_its_codes() -> None:
    for module in MODULES:
        importlib.import_module(module)

    seen: dict[str, Message] = {}
    for catalogue in Catalogue.all:
        if catalogue.prefix.startswith("test_"):
            continue
        assert catalogue.prefix in OWNED, f"{catalogue.prefix} is not in the owned-prefix table"
        for message in catalogue.messages.values():
            assert message.code not in seen, f"{message.code} is defined by two catalogues"
            seen[message.code] = message
    assert len(seen) > 200
