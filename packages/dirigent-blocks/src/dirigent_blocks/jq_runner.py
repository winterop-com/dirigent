"""The process a jq program is evaluated in, started by ``transform_jq`` and spoken to over its pipes.

jq is a C extension that holds the GIL for as long as a program runs, so a program evaluated
in the worker's own process holds its event loop too: the step's timeout never fires, the
lease heartbeat never runs, and the sweeper eventually hands the attempt to another worker
while this one is still computing. There is no way to interrupt a jq program and no way to
cancel a thread, so a program runs here, where killing the process ends it.

One request per line in, one reply per line back: ``{"program": ..., "value": ...}`` is
answered with ``{"outputs": [...]}``, or with ``{"error": "..."}`` carrying jq's own message
about a program that could not be compiled or met data it cannot work on. The pipe closing is
how the parent says it is done.

This module is run by path, never imported, so it costs the standard library and jq and
nothing else to start. Importing it as part of its package would load every block dirigent
ships in order to evaluate ``.name``.
"""

import json
import sys
from typing import Any

import jq

#: Typed ``Any`` because the jq binding is a C extension that ships no type information.
libjq: Any = jq


def main() -> None:
    """Answer one request at a time until the pipe closes.

    The last program compiled is kept because a step sends the same one once per element, and
    only the last, because the process outlives the step and a run's programs would otherwise
    pile up in it.
    """
    out = sys.stdout.buffer
    source: str | None = None
    compiled: Any = None
    for line in sys.stdin.buffer:
        request = json.loads(line)
        try:
            if request["program"] != source:
                # Named only once it has compiled, so a refused program is not cached as one.
                compiled = libjq.compile(request["program"])
                source = request["program"]
            reply = {"outputs": compiled.input_value(request["value"]).all()}
        except ValueError as error:
            reply = {"error": str(error).strip()}
        out.write(json.dumps(reply).encode() + b"\n")
        out.flush()


if __name__ == "__main__":
    main()
