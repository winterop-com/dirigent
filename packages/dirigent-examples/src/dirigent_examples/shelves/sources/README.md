# Sources

A pipeline that starts where an input arrives. A step is one of three things: a block, a
source, where an input enters and whose output is that input, or a reply, which the server
renders from the run's outputs to answer whoever sent it.

| Document | What it shows |
| --- | --- |
| [`echo-by-hand.yaml`](echo-by-hand.yaml) | The smallest pipeline with a source: the input answered straight back. |
| [`greet-by-hand.yaml`](greet-by-hand.yaml) | A path parameter, a jq step between the source and the reply, and a status of its own. |
| [`signup-form.yaml`](signup-form.yaml) | A urlencoded form taken, and its caller answered 202 the moment the run exists. |
| [`landing-files.yaml`](landing-files.yaml) | A storage source a worker polls: each CSV landing under a prefix becomes one run, two in flight at most. |

Each runs by hand: `dg run --local` takes the source's `sample`, and `--input` gives one
instead (`--source` names which source when a pipeline has several). Applied to a server, an
endpoint is called at its route under `/endpoints` with the token the apply printed, and
`dg source call` does that for you. A caller of a pipeline with a reply is held until the reply
answers; one with none is answered 202.
