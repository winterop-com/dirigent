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
