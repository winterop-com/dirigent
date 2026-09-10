"""Value types and shared schemas every dirigent package may depend on.

This package knows nothing of blocks, the wire, or the engine. Everything here is something
more than one package has to agree on: how a document spells a duration or a size, what a
name may be, and the small schemas a plugin and the API both name.
"""

from dirigent_common.clients import build_client
from dirigent_common.docstrings import as_markdown
from dirigent_common.durations import (
    DURATION_PATTERN,
    Duration,
    DurationError,
    HumaneJsonSchema,
    NegativeDuration,
    format_duration,
    parse_duration,
    to_timedelta,
)
from dirigent_common.formats import base_format_checker, format_checker_with
from dirigent_common.formatters import Formatter
from dirigent_common.names import (
    EMAIL_MAX_LENGTH,
    EMAIL_PATTERN,
    ENTITY_NAME_MAX_LENGTH,
    ENTITY_NAME_PATTERN,
    STEP_NAME_MAX_LENGTH,
    STEP_NAME_PATTERN,
    Email,
    EntityName,
    StepName,
    entity_name_error,
    is_entity_name,
    is_step_name,
    step_name_error,
)
from dirigent_common.programs import JQ_MEDIA_TYPE, SHELL_MEDIA_TYPE, TEMPLATE_MEDIA_TYPE
from dirigent_common.schemas import BlockModel, HealthReport, HttpConnectionConfig
from dirigent_common.sizes import (
    SIZE_PATTERN,
    NegativeSize,
    Size,
    SizeError,
    format_size,
    parse_size,
)
from dirigent_common.templating import RenderTooLarge, TemplateError, compile_template, render
from dirigent_common.types import JsonList, JsonMap
from dirigent_common.uris import STORAGE_URI_FORMAT, StorageUri
from dirigent_common.values import spelled
from dirigent_common.versions import API_VERSION

__all__ = [
    "base_format_checker",
    "format_checker_with",
    "API_VERSION",
    "DURATION_PATTERN",
    "EMAIL_MAX_LENGTH",
    "EMAIL_PATTERN",
    "ENTITY_NAME_MAX_LENGTH",
    "ENTITY_NAME_PATTERN",
    "JQ_MEDIA_TYPE",
    "SHELL_MEDIA_TYPE",
    "TEMPLATE_MEDIA_TYPE",
    "SIZE_PATTERN",
    "STORAGE_URI_FORMAT",
    "STEP_NAME_MAX_LENGTH",
    "STEP_NAME_PATTERN",
    "BlockModel",
    "Duration",
    "DurationError",
    "Email",
    "EntityName",
    "Formatter",
    "HealthReport",
    "HttpConnectionConfig",
    "HumaneJsonSchema",
    "JsonList",
    "JsonMap",
    "NegativeDuration",
    "NegativeSize",
    "RenderTooLarge",
    "Size",
    "SizeError",
    "StepName",
    "StorageUri",
    "TemplateError",
    "as_markdown",
    "entity_name_error",
    "build_client",
    "compile_template",
    "format_duration",
    "format_size",
    "is_entity_name",
    "is_step_name",
    "parse_duration",
    "parse_size",
    "render",
    "spelled",
    "step_name_error",
    "to_timedelta",
]
