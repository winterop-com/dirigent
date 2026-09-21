# dirigent-blocks

The built-in pack: one install that brings every block family dirigent ships -- base, http,
storage, execute, sql, jq and queues -- and the outbound alert channels beside them.

The three channels here are `webhook`, `slack` and `email`, each with a connection kind of the
same id, so an alert is delivered through the one connection path every credential in this
instance goes through. The fourth channel, `log`, is `dirigent-block-base`'s, because it needs
no credential.

A family is installable on its own: a worker that only runs jq needs
`dirigent-block-jq` and nothing else. This package is what an instance installs to have the lot.
