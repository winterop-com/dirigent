"""A runner the protocol tests start by path, whose whole language is the five words in PROGRAMS.

It speaks the runner protocol and nothing else: the standard library, one request per line,
one reply per line, exactly as a runner for a language dirigent does not ship would.
"""

import json
import sys
import time
from typing import Any

#: Every program this runner compiles; outputs() is what each one makes of a value.
PROGRAMS = ("echo", "twice", "nothing", "double", "forever")

#: How long "forever" spends on one value: long enough that only a kill ends the step.
FOREVER = 3600.0


def outputs(program: str, value: Any) -> list[Any]:
    """The stream one program produces for one value."""
    if program == "echo":
        return [value]
    if program == "twice":
        return [value, value]
    if program == "nothing":
        return []
    if program == "double":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"cannot double {json.dumps(value)}")
        return [value * 2]
    time.sleep(FOREVER)
    return [value]


def answer(programs: dict[str, str], request: dict[str, Any]) -> dict[str, Any]:
    """Compile a program under its id, run the one an id names, or release it."""
    kind = request["kind"]
    if kind == "compile":
        program = request["program"]
        if program not in PROGRAMS:
            return {"error": f"{program} is not a program: write one of {', '.join(PROGRAMS)}"}
        programs[request["id"]] = program
        return {"ok": True}
    if kind == "forget":
        programs.pop(request["id"], None)
        return {"ok": True}
    if kind == "run":
        program = programs.get(request["id"])
        if program is None:
            return {"error": f"no program is compiled under {request['id']}"}
        try:
            return {"outputs": outputs(program, request["value"])}
        except ValueError as error:
            return {"error": str(error)}
    return {"error": f"{kind} is not a request kind: compile, run, or forget"}


def main() -> None:
    """Answer one request at a time until the pipe closes, holding the programs compiled so far."""
    out = sys.stdout.buffer
    programs: dict[str, str] = {}
    for line in sys.stdin.buffer:
        reply = answer(programs, json.loads(line))
        out.write(json.dumps(reply).encode() + b"\n")
        out.flush()


if __name__ == "__main__":
    main()
