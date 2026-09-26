"""Every refusal the base family makes, catalogued under the ``base`` prefix."""

from dirigent_common import Catalogue

BASE = Catalogue("base")

TEMPLATE_FAILED = BASE.define("template_failed", "{detail}")

TEMPLATE_REFUSED = BASE.define("template_refused", "{detail}")

CHILD_RUN_GONE = BASE.define("child_run_gone", "run {run} disappeared before its result could be read")

NOT_A_RUN_HANDLE = BASE.define("not_a_run_handle", "the handle {handle} does not name a run")

VALUE_REFUSED = BASE.define("value_refused", "at {location}: {detail}")


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

NOT_A_TIMEZONE = BASE.define(
    "not_a_timezone",
    "{value} is not an IANA timezone name, such as 'Europe/Oslo' or 'UTC'",
)

EMPTY_WINDOW = BASE.define(
    "empty_window",
    "a window from {after} to {before} is empty; omit the sensor rather than writing a window nothing falls in",
)


# What the ``convert.std`` codec refuses. A codec refusal reaches an attempt as
# ``plugin.transform_failed``: the convert frame owns the failure, and the codec's sentence
# rides on it as the ``detail`` param.

NOT_UTF8 = BASE.define(
    "not_utf8",
    "the input is not UTF-8 text: {reason} at byte {position}; convert.std reads and writes UTF-8",
)

NOT_JSON = BASE.define("not_json", "the input is not JSON: {detail}")

NOT_A_JSON_ARRAY = BASE.define(
    "not_a_json_array",
    "json to {target_format} writes one {unit} per element, so the input has to be "
    "a JSON array, and this one is {described}",
)

LINE_NOT_JSON = BASE.define("line_not_json", "line {number} of the input is not JSON: {detail}")

CSV_ROW_TOO_WIDE = BASE.define(
    "csv_row_too_wide",
    "row {number} of the csv has more cells than the header names columns, "
    "and a cell no column names has nowhere to go",
)

CSV_HEADER_UNNAMED = BASE.define(
    "csv_header_unnamed",
    "the csv header has no name at {columns}, and a record key names its column; name it before converting",
)

CSV_HEADER_REPEATED = BASE.define(
    "csv_header_repeated",
    "the csv header repeats a column name: {listed}; a record key names one column, so rename them before converting",
)

CSV_ROW_NOT_AN_OBJECT = BASE.define(
    "csv_row_not_an_object",
    "row {number} of the input is {described}, and a csv row is a flat object",
)

CSV_NESTED_VALUE = BASE.define(
    "csv_nested_value",
    "row {number} has a nested value at {key}, and a csv cell holds one value; "
    "flatten it before converting, because writing it as text would not be the same content",
)

NOT_YAML = BASE.define("not_yaml", "the input is not YAML: {detail}")

YAML_STREAM = BASE.define(
    "yaml_stream",
    "the input is a YAML stream of {counted} documents, and yaml to json reads one document "
    "as one value; convert it to ndjson to write one line per document",
)

YAML_NOT_A_NUMBER = BASE.define(
    "yaml_not_a_number",
    "the YAML number at {path} is {value}, and JSON writes no nan or infinity; "
    "quote it in the source to convert it as text",
)

YAML_KEY_NOT_A_STRING = BASE.define(
    "yaml_key_not_a_string",
    "the YAML mapping at {path} is keyed by {key}, and a JSON key is a string; "
    "quote the key in the source to convert it",
)

YAML_UNSPELLABLE = BASE.define("yaml_unspellable", "the YAML value at {path} is {described}")

XML_HAS_A_DOCTYPE = BASE.define(
    "xml_has_a_doctype",
    "the input carries a <!DOCTYPE declaration, and convert.std reads XML without a DTD, "
    "because a DTD is where entities and the files they name enter a document",
)

NOT_XML = BASE.define("not_xml", "the input is not XML: {detail}")

XML_ROOT_HAS_TEXT = BASE.define(
    "xml_root_has_text",
    "the element at {tag} has text beside its child elements, and the records xml to ndjson writes are those children",
)

XML_ELEMENT_HAS_TEXT = BASE.define(
    "xml_element_has_text",
    "the element at {path} has text beside its child elements, and this mapping keeps an "
    "element's text under {text_key} only where the element has no children",
)

XML_ONE_ROOT = BASE.define(
    "xml_one_root",
    "json to xml writes one root element, so the input has to be an object of exactly one key "
    "naming it, and this one is {shape}",
)

XML_KEY_IS_NO_NAME = BASE.define(
    "xml_key_is_no_name",
    "the key {key} at {path} is no XML name, and this mapping writes a key as {what}",
)

XML_NESTED_ARRAY = BASE.define(
    "xml_nested_array",
    "the value at {path} is an array of arrays, and a tag repeated is as deep as a repeat goes",
)

XML_VALUE_IS_NOT_TEXT = BASE.define(
    "xml_value_is_not_text",
    "the value at {path} is {described}, and an XML attribute and an element's text hold text",
)

XML_TEXT_AND_CHILDREN = BASE.define(
    "xml_text_and_children",
    "the object at {path} has both {text_key} and child keys, and this mapping keeps an "
    "element's text under {text_key} only where the element has no children",
)

XML_NULL_ATTRIBUTE = BASE.define(
    "xml_null_attribute",
    "the attribute {key} at {path} is null, and an XML attribute holds text",
)

XML_EMPTY_ARRAY = BASE.define(
    "xml_empty_array",
    "the value at {path} is an empty array, and no elements at all is no key at all; "
    "drop the key to convert the object",
)

#: The playground answers with its own codes, so a refusal from a generated dataset is
#: not mistaken for one from the rest of the base family.
PLAYGROUND = Catalogue("playground")

UNKNOWN_PROVIDER = PLAYGROUND.define(
    "unknown_provider",
    "{provider!r} is not a provider the installed Faker offers for locale {locale!r}; "
    "run 'uv run faker -l {locale}' to print every name it does offer, with a sample of each",
)

UNKNOWN_LOCALE = PLAYGROUND.define(
    "unknown_locale",
    "{locale!r} is not a locale the installed Faker ships, such as en_US, no_NO or fr_FR",
)

PROVIDER_REFUSED = PLAYGROUND.define(
    "provider_refused",
    "the provider {provider!r} refused the arguments it was given: {detail}",
)

FAILED_ON_PURPOSE = PLAYGROUND.define(
    "failed_on_purpose",
    "the playground failed attempt {attempt} on purpose, because fail_until is {fail_until}; "
    "attempt {next_attempt} will succeed",
)
