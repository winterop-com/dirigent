# dirigent-block-queues

The queue block family: `kafka.produce` and `rabbitmq.publish` send one message, and the
`kafka.consume` and `rabbitmq.consume` sensors wait for messages to arrive.

Each broker registers a connection kind of its own -- `kafka` and `rabbitmq` -- holding the
addresses, the credential and the TLS settings, so a step names a connection and a topic or a
queue. A consuming sensor parks the attempt until enough has arrived, and the place it has
read to is the sensor's cursor: a poke that parks commits nothing, so a batch too small to act
on is read again rather than lost.
