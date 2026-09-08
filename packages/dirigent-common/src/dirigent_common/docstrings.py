"""Reading a Python docstring as the markdown every reader of it renders.

A description of a block's config, a setting or a surface is authored as a docstring, so it is
written in reStructuredText; the UI, the CLI and the generated reference all render markdown.
This is the rule for crossing between the two, and it is applied where a docstring becomes a
description rather than by anything that later reads one.
"""

import re
from typing import Final

#: A reStructuredText inline literal, which is how a docstring writes code.
RST_LITERAL: Final = re.compile(r"``(.+?)``", re.DOTALL)


def as_markdown(text: str) -> str:
    """Rewrite a docstring's inline literals as markdown inline code."""
    return RST_LITERAL.sub(r"`\1`", text)
