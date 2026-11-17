# Queues

The queue family lets a run start from a message, and lets a run put one there. It is two
sensors and two operators:

- [`kafka.consume`](blocks.md#kafkaconsume) waits for messages on a Kafka topic.
- [`rabbitmq.consume`](blocks.md#rabbitmqconsume) waits for messages on a RabbitMQ queue.
- [`kafka.produce`](blocks.md#kafkaproduce) publishes records to a Kafka topic.
- [`rabbitmq.publish`](blocks.md#rabbitmqpublish) publishes one message to an exchange.

A queue and an endpoint are the same intent arriving by different transport, and a run should
not care which. An endpoint source is somebody pushing work at this instance; a queue sensor is
this instance reaching out for it. What comes out is the same thing either way -- a payload, in a
step's output, that the rest of the DAG reads with `${steps.<name>.output...}` -- so a pipeline
written against one reads almost exactly like a pipeline written against the other.

Waiting costs a row, not a worker. Each poke is one bounded read that returns in seconds, and
between pokes the attempt is a `waiting` row with a due time, so a pipeline parked on a quiet
topic for a day costs the same as one parked for a minute. That is what makes waiting on a
queue in the DAG reasonable at all.

Two durations bound that, and they are different questions. `poll_timeout` (`5s` by default) is
how long one poke waits on the broker before answering with what it has: it bounds the poke, not
the wait. `poll_every` is how long the attempt parks between pokes, and unset it leaves the
cadence to the step's own `poll`, which both sensors default to `30s`.

The blocks' fields are the generated [block reference](blocks.md); this page is the family: the
two connection kinds, the cursor, when a message is acknowledged, what publishing promises, and
the limits the family keeps.

## These are ordinary blocks

No block here declares `local_execution`, so no instance has to allowlist them. Each reaches
only the brokers its connection names, runs nothing a document supplies, and writes nothing on
the worker. "Can edit pipelines" therefore does not become "can run code on the worker".

## The cursor, and why a poke may see the same message twice

A sensor's poke has one piece of durable state: its **cursor**, an arbitrary JSON map that the
poke returns with a `NotYet` and that the next poke receives as `ctx.cursor`. `kafka.consume`
keeps the offset it has read to in it; `rabbitmq.consume` keeps only a count and the last
delivery tag, because the broker is doing the bookkeeping there.

Three rules govern it, and they are the same three for every sensor:

- **It replaces, it does not merge.** Whatever is worth keeping is written into each `NotYet` in
  full.
- **It is stored by the transaction that parks the attempt.** So advancing it is at-least-once:
  a worker that dies between reading the broker and committing that park leaves the older cursor
  behind, and the next poke reads the same ground again. A poke must tolerate that, and these
  two do.
- **It lives only as long as the waiting attempt.** A poke that succeeds ends the step, and
  only a [`sensor` source](concepts.md#source-and-reply) carries the cursor past it. What a downstream step needs
  is in the output -- `kafka.consume` puts the offsets it ended at there for exactly that reason.

At-least-once is not a shortcut here; it is the only thing achievable. Exactly-once would need
the broker's state and this instance's database to move in one transaction, and nothing can
give that across a boundary we do not own. So the contract says at-least-once, and a pipeline
that must not act twice on one message makes its own step idempotent.

## A batch is settled with the broker only once it is stored

A poke that succeeds does not acknowledge its batch. It hands the engine the batch and leaves
the broker owed an answer: under `ack: on_success` a `rabbitmq.consume` batch stays
unacknowledged on the channel it was received on, and a `kafka.consume` with a `group_id`
leaves the group's offsets where they were. The engine settles the batch -- acks it, or commits
the offsets -- only after the transaction that stores the step's output has committed, or, under
a `sensor` source, after the transaction that starts the run.

Anything that keeps the batch from being stored hands it back instead: an output too large for
the run's storage quota or nested too deep to store, a lost lease, a run cancelled under the
poke, a failed commit, or a worker that dies before it settles. The RabbitMQ batch is nacked
back onto the queue (or requeued by the broker when the connection drops), and the Kafka group
is not moved, so the next poke, the step's retry, or a manual retry reads the same messages
again. A retry, automatic or manual, starts from the cursor the failed attempt stood at, so
a `kafka.consume` without a group reads the same offsets rather than seeking past them.

**A batch may therefore be delivered more than once, and never fewer.** The output is stored
before the broker is told, so an ack or a commit that fails after the store, or a worker that
dies between the two, leaves a stored batch that the broker delivers again. A step that must not
act twice on one message makes itself idempotent, by key or by offset.

## The `kafka` connection kind

A step names a connection and never a broker address, whichever direction it reads or writes in.

| Field | For |
| --- | --- |
| `bootstrap_servers` | The brokers a client bootstraps from, each `host:port`. |
| `security` | `plaintext` (the default), `ssl`, `sasl_ssl`, or `sasl_plaintext`. |
| `sasl_mechanism` | `PLAIN`, `SCRAM-SHA-256` or `SCRAM-SHA-512`, for a `sasl_` setting. |
| `username`, `password` | The SASL credential. The password is sealed. |
| `ca_certificate` | The PEM a private CA's brokers are checked against. |

A credential that does not fit the security setting is refused when the connection is written,
in both directions: `sasl_ssl` with no password, and `plaintext` with one, are both mistakes
that would otherwise only show up as a puzzling failure at run time.

`ca_certificate` is a **plain** field, not a sealed one, and deliberately. A CA certificate is
the public half of a trust anchor -- published by whoever issued it, and what authenticates the
*broker to us* rather than us to the broker. Sealing it would encrypt it at rest and redact it
from every API response, which would stop an operator reading back which CA their own
connection trusts while protecting nothing that is not already public.

```bash
dg connection create kafka orders \
  --set bootstrap_servers='["broker-1:9092","broker-2:9092"]'
dg connection create kafka orders-secure \
  --set bootstrap_servers='["broker:9093"]' --set security=sasl_ssl \
  --set username=reader --set password=...
dg connection check orders
```

A check fetches the cluster's metadata, which is the smallest thing that proves both reach and
credential.

## The `rabbitmq` connection kind

| Field | For |
| --- | --- |
| `url` | `amqp://user@host:5672/vhost`, or the `amqps://` form. |
| `password` | The password for that user. Sealed. |

A URL carrying a password inline is **refused**, in the same words and for the same reason the
[`sql`](sql.md) kind refuses one: a plain field is neither encrypted at rest nor redacted in an
API response, so the secret belongs in `password`, which is both. It is merged into the URL when
a connection is opened and nowhere else.

```bash
dg connection create rabbitmq shop \
  --set url=amqp://dirigent@rabbit:5672/ --set password=...
dg connection check shop
```

A check opens a connection and a channel.

## `kafka.consume`: offsets, and the group

Each poke reads from where the cursor says, takes up to `max_messages`, and succeeds once it
has `min_messages`. Below that it parks where it began, so the next poke reads those messages
again together with whatever has arrived since, and none of them is left out of a batch.

`start` decides where a poke with no cursor begins -- `latest` (the default) at whatever
arrives next, `earliest` at the oldest record the broker still holds. It applies to the first
poke of an attempt only, and under a `sensor` source to its first poke ever; after that the cursor
answers the question. A first poke that read
nothing still writes down the place it began, so a message arriving between two pokes is read
by the second rather than seeked past.

`latest` is a place nothing remembers, so a batch is never taken from it directly. A first
poke under `latest` without a group writes down where the topic ends and parks, and the next
poke reads from that stored place. With a group that has not committed on the topic yet, a poke
that found a batch parks with the offsets the batch began at instead of succeeding. Either way
a retry of a batch that was not stored finds the same messages again. A poke under `earliest`,
or with a group that has committed, starts from a place a retry finds again, and succeeds at
once.

`group_id` is the one real choice.

**Left unset**, the sensor tracks offsets itself and commits nothing to the broker. The offsets
live on the waiting attempt, and under a `sensor` source on the source, so two pipelines reading one topic
each see every message, and a topic can be read without arranging anything on the cluster.

**Set**, the broker keeps the group's offsets too, and they are committed only once the engine
has *stored* a success -- never by a poke that parks, and never for a success that was refused or
lost before it was stored. A batch too small to act on, or one the step could not keep, is
therefore read again rather than committed away, and the cursor still carries the offsets the
batch covers so a replay reads the same ground rather than skipping it. A poke that parks leaves its
place in the cursor as well, so the next poke reads on from there instead of rejoining the
group at the last commit: the group is where an attempt's offsets end up, not how it holds
them while it waits.

`key_format` and `value_format` say how the bytes are read: `json`, `text`, or `base64`. A
value defaults to `json` and a key to `base64`, because a key is often not text at all and
base64 carries any bytes through unharmed. A value that is not the JSON it was promised fails
the step as **rejected**, not retried: reading it again will not make it parse.

The output carries the batch, its `count`, and the `cursor` it ended at -- the next offset to
read per partition, one past the last message taken.

**Poked by a source, a topic is a stream of batches.** A
[`sensor` source](concepts.md#source-and-reply) naming `kafka.consume` pokes it outside any run,
and each batch it takes becomes one run, the next wait reading on from the offsets that batch
ended at, without a gap and without a consumer group. A `group_id` set beside it still commits
what each batch took, once the run that batch became is committed; the source's cursor is what
the next wait reads from. The usual way to
make a topic a pipeline's entrance is the held `kafka` source, which keeps a consumer open and
makes each message its own run:
[`examples/queues/kafka-source-then-transform.yaml`](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues/kafka-source-then-transform.yaml).
The sensor source is for a batch per run. `rabbitmq.consume` cannot be poked by a source; the
held `rabbitmq` source is that queue's entrance.

## `kafka.produce`: what a publish promises

The other direction on the same connection kind. A step names a topic and the records to put on
it, and succeeds once the broker has acknowledged every one.

`records` is the one input: a list held in the document, or a list an earlier step produced.
A publish takes a value like any other step, so an NDJSON export held in storage gets there
the way every value comes in from storage -- `convert.std` re-spells the object as json and
`storage.read` hands the array to the step, whose `max_size` is what bounds it.

An element is read as an **envelope** when it is an object carrying `value` and nothing
besides `key`, `value` and `headers`; every other element is itself the value. Two shapes
rather than one because most topics carry values alone, so a list of documents from an earlier
step publishes unchanged, while a key or a header has to be written somewhere. An object that
means to be a value and would read as an envelope is written `{"value": {...}}`. A string value
is sent as UTF-8 text and anything else as compact JSON, so a topic of JSON documents and a
topic of plain lines are both writable; a null value is a record with no value at all, which is
what a compacted topic reads as a tombstone.

`key` names a field of each record's value to take the message key from, which is what puts
every record sharing a key on one partition. An envelope's own `key` wins. A record that is not
an object, or that lacks the field, fails the step as **rejected** rather than being published
unkeyed: a key silently dropped repartitions a topic, and that is not a thing to discover from
the consumer's side a week later.

`acks` is `all` by default, and that default is load-bearing: it is the only setting an
idempotent producer runs under. Under it the broker recognises a record the client itself
retried and writes it once, so a connection that stumbles inside one step does not
double-publish. `1` waits for the leader alone and `0` waits for nothing, and both give up
de-duplication with it.

**Idempotence covers one producer session and no further.** A retry of the *step* opens a new
session with a new producer id, and every record goes again -- the broker has no way to tell it
is the same batch. This is the same at-least-once bargain the cursor makes, from the other end.
A pipeline that must not publish twice either does not retry the step, or gives its records keys
and lets a compacted topic or the reader settle the duplicates.

The topic must already exist here too, and for the same reason: a name the cluster's metadata
does not carry is **rejected** before a record is sent, on a cluster that would have auto-created
it as much as on one that would not. `timeout` (`30s` by default) bounds the whole publish, from
the first send to the last acknowledgement; how the records are batched inside it is the client's
own business.

The output carries `produced`, the `topic`, the last `offsets` written per partition,
`duration_ms`, and `sent_bytes` -- the bytes of keys and values handed to the client.

## `rabbitmq.consume`: when a message is acknowledged

RabbitMQ, unlike Kafka, keeps its own place: a message is held unacknowledged until it is acked
or nacked. So the sensor's decision is not *where to read* but *when to acknowledge*, and `ack`
is that decision.

`ack: on_success` is the default, and is the safe one. A batch is acked only once every body in
it has been read and the engine has stored the success carrying it, on the channel it was
received on. A poke that parks -- because fewer than `min_messages` were there -- nacks
everything it took back onto the queue with `requeue`, and so does a poke that finds a body it
cannot read, so one malformed message does not take the sound ones beside it off the queue. A
success the engine refuses or loses before storing it is nacked back the same way. No message
is acked without its batch stored, and another consumer may take a message handed back. The
cost is that a message may be delivered more than once: an ack that fails after the store
leaves a stored batch on the queue, and it arrives again. That is the same at-least-once
bargain the cursor makes.

`ack: always` acknowledges every message the moment it is taken, before any of them is read,
park or no park. It suits a queue nothing else reads and a step that would rather drop a partial
batch than see it twice. It is a real choice with a real cost: a batch that parks is gone, and
so is a batch holding a body the step cannot read.

The queue must already exist. Neither block declares one -- a queue a pipeline invented is a
typo that reads as a working pipeline, so a name nobody created is **rejected** with the name in
the message rather than waiting forever on nothing.

## `rabbitmq.publish`: a message nothing takes is a failure

A publish waits for the broker's confirm, so `published: 1` means the broker took the message.
On the default exchange a routing key is a queue name, and a broker drops a message whose key
names no queue -- or, on a named exchange, one nothing is bound to take -- and still confirms it.
So the publish is `mandatory` by default: the broker hands such a message back, and the step
fails as **rejected** with `queues.rabbit.nothing_bound`, naming the exchange and the key.
A typo in a queue name is then a failed run, not a run that succeeded and delivered nothing.

`require_route: false` turns that off, for a fanout of events nobody may be subscribed to yet:
the message is published without `mandatory`, a broker with nowhere to put it drops it, and the
step succeeds.
A broker that answers the publish with a nack -- a queue at its length limit that rejects new
messages, say -- fails the step as **transient** with `queues.rabbit.publish_nacked`.

`kafka.produce` has no such gap: the topic is checked against the cluster's metadata before a
record is sent, and under the default `acks: all` a record counts once every in-sync replica
holds it. `acks: 0` is the one setting that waits for nothing, and a step that chooses it gives
up knowing whether anything arrived.

## A topic or a queue as a pipeline's source

A `kafka` or `rabbitmq` source makes each message its own run, where `kafka.consume` and
`rabbitmq.consume` hand a batch to a run that is waiting. One worker holds the source's consumer
under a lease and acknowledges a message only once its run is committed: a `kafka` source
commits its `group_id`'s offsets, which is where a worker taking the source over carries on, and
a `rabbitmq` source acks each delivery, so one never acked is handed back when the consumer
closes. A message may therefore arrive twice and is never lost. A body that does not decode the
way `value_format` says fails the source, and is handed over again on the next attempt; read
such a topic or queue as `text` or `base64` to get past it. `max_in_flight` holds the consumer
back while that many of its runs are unsettled. See
[kafka-source-then-transform.yaml](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues/kafka-source-then-transform.yaml).

## What a failure means

| What happened | Class | What the engine does |
| --- | --- | --- |
| The broker cannot be reached | transient | Retried under the step's policy. |
| Authentication was refused | rejected | Not retried. |
| The topic or queue does not exist | rejected | Not retried; the name is in the message. |
| A value is not the JSON it was promised | rejected | Not retried. |
| A record has no field to take its key from | rejected | Not retried. |
| A publish ran past its `timeout` | transient | Retried, and every record goes again. |
| A RabbitMQ message no queue takes, under `require_route` | rejected | Not retried; the exchange and the key are in the message. |
| The broker nacked a RabbitMQ publish | transient | Retried under the step's policy. |
| Nothing has arrived yet | not a failure | The attempt parks and is poked again. |

## The limits

- **A publish to RabbitMQ is one message.** `rabbitmq.publish` sends the one `message` it is
  given, where `kafka.produce` sends a list of `records`; a run with several messages to send
  fans the step out over them.
- **One topic, one queue.** A step names one of each. A pipeline reading three uses three steps.
- **No consumer-group rebalancing across pokes.** Each poke opens a connection, reads, and
  closes it, which is what makes a poke cheap and any worker able to run it. A long-lived
  consumer holding a partition assignment would be a different shape of thing entirely.
- **No transactions.** No block here reads a transactional producer's uncommitted messages
  differently from any other, and none participates in one -- `kafka.produce` included, whose
  idempotence is the broker's de-duplication and not a transaction.

## Running these against real brokers

`infra/compose.queues.yaml` is a single-node Redpanda (which speaks the Kafka protocol) and a
RabbitMQ, both unprotected, for a developer's machine or a CI runner:

```bash
make queues-up      # docker compose -f infra/compose.queues.yaml up -d --wait
make test-queues    # the `queues` pytest marker: every block here against both brokers
make queues-down
```

The [`examples/queues/`](https://github.com/winterop-com/dirigent/tree/main/packages/dirigent-examples/src/dirigent_examples/shelves/queues)
shelf is written against that stack, and each document's header says what to put on the topic
or the queue first.

## On the compose stack

`infra/compose.brokers.yaml` puts the same two brokers on the [compose
stack's](operations.md) own network, where the server and the worker resolve them by service
name. It is an overlay, layered on the base stack with another `-f`:

```bash
make docker-run-queues   # docker compose ... -f infra/compose.brokers.yaml up
```

Nothing but the RabbitMQ management UI is published to the host, on
`127.0.0.1:15672`. The two connections name the services:

```bash
dg connection create kafka orders-topic --set bootstrap_servers='["redpanda:9092"]'
dg connection create rabbitmq shop-queue \
  --set url=amqp://dirigent@rabbitmq:5672/ --set password=dirigent
```

`infra/compose.queues.yaml` and this overlay are not the same file and are not
interchangeable: the standalone one publishes both brokers on the host, which is what the
pytest lane and a `dg` outside a container need; this one advertises in-network addresses,
which is what a container needs.
