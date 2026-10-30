# dirigent-mcp

An MCP server that lets an agent operate a dirigent instance through its API: write and apply
pipeline documents, start runs and read them, and pause or resume sources and schedules. Its
tools are calls the API already answers, so the agent may do what its token may do, and none of
them deletes anything.

```bash
claude mcp add dirigent -e DG_URL=https://dirigent.example.org -e DG_TOKEN=... -- uvx dirigent-mcp
```

Any MCP client starts it the same way: `uvx dirigent-mcp` over stdio, with `DG_URL` and
`DG_TOKEN` in its environment. See [Working with a coding agent](https://winterop-com.github.io/dirigent/agents/)
for the tools it offers.
