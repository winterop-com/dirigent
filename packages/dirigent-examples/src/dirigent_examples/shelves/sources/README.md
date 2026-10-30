# Sources

A pipeline that starts where an input arrives. A step is one of three things: a block, a
source, where an input enters and whose output is that input, or a reply, which the server
renders from the run's outputs to answer whoever sent it.

| Document | What it shows |
| --- | --- |
| [`echo-by-hand.yaml`](echo-by-hand.yaml) | The smallest pipeline with a source: the input answered straight back. |
| [`greet-by-hand.yaml`](greet-by-hand.yaml) | A path parameter, a jq step between the source and the reply, and a status of its own. |
| [`signed-nested-payload.yaml`](signed-nested-payload.yaml) | A body signed with HMAC-SHA256 instead of a token, and a jq step that takes only the fields it names from a nested payload. |
| [`signup-form.yaml`](signup-form.yaml) | A urlencoded form taken, and its caller answered 202 the moment the run exists. |
| [`landing-files.yaml`](landing-files.yaml) | A storage source a worker polls: each CSV landing under a prefix becomes one run, two in flight at most. |
| [`sensor-arrivals.yaml`](sensor-arrivals.yaml) | A sensor source: `playground.arrive` poked outside any run, each batch it arrives with one run, the offsets carrying on from batch to batch. |
| [`sensor-fan-out-per-message.yaml`](sensor-fan-out-per-message.yaml) | A sensor source's batch handled one message at a time: a `for_each` over the batch's messages, its items written with the run. |

Each runs by hand: `dg run --local` takes the source's `sample`, and `--input` gives one
instead (`--source` names which source when a pipeline has several). Applied to a server, an
endpoint is called at its route under `/endpoints` with the token the apply printed, or
signed with the secret it printed for an `auth: {kind: hmac}` source, and `dg source call`
does either for you. A caller of a pipeline with a reply is held until the reply
answers; one with none is answered 202.
