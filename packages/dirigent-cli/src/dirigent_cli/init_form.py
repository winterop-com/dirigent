"""The ``dg init`` form: one Textual screen instead of a run of flags and prompts.

Everything is visible at once and revised before anything is written: where the project
runs, which services the stack carries, which packs come along, and the first admin. The
form returns the choices and the caller scaffolds, so quitting leaves no half-made project.
Nothing here touches the disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, SelectionList

from dirigent_cli.project import (
    DEFAULT_SERVICES,
    PACKS,
    SERVICES,
    InitChoices,
    installed_starters,
)

if TYPE_CHECKING:
    from dirigent_core.examples import ExampleEntry

MIN_PASSWORD_LENGTH = 8

#: The web UI's dark palette, so the form is the same product as the screen behind the door:
#: the amber accent on the near-black ground, with the same surfaces, inks and status colours.
DIRIGENT_THEME = Theme(
    name="dirigent",
    primary="#e9b452",
    secondary="#00a7e2",
    accent="#e9b452",
    foreground="#eaeff5",
    background="#070a0f",
    surface="#10151c",
    panel="#191f26",
    success="#5cb85c",
    warning="#f9b64f",
    error="#ed5350",
    dark=True,
    variables={
        "input-cursor-background": "#e9b452",
        "input-cursor-foreground": "#0a0e12",
        "input-selection-background": "#e9b45240",
        "block-cursor-background": "#e9b452",
        "block-cursor-foreground": "#0a0e12",
        "border": "#323941",
        "border-blurred": "#191f26",
        "footer-background": "#10151c",
        "button-color-foreground": "#0a0e12",
    },
)

#: The three places a project runs, in the order the form lists them.
KINDS = (
    ("local", "Local: one process on SQLite", "dg dev; one person, one machine"),
    ("compose", "A container stack", "compose: PostgreSQL, workers, the published image"),
    ("documents", "Documents only", "against an instance somebody else runs"),
)


#: How much of a starter's description fits on the line that offers it.
DESCRIPTION_WIDTH = 60


def starter_label(entry: ExampleEntry) -> str:
    """Name one starter the way every screen names an addressable thing.

    The title is the name where there is one and the code otherwise, the code is on the line
    exactly once, and the description is the rest of it.
    """
    described = (entry.description or "").strip().splitlines()
    first = described[0] if described else ""
    if len(first) > DESCRIPTION_WIDTH:
        first = first[: DESCRIPTION_WIDTH - 1].rstrip() + "\u2026"
    trailing = "  ".join(part for part in ([entry.code] if entry.name else []) + ([first] if first else []))
    return f"{entry.name or entry.code}  [dim]{trailing}[/]" if trailing else entry.name or entry.code


class InitForm(App[InitChoices | None]):
    """The scaffolding form: kind, services, packs, workflow, admin, on one screen."""

    TITLE = "dg init"

    CSS = """
    Screen { padding: 1 2; }
    #body { height: 1fr; }
    Label { width: 1fr; }
    .section { color: $text-muted; margin-top: 1; }
    .hint { color: $text-muted; }
    SelectionList > .selection-list--button { color: $surface; background: $surface; }
    SelectionList > .selection-list--button-selected { color: $success; background: $surface; }
    SelectionList > .selection-list--button-highlighted { color: $surface; background: $surface; }
    SelectionList > .selection-list--button-selected-highlighted { color: $success; background: $surface; }
    Checkbox > .toggle--button { color: $surface; background: $surface; }
    Checkbox.-on > .toggle--button { color: $success; background: $surface; }
    #kind { height: auto; }
    #services, #packs, #starters { height: auto; max-height: 12; border: round $border; }
    #admin-block { height: auto; }
    #admin-row { height: auto; }
    #admin-row Input { width: 1fr; margin-right: 2; }
    #problem { color: $error; height: auto; }
    #files { color: $text-muted; height: auto; margin-top: 1; }
    #actions { height: auto; margin-top: 1; }
    #actions Button { margin-right: 2; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+s", "create", "Create", show=True, priority=True),
    ]

    def __init__(self, directory: Path, *, version: str, admin: str = "admin", password: str = "") -> None:
        """Open on a directory, the runtime it will pin, and whatever the flags already said."""
        super().__init__()
        self.register_theme(DIRIGENT_THEME)
        self.theme = "dirigent"
        self._directory = directory
        self._version = version
        self._admin = admin
        self._password = password
        self._starters = installed_starters()

    def compose(self) -> ComposeResult:
        """Lay the whole form out on one screen."""
        yield Label(f"New dirigent project: {self._directory.name}")
        yield Label(
            f"The documents, the runtime it pins ({self._version}) and its instance, all in this directory.",
            classes="hint",
        )
        with VerticalScroll(id="body"):
            yield Label("Where it runs", classes="section")
            with RadioSet(id="kind"):
                for index, (code, title, what) in enumerate(KINDS):
                    yield RadioButton(f"{title}  [dim]{what}[/]", value=index == 0, id=f"kind-{code}")

            yield Label("Services in the stack  (space toggles)", classes="section", id="services-label")
            yield SelectionList[str](
                *(
                    (f"{service.title}  [dim]{service.what}[/]", service.code, service.code in DEFAULT_SERVICES)
                    for service in SERVICES
                ),
                id="services",
            )

            yield Label("First pipelines  (space toggles; copied from the installed corpus)", classes="section")
            yield SelectionList[str](
                *((starter_label(entry), entry.code) for entry in self._starters),
                id="starters",
            )

            yield Label("Packs  (space toggles; pinned at this version)", classes="section")
            yield SelectionList[str](*((f"{pack.name}  [dim]{pack.what}[/]", pack.name) for pack in PACKS), id="packs")

            yield Checkbox("A GitHub workflow that applies the project on merge", id="workflow")

            with Vertical(id="admin-block"):
                yield Label("First admin", classes="section")
                with Horizontal(id="admin-row"):
                    yield Input(value=self._admin, placeholder="username", id="admin")
                    yield Input(value=self._password, placeholder="password", password=True, id="password")
                    yield Input(value=self._password, placeholder="confirm", password=True, id="confirm")
                yield Label(f"At least {MIN_PASSWORD_LENGTH} characters, typed twice.", classes="hint")

            yield Label("", id="problem")
            yield Label("", id="files")
        with Horizontal(id="actions"):
            yield Button("Create project", variant="primary", id="create")
            yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        """Open on the kind, and say what the defaults will write."""
        self.query_one("#kind", RadioSet).focus()
        self._follow_kind()

    @property
    def kind(self) -> str:
        """The place the project runs, as the radio set has it."""
        pressed = self.query_one("#kind", RadioSet).pressed_button
        return pressed.id.removeprefix("kind-") if pressed is not None and pressed.id else "local"

    def _follow_kind(self) -> None:
        """Show the services for the stack alone, and the admin for the two kinds that make one."""
        kind = self.kind
        stack = kind == "compose"
        self.query_one("#services-label").display = stack
        self.query_one("#services").display = stack
        self.query_one("#admin-block").display = kind != "documents"
        self._refresh_files()

    def on_radio_set_changed(self, _event: RadioSet.Changed) -> None:
        """A kind decides which sections apply."""
        self._follow_kind()

    def on_selection_list_selected_changed(self, _event: SelectionList.SelectedChanged[str]) -> None:
        """A toggle changes what is written."""
        self._refresh_files()

    def on_checkbox_changed(self, _event: Checkbox.Changed) -> None:
        """The workflow box changes what is written."""
        self._refresh_files()

    def _collect(self) -> InitChoices:
        """Read the form into choices, as they stand."""
        # query_one's type argument is a runtime isinstance check, so it cannot take a
        # subscripted generic: the widgets are fetched untyped and narrowed here.
        services = cast("SelectionList[str]", self.query_one("#services"))
        packs = cast("SelectionList[str]", self.query_one("#packs"))
        chosen = cast("SelectionList[str]", self.query_one("#starters"))
        picked_services: list[str] = list(services.selected)
        picked_packs: list[str] = list(packs.selected)
        picked_starters: list[str] = list(chosen.selected)
        kind = self.kind
        chosen_services = tuple(code for code in (s.code for s in SERVICES) if code in picked_services)
        return InitChoices(
            template=kind,
            services=chosen_services if kind == "compose" else DEFAULT_SERVICES,
            workflow=self.query_one("#workflow", Checkbox).value,
            packs=tuple(name for name in (p.name for p in PACKS) if name in picked_packs),
            pipelines=tuple(entry.code for entry in self._starters if entry.code in picked_starters),
            admin=self.query_one("#admin", Input).value.strip() or "admin",
            password=self.query_one("#password", Input).value,
        )

    def _refresh_files(self) -> None:
        """Say what Create will write, so the file list after the fact is not the first sight of it."""
        choices = self._collect()
        files = [
            "dirigent.yaml",
            *(f"pipelines/{code}.yaml" for code in choices.pipelines),
            ".dirigent/profiles.yaml",
            "pyproject.toml",
            "README.md",
        ]
        if choices.stack:
            files += ["compose.yaml", "Dockerfile", ".env"]
        elif choices.instance:
            files += [".env", ".dirigent/state/"]
        if choices.workflow:
            files.append(".github/workflows/dirigent.yml")
        self.query_one("#files", Label).update("Will write: " + ", ".join(files))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """The two buttons are the two bindings."""
        if event.button.id == "create":
            self.action_create()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        """Leave with nothing, so nothing is written."""
        self.exit(None)

    def action_create(self) -> None:
        """Refuse an admin the instance could not be made with, else hand the choices back."""
        choices = self._collect()
        problem = self.query_one("#problem", Label)
        if choices.template != "documents":
            confirm = self.query_one("#confirm", Input).value
            if choices.stack and choices.admin != "admin":
                problem.update("The stack's first admin is named admin.")
                return
            if len(choices.password) < MIN_PASSWORD_LENGTH:
                problem.update(f"A password must be at least {MIN_PASSWORD_LENGTH} characters.")
                self.query_one("#password", Input).focus()
                return
            if confirm != choices.password:
                problem.update("The two passwords differ.")
                self.query_one("#confirm", Input).focus()
                return
        self.exit(choices)


def run_form(directory: Path, *, version: str, admin: str = "admin", password: str = "") -> InitChoices | None:
    """Run the form, returning the choices, or None when the person quit."""
    return InitForm(directory, version=version, admin=admin, password=password).run()
