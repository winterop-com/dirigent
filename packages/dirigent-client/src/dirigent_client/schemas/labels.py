"""The label table a surface renders a contributed pack's refusals from."""

from pydantic import BaseModel, Field

from dirigent_common import API_VERSION


class Labels(BaseModel):
    """Every code an installed pack can refuse under, with the template it renders from.

    The instance's own codes are not here. A surface that draws refusals ships its own table for
    those, translated with the rest of its words; what it cannot know is which packs are
    installed, so that is what this answers.
    """

    api_version: int = API_VERSION
    templates: dict[str, str] = Field(default_factory=dict[str, str])
    """Every contributed code, mapped to the English template its params are written into.

    A named hole in a template -- ``{status}`` -- is filled from the params the refusal carries
    beside its code. A renderer with a translation of its own uses this as the fallback."""
