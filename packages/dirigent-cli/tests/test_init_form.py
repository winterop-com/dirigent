"""Headless pilot tests for the `dg init` form."""

from pathlib import Path

from textual.widgets import Input, RadioButton

from dirigent_cli.init_form import InitForm


def form(**kwargs: str) -> InitForm:
    return InitForm(Path("/somewhere/hello"), version="1.2.3", **kwargs)


async def test_the_defaults_make_a_local_instance() -> None:
    """Enter on nothing but a password gives today's default: an instance here, admin, no extras."""
    app = form(password="a-long-enough-password")
    async with app.run_test() as pilot:
        await pilot.press("ctrl+s")
    chosen = app.return_value
    assert chosen is not None
    assert chosen.template == "local"
    assert chosen.admin == "admin"
    assert chosen.password == "a-long-enough-password"
    assert chosen.packs == ()
    assert chosen.workflow is False


async def test_quitting_returns_nothing_so_no_project_is_written() -> None:
    app = form()
    async with app.run_test() as pilot:
        await pilot.press("escape")
    assert app.return_value is None


async def test_a_short_password_cannot_be_submitted() -> None:
    app = form(password="short")
    async with app.run_test() as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.return_value is None
        assert "at least 8" in str(app.query_one("#problem").render())
        assert app.focused is app.query_one("#password", Input)


async def test_the_two_passwords_have_to_agree() -> None:
    app = form(password="a-long-enough-password")
    async with app.run_test() as pilot:
        app.query_one("#confirm", Input).value = "a-different-password"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.return_value is None
        assert "differ" in str(app.query_one("#problem").render())


async def test_the_stack_shows_its_services_and_carries_the_toggled_ones() -> None:
    """Services are a real multi-select, shown for the stack alone, with S3 on by default."""
    app = form(password="a-long-enough-password")
    async with app.run_test() as pilot:
        assert app.query_one("#services").display is False
        app.query_one("#kind-compose", RadioButton).value = True
        await pilot.pause()
        assert app.query_one("#services").display is True
        app.query_one("#services").focus()
        await pilot.pause()
        await pilot.press("down", "space")  # docker, beside the s3 default
        await pilot.press("ctrl+s")
    chosen = app.return_value
    assert chosen is not None
    assert chosen.template == "compose"
    assert chosen.services == ("s3", "docker")


async def test_documents_only_asks_for_no_admin() -> None:
    app = form()
    async with app.run_test() as pilot:
        app.query_one("#kind-documents", RadioButton).value = True
        await pilot.pause()
        assert app.query_one("#admin-block").display is False
        await pilot.press("ctrl+s")
    chosen = app.return_value
    assert chosen is not None
    assert chosen.template == "documents"


async def test_a_pack_and_the_workflow_travel() -> None:
    app = form(password="a-long-enough-password")
    async with app.run_test() as pilot:
        app.query_one("#packs").focus()
        await pilot.pause()
        await pilot.press("space")
        app.query_one("#workflow").focus()
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("ctrl+s")
    chosen = app.return_value
    assert chosen is not None
    assert chosen.packs == ("dirigent-dhis2",)
    assert chosen.workflow is True


async def test_the_form_says_what_it_will_write_before_creating() -> None:
    app = form(password="a-long-enough-password")
    async with app.run_test() as pilot:
        await pilot.pause()
        listed = str(app.query_one("#files").render())
        assert ".dirigent/state/" in listed
        app.query_one("#kind-compose", RadioButton).value = True
        await pilot.pause()
        listed = str(app.query_one("#files").render())
        assert "compose.yaml" in listed
        assert "pipelines/" not in listed, "a stack writes no pipeline unless one was chosen"
