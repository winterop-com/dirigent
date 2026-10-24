"""Every refusal the block contract itself makes, catalogued under the ``plugin`` prefix."""

from dirigent_common import Catalogue

PLUGIN = Catalogue("plugin")

TRANSFORM_FAILED = PLUGIN.define("transform_failed", "{detail}")

PROGRAM_REFUSED = PLUGIN.define("program_refused", "{detail}")

ELEMENT_FAILED = PLUGIN.define("element_failed", "element {index}: {detail}")

FILTER_ANSWER = PLUGIN.define(
    "filter_answer",
    "{block} answered {answer} for element {index}, and a filter's answer is true or false",
)

UNSUPPORTED_PAIR = PLUGIN.define(
    "unsupported_pair",
    "{block} does not convert {source_format} to {target_format} ({supported})",
)

NOT_AN_ARRAY = PLUGIN.define(
    "not_an_array",
    "{block} {promise}, so its input has to be a JSON array, and this one is {described}",
)

NOTHING_TO_CONVERT = PLUGIN.define("nothing_to_convert", "there is nothing at {uri} to convert")

# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

UNSUPPORTED_API_VERSION = PLUGIN.define(
    "unsupported_api_version",
    "unsupported api_version {version}; this host speaks {host_version}",
)

DUPLICATE_ID = PLUGIN.define("duplicate_id", "duplicate {label} {value} in contribution")

INVALID_MARK = PLUGIN.define(
    "invalid_mark",
    "the mark connection kind {kind} declares is not SVG path data: {detail}",
)

# What a received source's path template refuses.

ROUTE_NOT_ROOTED = PLUGIN.define("route_not_rooted", "the path {template} does not start with '/'")

ROUTE_BAD_PARAMETER = PLUGIN.define(
    "route_bad_parameter",
    "the path {template} has the segment {segment}, and a parameter is a whole segment written "
    "as {{name}}, or {{name:path}} for the rest of the path, with a snake_case name",
)

ROUTE_BAD_SEGMENT = PLUGIN.define(
    "route_bad_segment", "the path {template} has the segment {segment}, which a path cannot carry"
)

ROUTE_REPEATED_PARAMETER = PLUGIN.define(
    "route_repeated_parameter", "the path {template} names the parameter {name} twice"
)

ROUTE_TAIL_NOT_LAST = PLUGIN.define(
    "route_tail_not_last", "the path {template} has {segment} before its end, and a tail takes the rest of the path"
)
