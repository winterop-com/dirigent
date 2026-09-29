"""Every word this product says in two languages, held to one wording by one test.

WHY THIS EXISTS. ``packages/dirigent-server/frontend/src/lib/labels.ts`` is the only place a word
the web UI says may live, and ``dirigent_common.messages`` is the same rule for every word Python
says. Some words are said by both: the four alert events, a credential's health, why a document
that is empty is refused, the floor an alert rule fires at, the role gate's own sentence. Neither
side can import the other's table -- one is TypeScript in a browser, the other is Python in a
wheel that ships no frontend source -- and the wire cannot carry the word either, because the
wire's value is the key and never the label. So the copy stays, and drifting it fails here.

ADDING A WORD BOTH SIDES SAY IS ADDING A ROW BELOW. That is the whole of the mechanism, and it is
cheap because ``scripts/check_ui_labels.entries`` already reads the catalogue as text for the gate
that ``make static`` runs.

WHAT IS NOT PAIRED, AND WHY. A sentence each surface writes for its own shape is not one string:
the CLI's worker check states a count and a silence in seconds, and the UI's row is a fragment
after a worker's name. Those share a *word* and this file holds them to that, which is the drift
that was actually there -- "went silent" beside "has gone quiet".
"""

import re
import sys
from pathlib import Path

import pytest

from dirigent_cli.messages import WORKER_NEVER_REGISTERED, WORKER_SILENT
from dirigent_cli.output import ALERT_EVENTS, CONNECTION_HEALTH, IMPORTANCE_FLOOR
from dirigent_client.enums import AlertEvent, FiringOutcome, WebhookOutcome
from dirigent_core.messages import DOCUMENT_EMPTY
from dirigent_server.messages import FORBIDDEN

REPO_ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_ui_labels import entries  # noqa: E402  # isort: skip


def catalogue() -> dict[str, str]:
    """Read the web UI's catalogue as code -> what it says.

    Returns:
        Every label, under the dotted code the path through ``LABELS`` mints.
    """
    return dict(entries())


#: Read once: the file is on disk and every test below asks it the same question.
LABELS = catalogue()


def said(code: str) -> str:
    """What the catalogue says under one code.

    Args:
        code: The dotted code, as ``scripts/ui_copy.py`` prints it.

    Returns:
        The label as written, with its quotes taken off.
    """
    assert code in LABELS, f"{code} is not in the web UI's catalogue"
    return LABELS[code]


def sentence(code: str) -> str:
    """Read a catalogued sentence that takes values as a Python format string.

    A label with a value in it is a TypeScript arrow returning a template literal, so the
    catalogue holds its source rather than its text. Turning ``${name}`` into ``{name}`` is what
    lets the two languages' versions of one sentence be compared as the same string.

    Args:
        code: The dotted code of a label that takes parameters.

    Returns:
        The template, with each hole written the way Python writes one.
    """
    written = said(code)
    found = re.search(r"`(.*)`", written, re.DOTALL)
    assert found is not None, f"{code} is not a template literal: {written!r}"
    return re.sub(r"\$\{([A-Za-z_][\w]*)\}", r"{\1}", found.group(1))


def as_fragment(text: str) -> str:
    """Reduce a sentence to the words in it, so a fragment and a sentence can be compared.

    The server writes a refusal's ``detail`` as a lower-case fragment, because it is rendered
    inside whatever the client puts around it; the web UI draws the same fact as a sentence of
    its own. They are the same words either way, and that is what is held here.

    Args:
        text: A sentence or a fragment.

    Returns:
        Its words, lower case, with a trailing full stop taken off.
    """
    return text.lower().rstrip(".")


@pytest.mark.parametrize("event", list(AlertEvent))
def test_an_alert_event_is_called_the_same_thing_by_dg_and_by_the_web_ui(event: AlertEvent) -> None:
    """The clearest case in the product: two byte-identical tables, one for each language."""
    assert ALERT_EVENTS[event.value] == said(f"alerting.event.{event.value}")


def test_every_alert_event_on_the_wire_has_a_word_on_both_sides() -> None:
    """A new member of the enum is a word each renderer has to be given, not a code on a screen."""
    wire = {event.value for event in AlertEvent}
    assert set(ALERT_EVENTS) == wire
    assert {code.removeprefix("alerting.event.") for code in LABELS if code.startswith("alerting.event.")} == wire


@pytest.mark.parametrize("state", sorted(CONNECTION_HEALTH))
def test_a_credential_reads_the_same_wherever_its_health_is_drawn(state: str) -> None:
    """One vocabulary for a connection's last check: `dg` said `unhealthy` and `no` for `failed`."""
    code = "state.health.failed.word" if state == "failed" else f"state.health.{state}"
    assert CONNECTION_HEALTH[state] == said(code)


def test_a_document_that_is_empty_is_refused_in_one_sentence() -> None:
    """The browser parses the source pane itself, and says what the server would have said."""
    assert DOCUMENT_EMPTY.text == said("editor.source.empty")


def test_an_alert_rules_importance_floor_is_written_the_same_way() -> None:
    """`dg` puts the scope in front of this half; the half itself is one sentence."""
    assert sentence("alerting.importance_floor") == IMPORTANCE_FLOOR


def test_a_role_gate_refuses_in_one_wording() -> None:
    """The bundle shuts a control before the request; the server refuses it after. One sentence."""
    assert as_fragment(said("refusal.shut")) == as_fragment(FORBIDDEN.text)


def test_a_fleet_nothing_has_registered_with_opens_with_the_same_words() -> None:
    """The CLI's check names where it looked; the UI's line is the same fact without the place."""
    assert WORKER_NEVER_REGISTERED.text.startswith(said("dashboard.health.no_worker"))


def test_a_worker_nobody_has_heard_from_is_silent_on_both_sides() -> None:
    """Two shapes, one word. The UI said `quiet` of exactly what `health.worker.silent` names."""
    assert "silent" in WORKER_SILENT.text
    assert "silent" in said("state.worker.silent")


@pytest.mark.parametrize("outcome", list(FiringOutcome))
def test_every_firing_outcome_has_a_word_the_web_ui_can_draw(outcome: FiringOutcome) -> None:
    """The schedules table drew the wire's value raw, so no review and no translation reached it."""
    assert said(f"triggers.schedule.outcome.{outcome.value}")


@pytest.mark.parametrize("outcome", list(WebhookOutcome))
def test_every_delivery_outcome_has_a_word_the_web_ui_can_draw(outcome: WebhookOutcome) -> None:
    """The same fault on the webhook panel, and the same answer."""
    assert said(f"triggers.webhook.outcome.{outcome.value}")
