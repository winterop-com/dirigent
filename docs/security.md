# Security

An orchestrator is a credential vault with an execute button. It holds the keys to every
system its pipelines touch, and it runs whatever the pipelines say to run. That framing
decides most of what follows: dirigent does not ship open, secrets are not stored in readable
columns, and "can edit a pipeline" is deliberately not the same permission as "can run code
on a worker".

This page is what the code actually does today. Where something is not built, it says so
rather than leaving the gap for you to find.

## Threat model

**Who dirigent trusts.**

- The **operating environment**. Whoever can read the server's or a worker's process
  environment can read `DIRIGENT_SECRET_KEY`, and therefore every connection secret the
  instance holds. Root on a dirigent host is game over, and no in-product control changes
  that.
- The **database**. There is no application-level integrity check on what comes back out of
  PostgreSQL. Write access to the database is equivalent to full control of the instance:
  connection secrets are encrypted, but pipeline definitions, run state, and password hashes
  are not protected against a writer.
- **Every operator**, at least as far as pipelines and runs go. Any operator account can
  define a pipeline, run it, read every run's logs, and see every connection by code, on any
  pipeline. See [authorization](#what-authorizes) for exactly where that stops.
- **Installed plugin packages**, completely. A plugin is Python running in the worker process
  with the same privileges as the engine. Installing one is a decision about the host.

**What it is designed to resist.**

- An unauthenticated caller reaching anything but the health probes, the login route, the
  OpenAPI document, and the webhook intake.
- Enumeration of accounts through the login endpoint -- a missing account and a wrong password
  return the same answer and take the same time, because a short-circuit on a missing user
  answered "does this account exist?" to anyone with a stopwatch.
- Enumeration of webhook tokens -- an unknown token, a revoked one, and a disabled webhook all
  answer identically, under load as well as at rest.
- Credential exfiltration through a stored pipeline: a document cannot inherit the instance's
  own environment variables, cannot address a `file://` URI outside the artifact root, and
  cannot execute code on a worker at all unless the instance allowlisted the block.
- Brute force against the login endpoint, both as a flood from one address and as credential
  stuffing spread across many.
- A cross-site write spending the session cookie, including a cross-site login: the browser
  says where the request came from, and one that came from elsewhere is refused.
- Secrets appearing where they are read casually: API responses, pipeline documents, exports,
  process logs, and OpenTelemetry span names are all redacted.

**What it explicitly does not defend against.**

- A malicious or compromised plugin package.
- An authenticated operator with a legitimate account who abuses it. There is no per-pipeline
  permission model, so any operator can start any pipeline and read any run.
- Read access to the database file or the backup of it. Connection secrets stay sealed, but
  everything else is in the clear.
- Multi-tenant separation of any kind. One dirigent instance is one team's instance.
- Denial of service from an authenticated principal. Rate limiting exists on the two
  unauthenticated write paths (login and webhook intake) and nowhere else.
- Anything a pipeline's own outbound traffic can reach. `http.request` will call the URL it is
  given; there is no egress allowlist.

## What authenticates

Sessions and API tokens are the same thing, and the code says so: both are rows in one
`api_tokens` table, distinguished only by a `kind` column. Both are an opaque secret that
authenticates as a user until it expires or is revoked. Keeping them apart would mean two
lookup paths, two revocation stories, and two chances to get the comparison wrong.

The difference is only where the secret is presented, and what a run it starts is attributed
to.

| | Session | API token |
| --- | --- | --- |
| Minted by | `POST /api/v1/auth/login` | `dg admin token create`, or `POST /api/v1/tokens` |
| Presented as | the `dirigent_session` cookie | `Authorization: Bearer <token>` |
| Lifetime | 14 days | none by default; an expiry may be set at mint time |
| Listed by | nothing -- sessions are not an operator-facing listing | `dg admin token list` |
| A run it starts is attributed | to the user | to the user, and the token by name |

The header wins over the cookie when both are present.

**Passwords** are Argon2id hashes, at the `argon2-cffi` library defaults, with a minimum
length of eight characters enforced before anything is hashed. A login against an account
that does not exist still verifies against a real Argon2id hash of a value nothing can
present, so the timing of a miss matches the timing of a hit.

**Tokens** are 32 bytes from the system CSPRNG, base64url-encoded. Only a SHA-256 of the
presented value is stored, alongside the first eight characters in the clear so that a listing
can tell two tokens apart without holding either. A plain SHA-256 is the right hash here and a
password hash would be wrong: the token has full entropy, so there is nothing to brute-force,
and the lookup happens on every single request.

**The login route is rate limited** on the client address *and* on the username, at
`DIRIGENT_LOGIN_RATE_PER_MINUTE` (default 10) each. Those are two different attacks -- a flood
from one place, and credential stuffing spread across many -- and Argon2id at 64 MiB is
expensive by design, so an unauthenticated caller who could invoke it freely could turn a few
hundred requests a second into the memory and CPU of the whole instance.

**First run.** Nothing can authenticate before an account exists, so account creation has a
local path that does not go through the API: `dg admin user create` runs against the
configured database the way `dg db upgrade` does, and `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`
creates the first admin unattended in a container. Both are one-way -- they do nothing once
any account exists -- so leaving the variable set on every deploy cannot reset a live
instance's password. `dg dev` mints a development admin and prints its token once, because
that is a SQLite file on a laptop.

### The account lifecycle

An account is created, edited, deactivated, and activated again. There is no delete: a run, a
token and an audit line all point at the account that owns them.

| What | How | Who |
| --- | --- | --- |
| Create | `POST /api/v1/users`, `dg admin user create` | admin |
| Edit the display name, the email or the role | `PATCH /api/v1/users/{username}`, with `name` as the display string | admin |
| Deactivate | `POST /api/v1/users/{username}/$deactivate`, `dg admin user deactivate` | admin |
| Activate | `POST /api/v1/users/{username}/$activate`, `dg admin user activate` | admin |
| Change your own password | `POST /api/v1/auth/password`, `dg auth password` | any principal |
| Reset another account's password | `POST /api/v1/users/{username}/$reset-password`, `dg admin user password` | admin |

`PATCH` carries partial semantics: a field the body left out is left alone, and `name`
sent as null is cleared. Those are two different requests, told apart by what the body
contained rather than by the value arriving as null either way. The username and the password
are not editable through it.

**Deactivation is the off switch, and it is complete.** An account's `active` flag is checked
in two places: `authenticate` refuses a login, and `resolve_token` refuses every credential the
account holds, session or API token alike. Deactivating also revokes the account's live
sessions, in the same flush that sets the flag, so no window exists in which the account is
barred from logging in while a session it already had still resolves. Activating it again does
not restore those sessions -- the person logs in.

**The last-admin guard.** Demoting an admin, or deactivating one, is refused with a 409 when it
would leave the instance with zero *active* admins. A deactivated admin does not count towards
the total, so it cannot rescue an instance from having nobody able to manage it. This is the
one guard that makes an admin screen safe to hand to an admin: the obvious mistake -- demoting
yourself, or switching yourself off -- is the one that cannot be undone from inside the product.

**Self-service password change.** `POST /api/v1/auth/password` takes the current password and
the new one. A wrong current password is a 403; the new one goes through the same minimum
length every other password does, and a short one is a 422. On success, every *other* session
of the account is revoked and the credential the request arrived on is kept, so the change does
not log the person out of the page they made it from. API tokens are untouched: a password
change is not a reason to break a CI job, and `dg admin token revoke` is the thing that is.

**Admin reset.** `POST /api/v1/users/{username}/$reset-password` takes only the new password:
an admin does not know the one in force, which is what makes this a reset rather than a
change. The new password goes through the same minimum length, and a short one is a 422. Every
session of that account is revoked, including the one it may be sitting in. API tokens are
untouched, for the same reason they survive a self-service change.

### What is unauthenticated

Four things, and they are exempt by not being mounted behind the authenticated router rather
than by an exception list each endpoint remembers:

- `GET /health` and `GET /health/ready`.
- `POST /api/v1/auth/login`, which cannot require what it hands out.
- `/docs`, `/redoc`, and `/openapi.json`. These are FastAPI's defaults and are open. If your
  deployment does not want the API surface published, do not expose them past your proxy.
- `POST /hooks/{token}`, which has its own credential and its own rules. See
  [webhook hardening](#webhook-hardening).

Every other route under `/api/v1` requires a principal, as a property of the router mount.

### Cross-site writes

The session cookie is an ambient credential: a browser attaches it to a request another site's
page caused, so without a check, `evil.example` could make your browser POST to your instance
and the request would arrive fully authenticated. `SameSite=Lax` on the cookie stops the
common shapes of that; it is one browser-side flag, and the server is not entitled to assume
it was honoured.

So every state-changing request under the API prefix -- `POST`, `PUT`, `PATCH`, `DELETE` --
that a session cookie would authenticate has to say it came from this instance:

- `Sec-Fetch-Site` decides it when the browser sends it, which every current browser does.
  `same-origin` and `none` (a typed URL, a bookmark) pass; `cross-site` and `same-site` are
  refused with `403`.
- `Origin` is the fallback when there is no fetch metadata: it has to match the scheme, host
  and port the request arrived on.
- A request with neither header is not from a browser, and passes. `curl` and the SDK are
  unaffected.

**A bearer token is exempt**, because nothing attaches it ambiently: a cross-site page cannot
make a browser send an `Authorization` header it does not know. When a request carries both, the
header wins, as it does everywhere else, and the request is treated as automation.

**`POST /api/v1/auth/login` is guarded too**, although no session exists yet. A cross-site
login POST is the login-fixation vector: it logs the victim's browser into an account the
attacker controls, and everything the victim then does is attributed there.

The check runs in middleware, ahead of routing, so no route can be added past it and no
dependency ordering can skip it. `POST /hooks/{token}` is outside the API prefix and outside
this: its token is its credential, and no browser holds one.

**Behind a TLS-terminating proxy**, make sure the proxy sets `X-Forwarded-Proto` and that
uvicorn is trusting it, or the fallback `Origin` comparison sees `http` where the browser
said `https`. Current browsers send `Sec-Fetch-Site`, which is checked first and carries no
scheme, so this only bites older ones.

## What authorizes

Three roles are enforced: **admin**, **operator**, and **viewer**. The boundary is applied per
endpoint rather than at a mount, and it is a ladder -- an admin may do everything an operator
may, and an operator everything a viewer may.

- A **viewer** may read. Every `GET`, the run event stream, a pipeline export and a run report,
  and the two routes that act on the caller's own credential: `POST /api/v1/auth/logout` and
  `POST /api/v1/auth/password`. `POST /api/v1/pipelines/{code}/$validate` is a read as well --
  it reports what a stored version would fail on and writes nothing. Anything else that writes
  is a `403`.
- An **operator** may in addition change pipelines and runs: apply, prune, activate, deactivate,
  run, backfill, cancel, retry, every schedule and webhook operation, deleting a triggers
  document with the rows it owns, alert rules, and the notifier test.
- An **admin** may in addition hand out authority. That set is exact:

| Operation | Why it is admin |
| --- | --- |
| `GET /api/v1/tokens` | Listing credentials |
| `POST /api/v1/tokens` | Minting a credential |
| `DELETE /api/v1/tokens/{name}` | Revoking a credential |
| `GET /api/v1/users/{username}/tokens` | Listing another account's credentials |
| `POST /api/v1/users/{username}/tokens` | Minting a credential for another account |
| `DELETE /api/v1/users/{username}/tokens/{name}` | Revoking another account's credential |
| `GET /api/v1/users` | Listing accounts |
| `POST /api/v1/users` | Creating an account |
| `PATCH /api/v1/users/{username}` | Changing what an account may do |
| `POST /api/v1/users/{username}/$deactivate` | Taking away an account's access |
| `POST /api/v1/users/{username}/$activate` | Giving it back |
| `POST /api/v1/users/{username}/$reset-password` | Setting an account's password without its old one |
| `POST /api/v1/connections` | Storing a third-party credential |
| `PATCH /api/v1/connections/{code}` | Changing one |
| `DELETE /api/v1/connections/{code}` | Removing one |
| `POST /api/v1/connections/{code}/$check` | Making the instance use a credential on demand |
| `DELETE /api/v1/pipelines/{code}` | Destroying a definition and its history |
| `POST /api/v1/schemas` | Publishing a shape every document may reference |
| `PATCH /api/v1/schemas/{code}` | Changing one under everything that references it |
| `DELETE /api/v1/schemas/{code}` | Removing one under everything that references it |

A write a role may not perform is answered with `403` and one sentence of detail:
`not permitted for your role`. It is the same status and the same sentence whichever boundary
refused it, so the answer says neither which role would have sufficed nor what any role may
do -- a refusal is not the place to teach the permission model. The `403` a cookie write
initiated by another site gets is the only one with a different detail, and it says so.

Two consequences worth being deliberate about. Listing connections is available to a viewer, so
any principal can see which credentials exist and what their non-secret settings are; the secret
fields are redacted, but the existence and shape of a credential is not a secret from an
operator. And `POST /api/v1/users` names a role or is refused; there is no default, so a script
cannot make an admin by leaving a field out. `dg admin user create` takes the same
`--role admin|operator|viewer` and is refused without it.

### Why opaque tokens, not JWTs

A dirigent bearer credential is a random secret with no structure and no claims. It means
nothing on its own; the server looks up its hash and finds the row that says who it is. That
costs one indexed lookup per request, which is a real cost, and it buys three things a signed
self-contained token cannot give you without rebuilding them by hand.

**Revocation is immediate.** Setting `revoked_at` on a row ends that credential on the very
next request. A JWT is valid until it expires, so revoking one means either a very short
expiry with a refresh dance, or a server-side denylist -- which is a per-request lookup, which
is exactly the cost going stateless was supposed to avoid, except now you have both a lookup
and a signature to verify. An orchestrator holds the credentials to every system its pipelines
touch. When a token leaks, "revoked now" is the only useful meaning of revoked.

**Long-lived automation credentials fit the model.** The dominant use is a CI job or a script
holding a token for a year. A short-lived token is the wrong shape for that, and a long-lived
JWT is precisely the credential nobody can take back.

**The row is the audit trail.** A token has a name, a visible prefix, a creator, and a
`last_used_at`. That is what answers "is this token still in use, and may I revoke it?" -- a
question a stateless credential cannot answer at all, because the server never sees the same
one twice in any way it can count.

The write that field would otherwise cost is throttled. A token's first use is always
recorded; after that the timestamp is rewritten only once a minute has gone by, so a token
presented a thousand times a minute leaves one row write rather than a thousand. The field
answers "when was this credential last used", which no audit needs to the second. Read
`last_used_at` as accurate to the minute, never to the request.

What remains is the indexed lookup on every request, and that is the cost the design accepts
deliberately, in exchange for the three things above.

JWTs do have a place here, and it is the **federation boundary**. When OIDC/SSO lands, the
shape is: validate a token an identity provider signed (realistically Keycloak, in the DHIS2
world this project comes from), map its subject onto a local user, and then issue dirigent's
own opaque credential for every request afterwards. JWT as the format two systems agree on,
never as the format dirigent authenticates itself with. That keeps the revocation story, the
audit trail, and the automation story intact, and confines the IdP's token to the one request
where it is genuinely useful.

## Token lifecycle

A token belongs to exactly one account, and it authenticates as that account with that
account's role. There are two paths to one. `/api/v1/tokens` is the instance-wide listing plus
the caller's own mint and revoke: `POST` mints for whoever is calling, and `DELETE` reaches
only the caller's own tokens. `/api/v1/users/{username}/tokens` is the admin's path over any
account: list, mint, and revoke a token that belongs to someone else. Both are admin-only, the
first because listing every credential an instance holds is itself authority.

**Minting.** `dg admin token create NAME`, or `POST /api/v1/tokens`; `dg admin token create
NAME --user U` and `POST /api/v1/users/{username}/tokens` mint for another account. The secret
is generated server-side and returned exactly once, in the response to the mint. It is never
recoverable afterwards -- the instance holds only the SHA-256 and the eight-character prefix.

**Presenting.** `Authorization: Bearer <token>`. Resolution hashes what was presented and does
an indexed equality lookup, then checks in order: the row exists, `revoked_at` is null, the
user exists and is active, and `expires_at` has not passed. Any of those failing is the same
answer -- no principal.

**Listing.** `dg admin token list` shows the account, the name, the prefix, the creation time,
`last_used_at`, and whether it is revoked. Sessions are excluded from the listing, because a
browser session is not something an operator manages by name.

**Revocation.** `dg admin token revoke NAME` for the caller's own, `--user U` for another
account's; over HTTP that is `DELETE /api/v1/tokens/{name}` and
`DELETE /api/v1/users/{username}/tokens/{name}`. It sets `revoked_at` and takes effect on the
next request. Revocation matches by **name**, and a name is unique only within an account --
revoking a name revokes that account's live tokens holding it and reaches no one else's.
Logging out revokes the session the cookie carries by the same mechanism.

**Expiry.** A token may be minted with a lifetime, in which case it stops resolving at that
instant. There is no default lifetime for an API token; a session gets 14 days.

**Rotation.** There is no built-in rotation command and no overlap window. Rotating means:
mint the new token, deploy it wherever the old one is used, then revoke the old one --
checking `last_used_at` first, which is exactly what it is there for. Do not revoke before
you have confirmed nothing is still presenting it.

## Webhook hardening

`POST /hooks/{token}` is the only unauthenticated write surface the product exposes, and it is
mounted at the application root rather than under `/api/v1` on purpose. Authentication under
`/api/v1` is a property of the mount: every route there requires a principal. A webhook has no
principal to present -- its token *is* its credential, and it authenticates as the trigger
rather than as a person. Two authentication models on one mount is how one of them eventually
ends up wrong.

**The token is the whole credential.** It is 32 bytes from the CSPRNG, minted server-side,
stored only as a SHA-256 with an eight-character prefix beside it, and shown exactly once --
when the webhook is created, or when `dg webhook rotate-token` replaces it. It never appears in
a document, in an export, or in a listing; there is nowhere in `dirigent/v1` to write one, and
a document that declares a webhook re-applies without rotating it, because breaking every
caller as a side effect of an unrelated edit is not a behaviour anyone wants.

**Unknown, revoked, and disabled answer identically.** A token that resolves to nothing and a
token that resolves to a disabled webhook both return 404 with the same body, so the endpoint
is not an oracle for discovering which tokens once addressed something real. That equivalence
is maintained under load too: a disabled webhook's own rate limit is deliberately *not*
applied, because a different 429 threshold would have leaked exactly what the matching 404s
exist to hide.

**HMAC is optional and additive.** A webhook carrying a signing secret requires an
`X-Dirigent-Signature` header: HMAC-SHA256 over the **raw body** -- the bytes as they arrived,
not a re-serialization of the parsed JSON, because those are not the same string. A `sha256=`
prefix is accepted, since several popular senders write one. The comparison is constant-time
and operates on bytes rather than strings, because a header is attacker-controlled and
`hmac.compare_digest` raises on a non-ASCII `str`: the string version turned a one-byte change
in a request header into a 500 and a rolled-back session, which meant the refusal left no
evidence at all. The signing secret itself is sealed with the instance key, the way a
connection's secret is. An empty secret is refused at declaration rather than stored, because
a webhook that reads as signed and verifies nothing is worse than an honestly unsigned one:
either send a secret or send none.

**Rate limiting happens before the body is read**, in two layers:

- An **intake** bucket keyed on the hash of whatever token was *offered*, checked before
  anything is looked up, at `DIRIGENT_WEBHOOK_INTAKE_RATE_PER_MINUTE` (default 120). This is
  what bounds a stranger spraying the endpoint: a dictionary lookup each, rather than a
  database query each.
- The webhook's own `rate_limit_per_minute` (default 60), applied only to a live webhook.

Both buckets are in memory and therefore per process: behind N API replicas the effective
limit is the configured rate times N. That is documented rather than fixed, because the
alternative -- a row updated on every delivery -- turns a cheap refusal into a database write,
which is precisely what a caller hammering the endpoint would be trying to cause. The trade is
that a throttled delivery leaves no row in the delivery history; it is logged instead.

**The body is bounded.** Reading stops one byte past
`DIRIGENT_WEBHOOK_MAX_PAYLOAD` (default 1 MiB) rather than buffering whatever arrives and
measuring afterwards, so an unauthenticated caller cannot make the process allocate a gigabyte
in order to be told that a megabyte is the maximum. An oversized delivery still reaches the
refusal path, so it is still recorded.

**The mapping is strict and small.** `params_from_payload` is JSONPath-lite: a leading `$.`,
dotted keys, and a numeric segment for a list element. No filters, wildcards, or slices, for
the same reason the reference language has no expressions -- a mapping a reviewer cannot
evaluate in their head is a mapping nobody can audit. It reads the JSON body and nothing else:
not headers, not the query string. What it produces is validated against the pipeline's own
parameter schema like any other run's parameters, so a webhook cannot smuggle configuration
past the schema.

**Every delivery is recorded, refusals included** -- what arrived (truncated past 8 KiB), what
it mapped to, the source address, and the run id or the reason. This is why a refusal inside
the delivery path is a *returned value* rather than a raised exception: the row explaining why
a call was refused is written in the same transaction, and an exception escaping would roll
back exactly the evidence someone debugging their sender needs. Read it with `dg webhook
deliveries PIPELINE NAME`.

Note the asymmetry that follows from the two paragraphs above: a *refused* delivery leaves a
row, a *throttled* one does not. If a sender insists it has been calling all night and the
history is empty, check the process log for rate limiting before concluding nothing arrived.

## Local execution and the unsafe-block allowlist

Some blocks execute code on the worker. `shell.run` runs a process; `docker.run` talks to the
Docker daemon, and reaching the Docker socket is reaching root on the host. A block declares
this about itself by setting `local_execution` in its spec, and the engine refuses to run any
such block unless the instance names its id in `DIRIGENT_ENABLED_UNSAFE_BLOCKS`.

The reason is one sentence: **"can edit a pipeline" must not silently mean "can run code on a
worker."** Any operator can apply a pipeline. If applying one were enough to
execute arbitrary commands on every worker in the pool, then the pipeline-editing permission
would in fact be a shell on the infrastructure, and the difference between an operator and a
host administrator would be a distinction nobody could rely on. The allowlist is what makes
enabling that an explicit, host-level decision -- taken by whoever configures the deployment,
not by whoever writes a document.

The gate is enforced **twice**: when a run is created, and again when a worker claims the
step. Two checks rather than one, so that tightening the configuration stops work that was
already queued.

`dg run --local --enable-unsafe shell.run` adds to the allowlist for exactly one command. It
never turns the gate off, and it does not affect a server.

`docker.run` deserves its own sentence. Its containers default to `network: none`, because an
image a stored pipeline named should not reach the worker's network unless the step says so.
Allowlisting `docker.run` is a decision about the host, not about a pipeline.

A `docker` connection carries the two docker credentials there are, and both are sealed: the
client TLS key that reaches a remote daemon, and the registry password a `docker.build` pushes
with. Sealed means encrypted at rest, redacted in every API response, and never an argument or
an inherited variable. Each reaches the CLI only as a 0600 file in a 0700 directory under the
run's scratch space -- the key as `DOCKER_CERT_PATH`, the login as a `DOCKER_CONFIG` of its own
-- and both directories are removed when the step leaves, whether it succeeded, failed or was
cancelled. A push logs out before it returns, so the worker's own docker config is never
written to and no session survives the step.

### The `DIRIGENT_*` environment denial

Both blocks let a step name worker environment variables to inherit, through `env_allowlist`.
That is the point of an allowlist -- a step that needs `JAVA_HOME` should be able to say so --
but the worker's environment is also where dirigent's own secrets live, and `env_allowlist` is
a field of a *pipeline document*. Without a denylist, anyone who can edit a pipeline could
write:

```yaml
env_allowlist: [DIRIGENT_SECRET_KEY]
command: 'echo "$DIRIGENT_SECRET_KEY"'
```

and read the envelope key out of `log_entries`, which every principal can read. That is a
privilege escalation from "can edit pipelines" to "can decrypt every stored connection
secret" -- precisely the boundary the allowlist exists to hold.

So any variable whose name starts with `DIRIGENT_` (case-insensitively) is refused. It is
enforced in two places on purpose: at config validation, which is where a person is told, with
the pipeline named, at `dg apply` rather than at three in the morning on a worker; and again
when the environment is actually built, which is what holds for a document that was stored
before the check existed.

The same boundary holds for a block that never touches the environment on purpose but could:
`transform.jq` shadows jq's own `env` and `$ENV`, so a program reads an empty object rather
than the worker's process. An engine that runs behind no allowlist must not be a way around
one.

`shell.run` additionally passes only `PATH`, `LANG`, `LC_ALL`, and `TZ` plus whatever the
allowlist names -- never the worker's environment wholesale -- and gets a scratch-scoped
working directory it cannot climb out of.

It also gets a deadline it cannot outlive, and neither can anything it starts. The command
runs in a session of its own, and that whole session is killed when the block's own timeout
expires, when the engine's step timeout cancels the attempt, and on any other way out of the
block. A command is usually `sh -c`, so killing only the process that was started would
leave the children doing the work still running.

## Secrets lifecycle

A connection's secret fields never sit in a readable column. The mechanism is envelope
encryption, split by field rather than by blob: a connection kind declares which of its fields
are secret by typing them `SecretStr`, the public settings stay as queryable JSON on the row,
and only the secret fields go into a Fernet-sealed envelope. The same declaration that makes
the API redact a field is what makes the engine encrypt it, so the two cannot drift apart.

Each envelope is stamped with a short, non-reversible **key id** (the first twelve hex
characters of the key's own SHA-256), so an instance can tell which key sealed a row without
trying to decrypt it -- and so a failure to open one says "sealed by key `abc123…`" rather than
"decryption failed".

**Decryption happens on the worker path alone**, at the moment a block asks the step context
for its connection. It does not happen when a connection is listed, shown, or applied.

### Where the key comes from

`DIRIGENT_SECRET_KEY`, and nothing else. Per twelve-factor, it is configuration in the
environment: an environment variable, or a value in the `dirigent.yaml` the process reads at
boot. **Dirigent assumes no secret manager.** There is no KMS integration, no Vault client, no
key-fetch hook. If your platform provides secrets, its job is to put this variable in the
process environment before dirigent starts; dirigent does not reach out for it.

The value may be either a real Fernet key or an arbitrary passphrase. A well-formed Fernet key
is used as-is, which is what lets an operator generate one with the library's own generator:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Anything else is SHA-256'd into a valid 32-byte key, so a human-typed passphrase yields a
working instance rather than a startup crash. Prefer the generated key.

Every process that touches connection secrets needs the same value: the server, every worker,
and the scheduler. Distributing it is one of the four things multi-node deployment requires.

An instance with no key configured still starts, and still runs pipelines that use no
connection secrets. It refuses -- clearly, naming the variable -- the moment something has to
be sealed or opened.

### Rotation, honestly

**There is no key rotation tooling, and no support for reading rows sealed by an old key while
writing new ones with a new key.** The key id is stored, so a mismatch is diagnosed
precisely rather than mysteriously, but nothing uses it to select between two keys. Changing
`DIRIGENT_SECRET_KEY` makes every existing envelope unopenable, and the failure appears on the
worker path, at the moment a pipeline needs a credential.

Given what the code supports, rotating a key means re-entering the credentials:

1. Record which connections exist and what their non-secret settings are (`dg connection
   list`, and `dg connection show NAME` for each). The secrets are not readable; you need them
   from wherever you actually keep them.
2. Stop the writers, or accept a window in which runs needing a credential fail.
3. Set the new `DIRIGENT_SECRET_KEY` on every process.
4. Re-enter each connection's secret fields, which seals them with the new key. The CLI has no
   update command, so this is `dg connection delete CODE` followed by `dg connection create
   KIND CODE --set field=value` -- documents reference a connection by code, so recreating it
   under the same code is invisible to them. `PATCH /api/v1/connections/{code}` does it in
   place if you would rather script it against the API.
5. Run `dg connection check CODE` for each, which is the one command that actually opens an
   envelope and uses what is inside it.

The same applies to any webhook HMAC secret, which is sealed with the same key. There is no
update command for a webhook either, so re-entering a signing secret means `dg webhook delete`
and `dg webhook create ... --hmac-secret`. Note that this mints a new token as well, so every
sender has to be updated.

Treat losing the key as losing the credentials. Back it up somewhere that is not the database
backup, because a backup containing both the envelopes and the key that opens them is not an
encrypted backup.

### Where secrets are not

Marked-secret fields are redacted as `***` in every API response, and they never appear in a
pipeline definition, an export, or a process log. Paths carrying credentials are redacted
before they reach a log line or an OpenTelemetry span name -- a delivery to
`POST /hooks/<token>` carries its whole credential in the URL path, and a span name travels to
every trace viewer the operator has. A secret field that is not set reads as `null`, not as
`***`: the marker means a credential is stored.

That is what makes a redacted read editable. `PATCH /api/v1/connections/{code}` replaces the
config whole, and a secret field carrying the marker means **keep what is stored** -- the
sealed value is put back before the config is validated and sealed again, so changing a base
URL does not mean re-typing every credential. Any other value replaces the secret. The marker
where nothing is stored is refused with a 422, because nothing tells it apart from somebody
choosing three asterisks as a password; the literal `***` is therefore reserved and cannot be
stored as a secret value.

A document may carry its own connections, and one that does holds whatever it holds in plain
text: it is a file, not an instance record, and nothing encrypts or redacts it. A server
**refuses to apply such a document**, which is what keeps the paragraph above true of anything
stored -- no version row, export or diff can carry a credential that way. Carry one only where
the credential is already public, such as a demo instance whose password is documented; for
anything else the instance holds the connection and the document names it by code.

## Network placement

Dirigent's coordination is entirely PostgreSQL. There is no inter-service protocol and no port
on a worker: a worker's only inbound dependency is the database. That makes the placement
question small.

**Expose:** the API server's port (3333 by default), through whatever proxy terminates TLS.
Dirigent does not terminate TLS itself.

**Do not expose:** PostgreSQL, and the workers -- which listen on nothing, so there is nothing
to expose. The compose file publishes the Postgres port for local convenience; a real
deployment should not.

**The hooks endpoint.** `POST /hooks/{token}` sits at the application root, deliberately
outside `/api/v1`. If senders are outside your network and operators are inside, that split is
your seam: a proxy can publish `/hooks/*` to the internet and keep `/api/v1/*` on the internal
side, with no change to dirigent. Note that this only works because the split is structural.
Do not invert it -- publishing `/api/v1` and firewalling `/hooks` gets you nothing, since
`/api/v1` is the surface that holds the credentials.

**The OpenAPI document, `/docs`, and `/redoc` are unauthenticated.** If the API is
internet-facing and you would rather not publish its shape, block those three paths at the
proxy.

**Set `DIRIGENT_ALERT_BASE_URL`** to the externally reachable base URL, so alerts link back to
the run they are about. It has to be set on the workers as well as the server, because the
alert context is built by whichever worker settles the run.

## What is deliberately not built yet

Stated plainly, because a security page that lists only what exists is not much use.

- **OIDC/SSO.** No identity-provider integration of any kind. Accounts are local, passwords are
  local, and there is no way to delegate authentication. The intended shape when it lands is
  in [Why opaque tokens, not JWTs](#why-opaque-tokens-not-jwts).
- **RBAC beyond the three roles.** `admin`, `operator` and `viewer` are enforced, and that is
  the whole model: the role is a property of the account and applies to the entire instance.
  There are no custom roles and no way to grant one operation without the rest of its rung.
- **Per-pipeline permissions.** None. Every operator can run every pipeline, read every run and
  every log, and create schedules and webhooks on anything.
- **Per-connection permissions.** None. Any principal can list connections, and any operator
  can write a pipeline that uses any of them. Admin gates creating and modifying a connection, not using
  it.
- **MFA, password policy, account lockout.** None of these exist. There is a minimum length of
  eight characters and a rate limit on login, and that is the whole of it.
- **Audit log.** There is attribution -- every run points at what started it -- and there are
  process logs. There is no queryable record of administrative actions: who created a
  connection, who revoked a token, who deleted a pipeline.
- **Secret-manager integration.** None, by design. See [where the key comes
  from](#where-the-key-comes-from).
- **Key rotation.** Not supported. See [rotation, honestly](#rotation-honestly).
- **Egress control.** No allowlist on outbound requests. A pipeline can call any URL the worker
  can reach, which for a worker inside your network means your network.

  What a redirect cannot do is carry a connection's credentials somewhere else: the client
  drops the `Authorization` header when the origin changes, so a service that redirects
  before authenticating has to be configured with the URL it redirects to. `follow_redirects`
  is off by default in any case.
- **Rate limiting on the authenticated API.** Only login and webhook intake are limited.
- **A CSRF token.** There is none, and the defence is instead the origin check on every
  cookie-authenticated write described in [cross-site writes](#cross-site-writes), on top of
  the cookie's `SameSite=Lax`. That is the modern shape and it is what the UI relies on; a
  synchroniser token would add a second mechanism, not a second layer. What it does mean is
  that a browser sending neither `Sec-Fetch-Site` nor `Origin` on a cross-site write would not
  be caught, so an instance exposed to browsers older than the fetch-metadata rollout is
  relying on `SameSite=Lax` alone.
- **Retention is off until configured.** Each family has its own age and nothing is pruned
  until one is set, so an instance nobody has configured grows without bound. Log
  entries in particular are readable by every principal, so a secret
  that a block prints into a log is there permanently. See [known
  debt](operations.md#known-debt).

## Reporting a security issue

Report privately through [GitHub's private vulnerability
reporting](https://github.com/winterop-com/dirigent/security/advisories/new). The policy,
including what is in scope and what is deliberately dangerous, is
[SECURITY.md](https://github.com/winterop-com/dirigent/blob/main/SECURITY.md).
Please do not open a public issue for anything that looks exploitable against a running
instance.
