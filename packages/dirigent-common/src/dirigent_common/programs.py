"""The media types a config field carrying a program publishes itself under."""

from typing import Final

#: A jq program, as ``transform.jq``, ``map.jq`` and ``filter.jq`` take one.
JQ_MEDIA_TYPE: Final = "application/jq"

#: A string handed to a shell to parse, as ``shell.run`` and ``docker.run`` take one.
SHELL_MEDIA_TYPE: Final = "text/x-shellscript"

#: A Jinja template rendering text, as the run report and ``report.render`` take one.
TEMPLATE_MEDIA_TYPE: Final = "text/x-jinja"

#: A compose file, as ``docker.compose.up`` and ``docker.compose.down`` take one inline. A field
#: publishing this takes no ``${...}`` reference, at apply or at run.
COMPOSE_MEDIA_TYPE: Final = "application/x-compose+yaml"

#: One SQL statement, as ``sql.query`` and ``sql.execute`` take one. A field publishing this
#: takes no ``${...}`` reference, at apply or at run.
SQL_MEDIA_TYPE: Final = "application/sql"
