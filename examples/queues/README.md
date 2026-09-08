# Queue examples

A queue sensor starts a run from a message instead of a clock or a webhook. Each poke reads
what has arrived since the last one and succeeds the moment there is enough, so the batch
becomes ordinary step output and the rest of the DAG never learns where it came from. A publish
goes the other way: a step puts records on a topic and succeeds once the broker has them.
[docs/queues.md](../../docs/queues.md) is the family's home.

Every block here is **ordinary**: each reaches only the brokers its connection names, so no id
has to be allowlisted to run one.

## Bring the brokers up first

No document here can run without a broker. `infra/compose.queues.yaml` is a
single-node Redpanda (which speaks the Kafka protocol) and a RabbitMQ, both unprotected,
for a developer's machine:

```bash
make queues-up      # docker compose -f infra/compose.queues.yaml up -d --wait
```

Then create the topic or the queue, put something on it, and create the connection each
document names. Each document's header spells out its own three commands, and the produce
document needs nothing put on the topic first: it publishes what it reads back.

Every document **names** its connection under `requires.connections` rather than carrying one,
which is the shape to copy: bootstrap servers, an AMQP URL and a sealed password belong to an
environment, not to a pipeline. On an instance they are created once:

```bash
dg connection create kafka orders-topic --set bootstrap_servers='["127.0.0.1:9092"]'
dg connection create rabbitmq shop-queue \
  --set url=amqp://dirigent@127.0.0.1:5672/ --set password=dirigent
```

On the compose stack the brokers are the `infra/compose.brokers.yaml` overlay instead
(`make docker-run-queues`), and the same two connections name `redpanda:9092` and
`amqp://dirigent@rabbitmq:5672/`, which is what a container resolves.

## Pipelines

| File | What it teaches |
| --- | --- |
| [kafka-consume-then-transform.yaml](kafka-consume-then-transform.yaml) | Waiting on a topic: `min_messages` and `max_messages`, why the cursor rather than a consumer group holds the offsets, and the batch read by a downstream transform. |
| [kafka-produce-then-consume.yaml](kafka-produce-then-consume.yaml) | Publishing: the two shapes an element of `records` may take, where a message key comes from, what `acks: all` and an idempotent producer do and do not promise, and why this one consumes from `earliest`. |
| [rabbitmq-consume-ack-on-success.yaml](rabbitmq-consume-ack-on-success.yaml) | When a message is acknowledged: why `ack: on_success` is the default, what a poke that parks does with the messages it took, and what `always` gives up in exchange. |

## The cursor, in one paragraph

A sensor's poke keeps its place in a **cursor**, a JSON map the poke returns with a `NotYet`
and the next poke receives as `ctx.cursor`. `kafka.consume` keeps the offsets it has read to in
it; `rabbitmq.consume` keeps only a count and the last delivery tag, because the broker holds
the state there. It replaces rather than merges, it is stored by the transaction that parks the
attempt -- which makes advancing it at-least-once, so a poke may read the same ground twice --
and it lives only as long as the waiting attempt, because a poke that succeeds ends the step.
Anything a later step needs is in the output, which is why `kafka.consume` reports the offsets
it ended at there.
