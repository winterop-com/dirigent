# dirigent-common

Value types and shared schemas every other dirigent package may depend on, and which depend on
nothing of dirigent's in turn.

A `Duration` a document writes as `30s`, a `Size` it writes as `16KB`, the name rules an entity
obeys, and the small schemas more than one package has to agree on. It holds nothing about
blocks, the wire, or the engine: those are `dirigent-plugin`, `dirigent-client` and
`dirigent-core`, all of which may depend on this and none of which it knows about.

See [the architecture page](../../docs/architecture.md) for what belongs here and what does not.
