# dirigent-mcp

An MCP server that lets an agent operate a dirigent instance through its API: write and apply
pipeline documents, start runs and read them, and pause or resume sources and schedules. Its
tools are calls the API already answers, so the agent may do what its token's role may do. No
tool is a delete, but `apply_document` retires what a document stops declaring: a source, with
its input journal and its token, and a schedule the document managed. `plan_document` lists them
under `sources.removed` and `triggers.schedules_removed` first. An agent that may apply and run a document runs it with every
connection the instance holds: give a `viewer` token and set `DG_MCP_READ_ONLY=1` when it should
only read.

```bash
claude mcp add dirigent -e DG_URL=https://dirigent.example.org -e DG_TOKEN=... -- uvx dirigent-mcp
```

Any MCP client starts it the same way: `uvx dirigent-mcp` over stdio, with `DG_URL` and
`DG_TOKEN` in its environment. See [Working with a coding agent](https://winterop-com.github.io/dirigent/agents/)
for the tools it offers.
