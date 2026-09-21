"""Every refusal the sql family makes, catalogued under the ``sql`` prefix."""

from dirigent_common import Catalogue

SQL = Catalogue("sql")

DRIVER_NOT_INSTALLED = SQL.define(
    "driver_not_installed",
    "the {driver} driver this url names is not installed on the worker; add the {package} "
    "package to the image, or use a driver that ships with it ({shipped})",
)

CONNECT_TIMED_OUT = SQL.define("connect_timed_out", "the database did not answer within {timeout}")

READ_ONLY_CONNECTION = SQL.define(
    "read_only_connection",
    "connection {connection} is read_only, and sql.execute writes; "
    "read it with sql.query, or point this step at a connection that may write",
)

TOO_MANY_ROWS = SQL.define(
    "too_many_rows",
    "the query returned more than max_rows ({maximum}) rows; raise max_rows, or narrow the query",
)

NO_JSON_SPELLING = SQL.define("no_json_spelling", "a column of this result has no JSON spelling: {detail}")


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

ENGINE_PACKAGE_MISSING = SQL.define(
    "engine_package_missing",
    "{backend} needs the engine package: uv pip install {package}",
)

NO_ASYNC_DRIVER = SQL.define(
    "no_async_driver",
    "{driver} names no driver, and these blocks speak to a database over an "
    "async one; write the driver in the url, as in "
    "{driver_name}+asyncpg:// or {driver_name}+aiosqlite://",
)

READ_ONLY_UNSUPPORTED = SQL.define(
    "read_only_unsupported",
    "read_only has no meaning on {backend}: only {supported} can be told to "
    "refuse writes for the length of a session, and a connection that cannot be "
    "is not marked as one that is",
)

INLINE_PASSWORD = SQL.define(
    "inline_password",
    "this url carries a password inline, where it would sit unencrypted in a plain "
    "field; take it out of the url and set the sealed password field instead",
)

EMPTY_STATEMENT = SQL.define("empty_statement", "statement {index} is empty")

NOT_A_DATABASE_URL = SQL.define("not_a_database_url", "{url} is not a database url: {detail}")

MORE_THAN_ONE_STATEMENT = SQL.define(
    "more_than_one_statement",
    "this is more than one statement: a ';' ends the first and there is more after it. "
    "sql.query runs one statement, and sql.execute takes a list, one statement per entry",
)
