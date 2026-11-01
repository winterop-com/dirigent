# dirigent-mcp

An MCP server that lets an agent operate a dirigent instance through its API: write and apply
pipeline documents, start runs and read them, and pause or resume sources and schedules. Its
tools are calls the API already answers, so the agent may do what its token's role may do. No
tool is a delete, but `apply_document` retires what a document stops declaring: a source, with
its input journal and its token, and a schedule the document managed. `plan_document` lists them
under `sources.removed` and `triggers.schedules_removed` first. An agent that may apply and run a
document runs it with every connection the instance holds: give it a `viewer` token when it should
only read.

Every dirigent server serves these tools over Streamable HTTP at `/mcp`, each request acting as the
bearer token it presents, so nothing needs installing beside the agent:

```bash
claude mcp add --transport http dirigent https://dirigent.example.org/mcp \
  --header "Authorization: Bearer $DG_TOKEN"
```

Over stdio, the client starts this package as a command, with the instance and the token in its
environment; `DG_MCP_READ_ONLY=1` offers only the tools that read:

```bash
claude mcp add dirigent -e DG_URL=https://dirigent.example.org -e DG_TOKEN=... -- uvx dirigent-mcp
```

`--transport http` serves the same tools at `/mcp` in front of a remote instance, on loopback by
default, each caller presenting its own token, which is forwarded to the instance:

```bash
DG_URL=https://dirigent.example.org uvx dirigent-mcp --transport http --port 3334
claude mcp add --transport http dirigent http://127.0.0.1:3334/mcp \
  --header "Authorization: Bearer $DG_TOKEN"
```

An address other machines can reach needs `--allow-remote`.

See [Working with a coding agent](https://winterop-com.github.io/dirigent/agents/) for the tools
it offers.
