"""Every refusal the storage family makes, catalogued under the ``storage`` prefix."""

from dirigent_common import Catalogue

STORAGE = Catalogue("storage")

NOTHING_THERE = STORAGE.define("nothing_there", "there is nothing at {source}")

NOTHING_IN_SCRATCH = STORAGE.define(
    "nothing_in_scratch",
    "there is nothing at {source}, which is under this run's own scratch prefix: either no "
    "step wrote it, or the artifact root was not restored beside the database that names it; "
    "restore the artifact root, or run the pipeline again from its inputs",
)

TOO_LARGE = STORAGE.define(
    "too_large",
    "{source} is larger than max_size ({maximum} bytes); raise max_size, "
    "or move the bytes with storage.copy instead of carrying them",
)

UNREADABLE_AS_A_VALUE = STORAGE.define(
    "unreadable_as_a_value",
    "{source} is {content_type}, which this step has no way to read as a value; "
    "set content_type to say what it really is, or move the bytes with storage.copy",
)

NOT_UTF8 = STORAGE.define("not_utf8", "{source} is not the utf-8 its content type promises: {detail}")

NOT_JSON = STORAGE.define("not_json", "{source} is not the json its content type promises: {detail}")


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

WRITE_TAKES_ONE_SOURCE = STORAGE.define("write_takes_one_source", "a write needs either text or value{named}")
