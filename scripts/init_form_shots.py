"""Render the `dg init` form headless into the SVG screenshots the docs show.

    uv run python scripts/init_form_shots.py

Writes docs/images/init-form.svg (the form as it opens) and docs/images/init-form-stack.svg
(the stack chosen, with its services), at a fixed terminal size so the two agree.
"""

import asyncio
from pathlib import Path

from textual.widgets import RadioButton

from dirigent_cli.init_form import InitForm

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
SIZE = (100, 46)


async def shoot() -> None:
    """Open the form twice and save what each state looks like."""
    OUT.mkdir(parents=True, exist_ok=True)
    app = InitForm(Path("/home/you/hello"), version="0.10.0", password="a-long-enough-password")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.save_screenshot(filename="init-form.svg", path=str(OUT))
        app.query_one("#kind-compose", RadioButton).value = True
        await pilot.pause()
        app.query_one("#services").focus()
        await pilot.pause()
        await pilot.press("down", "space")
        await pilot.pause()
        app.save_screenshot(filename="init-form-stack.svg", path=str(OUT))
        await pilot.press("escape")


if __name__ == "__main__":
    asyncio.run(shoot())
