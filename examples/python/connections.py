"""Create a connection, ask whether it answers, and remove it again.

    export DG_URL=http://127.0.0.1:3333 DG_TOKEN=...
    uv run python examples/python/connections.py

A connection's kind declares which of its fields are secret by marking them SecretStr. That
one declaration is what makes the API redact them and the engine encrypt them, so a read
never returns a credential: this script writes one and gets the redaction marker back.
"""

import asyncio
import os

from dirigent_client import Conflict, Dirigent

NAME = "example-http"


async def main() -> int:
    """Create a connection, check it, read it back redacted, and delete it."""
    async with Dirigent(url=os.environ["DG_URL"], token=os.environ["DG_TOKEN"]) as dg:
        catalog = await dg.blocks.catalog()
        print(f"connection kinds: {', '.join(entry.id for entry in catalog.connection_kinds) or 'none'}")

        created_here = False
        try:
            created = await dg.connections.create(
                NAME,
                kind="http",
                description="An example credential; nothing behind it is real.",
                config={
                    # A reserved name that never resolves, so the check below fails without
                    # this example ever reaching a real service.
                    "base_url": "https://service.invalid",
                    "bearer_token": "not-a-real-token",
                },
            )
            created_here = True
        except Conflict:
            print(f"{NAME} already exists; reading it instead")
            created = await dg.connections.get(NAME)

        print(f"created: {created.code} ({created.kind})")
        print(f"  secret fields: {', '.join(created.secret_fields) or 'none'}")
        for field, value in created.config.items():
            print(f"  {field}: {value}")

        report = await dg.connections.check(NAME)
        print(f"check: {'healthy' if report.healthy else 'unhealthy'} -- {report.detail or ''}")

        # Only remove what this run made; a connection that was already here is left in place.
        if created_here:
            await dg.connections.delete(NAME)
            print(f"deleted: {NAME}")
        else:
            print(f"leaving pre-existing {NAME} in place")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
