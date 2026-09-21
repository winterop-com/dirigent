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
