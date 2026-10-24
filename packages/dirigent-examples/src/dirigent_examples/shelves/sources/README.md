# Sources

A pipeline that starts where an input arrives. A step is one of three things: a block, a
source, where an input enters and whose output is that input, or a reply, which the server
renders from the run's outputs to answer whoever sent it.

| Document | What it shows |
| --- | --- |
| [`echo-by-hand.yaml`](echo-by-hand.yaml) | The smallest pipeline with a source: the input answered straight back. |
| [`greet-by-hand.yaml`](greet-by-hand.yaml) | A path parameter, a jq step between the source and the reply, and a status of its own. |

Both are run by hand here: `dg run --local` takes the source's `sample`, and `--input` gives
one instead (`--source` names which source when a pipeline has several). An endpoint does not
take requests over the network yet; a hand run is how a pipeline with a source runs today.
