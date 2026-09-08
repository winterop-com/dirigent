"""Provoke each typed refusal, and show the shape of handling it.

    export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...
    uv run python examples/python/error_handling.py

Every exception carries the status, the URL, and the parsed problem body, so a caller can
print one sentence, branch on a status, or read the field list a validation failure names.
"""

import asyncio
import os

from dirigent_client import (
    Dirigent,
    DirigentError,
    NotDirigent,
    NotFound,
    Unauthorized,
    ValidationFailed,
)

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: error-handling-demo
params:
  type: object
  required: [day]
  properties:
    day:
      type: string
steps:
  gate:
    block: time.window
    config:
      after: "00:00"
      before: "23:59"
"""


async def main() -> int:
    """Ask for four things that cannot work, and handle each refusal on its own terms."""
    url = os.environ["DG_URL"]
    token = os.environ["DG_TOKEN"]

    async with Dirigent(url=url, token=token) as dg:
        try:
            await dg.pipelines.get("no-pipeline-has-this-code")
        except NotFound as refusal:
            print(f"not found: {refusal.message}  [{refusal.status} from {refusal.url}]")

        await dg.pipelines.apply(DOCUMENT)
        try:
            await dg.pipelines.run("error-handling-demo", params={"day": 7})
        except ValidationFailed as refusal:
            print(f"refused: {refusal.message}")
            for problem in refusal.problems:
                print(f"  - {problem}")
        finally:
            await dg.pipelines.delete("error-handling-demo")

    async with Dirigent(url=url, token="not-a-real-token") as dg:
        try:
            await dg.auth.whoami()
        except Unauthorized as refusal:
            print(f"unauthorized: {refusal.message}")

    # A URL pointing at the wrong thing has two shapes. Nothing listening is a
    # TransportError; something answering without X-Dirigent-Version -- a docs server, a
    # proxy, another service -- is NotDirigent, and both mean the URL rather than the
    # request is wrong. Every refusal is a DirigentError, so one clause is enough when the
    # distinction does not matter.
    async with Dirigent(url="http://127.0.0.1:1", token=token, retries=0) as dg:
        try:
            await dg.system.info()
        except NotDirigent as refusal:
            print(f"wrong address: {refusal.message}")
        except DirigentError as refusal:
            print(f"unreachable: {refusal.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
