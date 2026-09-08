"""The media types a config field carrying a program publishes itself under."""

from typing import Final

#: A jq program, as ``transform.jq``, ``map.jq`` and ``filter.jq`` take one.
JQ_MEDIA_TYPE: Final = "application/jq"

#: A string handed to a shell to parse, as ``shell.run`` and ``docker.run`` take one.
SHELL_MEDIA_TYPE: Final = "text/x-shellscript"
