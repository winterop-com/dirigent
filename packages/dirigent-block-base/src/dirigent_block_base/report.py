"""``report.render``: text from a Jinja template, handed on as the step's output."""

from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, Field

from dirigent_common import (
    TEMPLATE_MEDIA_TYPE,
    BlockModel,
    JsonMap,
    RenderTooLarge,
    Size,
    TemplateError,
    compile_template,
    render,
)
from dirigent_plugin import BlockFailure, ErrorClass, Operator, OperatorSpec, StepContext


class ReportRenderConfig(BlockModel):
    """The template, and what it is rendered against."""

    template: Annotated[str, Field(min_length=1, json_schema_extra={"contentMediaType": TEMPLATE_MEDIA_TYPE})]
    """The Jinja template, rendered against ``values``."""

    values: JsonMap = Field(default_factory=dict[str, Any])
    """What the template sees, each key a name in it.

    Fed by ``${steps.<step>.output}`` references, so a page is written over what the steps
    above it produced."""

    content_type: str = "text/markdown"
    """What the rendered text is, passed on for a sink to record."""

    max_size: Size = 1 * 1024 * 1024
    """How much text this step will build, such as ``256kb``.

    The cap is applied as the text is generated, so a loop over more rows than anyone meant
    to render stops at the cap rather than after the whole string is built."""


class ReportRenderOutput(BlockModel):
    """The rendered text, for the step that sends it somewhere."""

    text: str
    content_type: str
    text_bytes: int


class ReportRenderOperator(Operator[ReportRenderConfig, ReportRenderOutput]):
    """Renders a template into text and hands it on.

    Nothing is saved here: the text is the step's output, and a following ``storage.write``,
    ``kafka.produce``, ``rabbitmq.publish`` or ``webhook.post`` is what sends it anywhere. It
    runs on any worker with nothing on the allowlist, because it touches nothing.

    The template renders in the same sandbox the run's own ``report:`` section uses: no
    loader, so ``include``, ``import`` and ``extends`` reach nothing, and an undefined name
    renders as the empty string rather than failing the step.
    """

    spec = OperatorSpec(id="report.render", summary="Render text from a Jinja template.", idempotent=True)
    config_model: ClassVar[type[BaseModel]] = ReportRenderConfig
    output_model: ClassVar[type[BaseModel]] = ReportRenderOutput

    async def execute(self, config: ReportRenderConfig, ctx: StepContext) -> ReportRenderOutput:
        """Render the template against the values, and report what the text is."""
        try:
            text = render(config.template, config.values, max_bytes=int(config.max_size))
        except (RenderTooLarge, TemplateError) as error:
            raise BlockFailure(str(error), error_class=ErrorClass.REJECTED) from error
        size = len(text.encode())
        ctx.log.info("rendered", content_type=config.content_type, text_bytes=size)
        return ReportRenderOutput(text=text, content_type=config.content_type, text_bytes=size)

    def check_config(self, config: BaseModel) -> list[str]:
        """Compile the template at apply, so a bad one is refused before the document is stored."""
        if not isinstance(config, ReportRenderConfig):
            return []
        try:
            compile_template(config.template)
        except TemplateError as error:
            return [str(error)]
        return []
