# Architecture

Dirigent is one `uv` workspace of eighteen packages. This page says what each is for, what may
depend on what, and **where a new thing goes** -- so the answer is a rule rather than a guess.

## The tree

```text
dirigent-common              value types and shared schemas                    -> nothing
dirigent-plugin              the block contract                                -> common
dirigent-client              wire schemas and the SDK                          -> common
dirigent-core                engine, scheduler, triggers, alerting             -> common, plugin, client
dirigent-server              the API and auth                                  -> common, client, core
dirigent-cli                 the commands                                      -> common, client, core, server, blocks
dirigent-examples            the example corpus                                -> common, plugin, client
dirigent-block-base          log, report, validate, value, time, run, convert  -> common, plugin
dirigent-block-http          http.request, http.ready, webhook.post            -> common, plugin
dirigent-block-storage       copy, read, write, exists                         -> common, plugin
dirigent-block-execute       shell, docker, compose, build, checkout           -> common, plugin, block-http
dirigent-block-sql           sql.query, sql.execute                            -> common, plugin
dirigent-block-transform-jq  transform.jq, map.jq, filter.jq                   -> common, plugin
dirigent-block-queues        kafka and rabbitmq                                -> common, plugin
dirigent-block-parquet       convert.arrow, on pyarrow                         -> common, plugin
dirigent-blocks              the umbrella, and the alert channels              -> common, plugin, every family
dirigent-storage-s3          an adapter pack, and the shape of others          -> common, plugin
dirigent-testing             doubles and fixtures for testing a block          -> common, plugin
```

Edges point down and never back up. `packages/dirigent-common/tests/test_dependency_tree.py`
asserts every one of them, from the metadata *and* from what the source actually imports --
because a package can declare the right thing and still reach past it.

## Where a new thing goes

| What you are adding | Where |
| --- | --- |
| A value a document writes and the engine reads -- a duration, a size, an entity code | `common` |
| A schema more than one package must agree on -- a connection's shape, a health report | `common` |
| Something a block author implements or is handed -- `Operator`, `StepContext`, a spec | `plugin` |
| A request or response body, or a method on the SDK | `client` |
| Anything that decides what runs, when, or what happened | `core` |
| An HTTP route, or how a request is authenticated | `server` |
| A command, or how one is rendered | `cli` |
| A block anybody would want | the `dirigent-block-*` family it belongs to |
| A block or backend for one external system | an adapter pack |
| A double or fixture a block author writes tests against | `testing` |

The question that decides it is **who else needs this**. A thing two packages need belongs
below both, and `common` is what makes that possible: without something beneath `plugin`, a
value type the SDK and the engine both need would have to live behind the block contract, and
`dirigent-client` would depend on `Operator` to spell a duration.

## Why the client does not depend on the plugin

An SDK talks to an API. It needs to say `30s` and to address a pipeline by code, and it needs
neither `Operator` nor `Sensor` nor `StepContext`. The value types it does need are in `common`, and
the test asserts the edge to `plugin` stays absent.

## Why an adapter pack does not depend on the standard library

`HttpConnectionConfig` and `build_client` live in `common`. An adapter pack for some external
system needs the same base URL, auth, TLS and timeout fields that `http.request` uses, and a
client that honours them -- and if the only way to get either were to depend on the standard
library, a pack would either take all of it as a dependency or redefine the fields. Four packs
doing the latter is four slightly different HTTP connections, which the UI renders as four
slightly different forms, and four different ideas about whether a timeout applies to the
connect or the read.

`dirigent-block-http` still owns the *kind* that registers it: the configuration and the
client are shared, the registration is that family's. A pack that wants the kind itself
depends on that one family rather than on everything.

## What is not settled

The helpers many plugins will reuse -- the submit-probe-fetch shape, error classification from
a response, remote status mapping, paging -- are named in the roadmap as belonging in `common`
and are not there yet. Build the first adapter pack watching for what the second would
duplicate, and lift that as it appears rather than guessing now.
