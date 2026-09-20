"""The jq runner: the process a jq program is compiled and evaluated in, spoken to over its pipes.

jq is a C extension that holds the GIL for as long as a program runs, so a program evaluated
in the worker's own process holds its event loop too: the step's timeout never fires, the
lease heartbeat never runs, and the sweeper eventually hands the attempt to another worker
while this one is still computing. There is no way to interrupt a jq program and no way to
cancel a thread, so a program runs here, where killing the process ends it.

The runner protocol is what the pipes carry, one JSON object per line each way: ``compile``
holds a program under the id it is named by, ``run`` evaluates the program held under an id
over one value, and ``forget`` releases one. The pipe closing is how the parent says it is
done, and compiling a program and reading its outputs are the only jq in here.

This module is run by path, never imported, so it costs the standard library and jq and
nothing else to start. Importing it as part of its package would load the whole transform
family in order to evaluate ``.name``.
"""

import json
import sys
from typing import Any

import jq

#: Typed ``Any`` because the jq binding is a C extension that ships no type information.
libjq: Any = jq


def main() -> None:
    """Answer one request at a time until the pipe closes, holding the programs compiled so far."""
    out = sys.stdout.buffer
    programs: dict[str, Any] = {}
    for line in sys.stdin.buffer:
        reply = answer(programs, json.loads(line))
        out.write(json.dumps(reply).encode() + b"\n")
        out.flush()


def answer(programs: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Compile a program under its id, run the one an id names, or release it."""
    kind = request["kind"]
    if kind == "compile":
        try:
            compiled = libjq.compile(request["program"])
        except ValueError as error:
            return {"error": str(error).strip()}
        # Held only once it has compiled, so a refused program is not one an id names.
        programs[request["id"]] = compiled
        return {"ok": True}
    if kind == "forget":
        programs.pop(request["id"], None)
        return {"ok": True}
    if kind == "run":
        compiled = programs.get(request["id"])
        if compiled is None:
            return {"error": f"no program is compiled under {request['id']}"}
        try:
            return {"outputs": compiled.input_value(request["value"]).all()}
        except ValueError as error:
            return {"error": str(error).strip()}
    return {"error": f"{kind} is not a request kind: compile, run, or forget"}


if __name__ == "__main__":
    main()
