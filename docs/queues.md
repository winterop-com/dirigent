# Queues

The queue family lets a run start from a message, and lets a run put one there. It is two
sensors and two operators:

- [`kafka.consume`](blocks.md#kafkaconsume) waits for messages on a Kafka topic.
- [`rabbitmq.consume`](blocks.md#rabbitmqconsume) waits for messages on a RabbitMQ queue.
- [`kafka.produce`](blocks.md#kafkaproduce) publishes records to a Kafka topic.
- [`rabbitmq.publish`](blocks.md#rabbitmqpublish) publishes one message to an exchange.

A queue and a webhook are the same intent arriving by different transport, and a run should not
care which. A webhook trigger is somebody pushing work at this instance; a queue sensor is this
instance reaching out for it. What comes out is the same thing either way -- a payload, in a
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
what these blocks do not do.

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
  nothing carries the cursor past it. What a downstream step needs is in the output --
  `kafka.consume` puts the offsets it ended at there for exactly that reason.

At-least-once is not a shortcut here; it is the only thing achievable. Exactly-once would need
the broker's state and this instance's database to move in one transaction, and nothing can
give that across a boundary we do not own. So the contract says at-least-once, and a pipeline
that must not act twice on one message makes its own step idempotent.

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
has `min_messages`. Below that it parks, keeping the offsets it read so the next poke carries
on rather than starting over.

`start` decides where a poke with no cursor begins -- `latest` (the default) at whatever
arrives next, `earliest` at the oldest record the broker still holds. It applies to the first
poke of an attempt only; after that the cursor answers the question. A first poke that read
nothing still writes down the place it began, so a message arriving between two pokes is read
by the second rather than seeked past.

`group_id` is the one real choice.

**Left unset**, the sensor tracks offsets itself and commits nothing to the broker. The offsets
live on the waiting attempt and nowhere else, so two pipelines reading one topic each see every
message, and a topic can be read without arranging anything on the cluster.

**Set**, the broker keeps the group's offsets too, and the commit happens in the poke that
*succeeds* -- never in one that parks. A batch too small to act on is therefore read again by
the next poke rather than committed away, and the cursor still carries the offsets the batch
covers so a replay reads the same ground rather than skipping it. A poke that parks leaves its
place in the cursor as well, so the next poke reads on from there instead of rejoining the
group at the last commit: the group is where an attempt's offsets end up, not how it holds
them while it waits.

`key_format` and `value_format` say how the bytes are read: `json`, `text`, or `base64`. A
value defaults to `json` and a key to `base64`, because a key is often not text at all and
base64 carries any bytes through unharmed. A value that is not the JSON it was promised fails
the step as **rejected**, not retried: reading it again will not make it parse.

The output carries the batch, its `count`, and the `cursor` it ended at -- the next offset to
read per partition, one past the last message taken.

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
step publishes unchanged, while a key or a header has to be written somewhere. An object that means to be a value and would read as an envelope is written
`{"value": {...}}`. A string value is sent as UTF-8 text and anything else as compact JSON, so a
topic of JSON documents and a topic of plain lines are both writable; a null value is a record
with no value at all, which is what a compacted topic reads as a tombstone.

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

`ack: on_success` is the default, and is the safe one. Messages are acked only in the poke that
succeeds. A poke that parks -- because fewer than `min_messages` were there -- nacks everything
it took back onto the queue with `requeue`, so nothing is lost and another consumer may take it
instead. The cost is that a message may be delivered more than once, which is the same
at-least-once bargain the cursor makes.

`ack: always` acknowledges every message the moment it is taken, park or no park. It suits a
queue nothing else reads and a step that would rather drop a partial batch than see it twice.
It is a real choice with a real cost: a batch that parks is gone.

The queue must already exist. Neither block declares one -- a queue a pipeline invented is a
typo that reads as a working pipeline, so a name nobody created is **rejected** with the name in
the message rather than waiting forever on nothing.

## What a failure means

| What happened | Class | What the engine does |
| --- | --- | --- |
| The broker cannot be reached | transient | Retried under the step's policy. |
| Authentication was refused | rejected | Not retried. |
| The topic or queue does not exist | rejected | Not retried; the name is in the message. |
| A value is not the JSON it was promised | rejected | Not retried. |
| A record has no field to take its key from | rejected | Not retried. |
| A publish ran past its `timeout` | transient | Retried, and every record goes again. |
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
