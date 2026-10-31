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
  OpenAPI document, and the endpoint sources a pipeline declares.
- Enumeration of accounts through the login endpoint -- a missing account and a wrong password
  return the same answer and take the same time, because a short-circuit on a missing user
  answered "does this account exist?" to anyone with a stopwatch.
- A forged call to a signed endpoint source -- a body is admitted only under a signature made
  with the source's secret, compared in constant time.
- Credential exfiltration through a stored pipeline: a document cannot inherit the instance's
  own environment variables, cannot address a `file://` URI outside the artifact root, cannot
  open a database file its `sql` connection does not name, and
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
  unauthenticated write paths (login and endpoint sources) and nowhere else.
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

**The session cookie is `Secure`** whenever the login arrived over HTTPS, and always when
`DIRIGENT_ENVIRONMENT` is not `local`, so only a login over plain HTTP on a `local` instance gets
a cookie a browser would also send over plain HTTP. A proxy that terminates TLS is believed
through uvicorn's own trust setting: `X-Forwarded-Proto` counts only from an address in
`FORWARDED_ALLOW_IPS`, which defaults to `127.0.0.1`.

**Passwords** are Argon2id hashes, at the `argon2-cffi` library defaults, with a minimum
length of eight characters enforced before anything is hashed. A login against an account
that does not exist still verifies against a real Argon2id hash of a value nothing can
present, so the timing of a miss matches the timing of a hit.

**Tokens** are 32 bytes from the system CSPRNG, base64url-encoded. Only a SHA-256 of the
presented value is stored, alongside the first eight characters in the clear so that a listing
can tell two tokens apart without holding either. A plain SHA-256 is the right hash here and a
password hash would be wrong: the token has full entropy, so there is nothing to brute-force,
and the lookup happens on every single request.

**The login route is rate limited** twice: one username from one address at
`DIRIGENT_LOGIN_RATE_PER_MINUTE` (default 10), and one address across every username at
`DIRIGENT_LOGIN_ADDRESS_RATE_PER_MINUTE` (default 60). The first slows guessing at one account
and is counted per address, so a stranger failing logins against a named account spends their
own count and not its owner's. The second bounds what one machine can spend, because Argon2id
at 64 MiB is expensive by design, and an unauthenticated caller who could invoke it freely could
turn a few hundred requests a second into the memory and CPU of the whole instance. No count
spans addresses, so guessing spread across many addresses is limited only per address: a strong
password is what stops that.

Both counts read the address the server sees. Behind a reverse proxy that is the proxy's own
unless uvicorn trusts it, so set `FORWARDED_ALLOW_IPS` to the proxy's address: otherwise every
caller shares one address, and a stranger can again lock a named account out.

**First run.** Nothing can authenticate before an account exists, so account creation has a
local path that does not go through the API: `dg admin user create` runs against the
configured database the way `dg db upgrade` does, and `DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD`
creates the first admin unattended in a container. Both are one-way -- they do nothing once
any account exists -- so leaving the variable set on every deploy cannot reset a live
instance's password. `dg dev` mints a development admin and prints its token once, because
that is a SQLite file on a laptop. Its password is the fixed `admin`, so it stays on loopback:
`dg dev` refuses a non-loopback bind, whether from `--host` or `DIRIGENT_HOST`, while that login
would be made or still stands. `scripts/seed_dev.py`, which pairs the login with an unsafe
allowlist, refuses one outright.

On a loopback bind, `dg dev` also answers only to a loopback name: `localhost`, or an address such
as `127.0.0.1` or `[::1]`. Any other `Host` is refused 421 (`server.host_not_loopback`) before the
request is read. Without that, a page on a name that resolves to 127.0.0.1 could read this instance
as its own origin and sign in as `admin`. A proxy in front of a loopback `dg dev` has to send one of
those names as `Host`. A non-loopback bind has no such check, and `dg server` never does, because a
proxy on the same host commonly fronts a loopback `dg server` under its public name.

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

**A body is bounded before anyone has proved who they are.** A route parses its body before
it authenticates, so `/api/v1` holds at most 1 MiB from a caller and checks its credential before
reading past that. A caller with no credential, or one that does not resolve, is answered 413
(`server.unauthenticated_body_too_large`). A login is held to 16 KiB whatever it presents. A body
that has not arrived whole within 30 seconds is answered 408 and the connection closed
(`server.body_timed_out`), unless the caller's credential resolves. A
rate-limit key longer than 128 characters is held as its hash.

### What is unauthenticated

Five things, and they are exempt by not being mounted behind the authenticated router rather
than by an exception list each endpoint remembers:

- `GET /health` and `GET /health/ready`.
- `POST /api/v1/auth/login`, which cannot require what it hands out.
- `/docs`, `/redoc`, and `/openapi.json`. These are open. If your
  deployment does not want the API surface published, do not expose them past your proxy.
- Every route under `/endpoints`, which a pipeline's endpoint sources declare, each with its own
  token or signing secret unless it writes itself public. See [endpoint hardening](#endpoint-hardening).
- The [playground](playground.md) under `/api/v1/playground`, which reflects at most 8 KiB of a body, opens no session and reads no
  instance data. It shares the UI's origin, so what a caller can make it answer is contained:
  every answer carries `nosniff` and a sandboxing CSP, it answers under no content type a browser
  runs, it sets no header that would make the origin act for the caller, it redirects only on
  its own origin, and it reads at most 1 MiB of a body. A stream ends 95 seconds after it arrives
  whether or not its client reads it, and one process holds 32 of them.
  `DIRIGENT_PLAYGROUND_ENABLED=false` unmounts it.

Every other route under `/api/v1` requires a principal, as a property of the router mount.

### What every response says to a browser

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: same-origin` and a `Content-Security-Policy` that includes
`frame-ancestors 'none'`, so no page of this instance can be framed by another site. The UI's
policy allows scripts only from this origin, workers from this origin or `blob:` for the
editor, and inline styles. `/docs` and `/redoc` load Swagger UI and ReDoc from `cdn.jsdelivr.net`,
each pinned to one exact release and to its subresource integrity hash, so a browser runs those
bytes or nothing. Their policy of their own names those exact URLs rather than the CDN, and
Swagger UI's inline bootstrap by its hash. A newer release of either arrives only with a dirigent
release that changes both the version and the hash. ReDoc's badge image still loads from
`cdn.redoc.ly`, and neither page loads web fonts. A route that sets one of these headers itself keeps its own value. A terminating proxy
that also sets them should agree with these, because a browser enforces every policy it is sent.

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
dependency ordering can skip it. `/endpoints` is outside the API prefix and outside this: a
source's token or signature is its credential, and no browser holds one.

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
  run, backfill, cancel, retry, every schedule and source operation, deleting a triggers
  document with the rows it owns, alert rules, and the notifier test.
- An **admin** may in addition hand out authority. That set is exact:

| Operation | Why it is admin |
| --- | --- |
| `GET /api/v1/tokens` | Listing credentials |
| `POST /api/v1/tokens` | Minting a credential |
| `DELETE /api/v1/tokens/{id}` | Revoking a credential |
| `GET /api/v1/users/{username}/tokens` | Listing another account's credentials |
| `POST /api/v1/users/{username}/tokens` | Minting a credential for another account |
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
| `DELETE /api/v1/schemas/{code}` | Removing one, which is refused while a pipeline names it |

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
shape is: validate a token an identity provider signed (realistically Keycloak), map its subject onto a local user, and then issue dirigent's
own opaque credential for every request afterwards. JWT as the format two systems agree on,
never as the format dirigent authenticates itself with. That keeps the revocation story, the
audit trail, and the automation story intact, and confines the IdP's token to the one request
where it is genuinely useful.

## Token lifecycle

A token belongs to exactly one account, and it authenticates as that account with that
account's role. There are two paths to one. `/api/v1/tokens` is the instance-wide listing, the
caller's own mint, and the revoke: `POST` mints for whoever is calling, and `DELETE
/api/v1/tokens/{id}` revokes one token, whichever account holds it.
`/api/v1/users/{username}/tokens` is the admin's path over any account: list and mint a token that
belongs to someone else. Both are admin-only, the first because listing every credential an instance
holds is itself authority.

**Minting.** `dg admin token create NAME [--expires 90d]`, or `POST /api/v1/tokens` with
`expires_in`; `dg admin token create NAME --user U` and `POST /api/v1/users/{username}/tokens` mint for another account. The secret
is generated server-side and returned exactly once, in the response to the mint. It is never
recoverable afterwards -- the instance holds only the SHA-256 and the eight-character prefix.

**Presenting.** `Authorization: Bearer <token>`. Resolution hashes what was presented and does
an indexed equality lookup, then checks in order: the row exists, `revoked_at` is null, the
user exists and is active, and `expires_at` has not passed. Any of those failing is the same
answer -- no principal.

**Listing.** `dg admin token list` shows the account, the name, the prefix, the creation time,
`last_used_at`, `expires_at`, and whether it is revoked. Sessions are excluded from the listing, because a
browser session is not something an operator manages by name.

**Revocation.** `dg admin token revoke ID`, or `DELETE /api/v1/tokens/{id}` over HTTP, with the
id `dg admin token list` prints. It sets `revoked_at` on that one token and takes effect on the next
request. Two tokens may share a name, so a name is not what is revoked. A browser session shares the
table and is not reached from this path. Logging out revokes the session the cookie carries by the
same mechanism.

**Expiry.** A token may be minted with a lifetime, `--expires 90d` or `expires_in` over HTTP, in
which case it stops resolving at that instant. There is no default lifetime for an API token,
so one minted without it lives until it is revoked; a session gets 14 days. A lifetime is above
zero and under 100 years.

**Rotation.** There is no built-in rotation command and no overlap window. Rotating means:
mint the new token, deploy it wherever the old one is used, then revoke the old one --
checking `last_used_at` first, which is exactly what it is there for. Do not revoke before
you have confirmed nothing is still presenting it.

## Endpoint hardening

The routes under `/endpoints` are a pipeline's endpoint sources, mounted under their own prefix
(`DIRIGENT_ENDPOINT_PREFIX`) rather than under `/api/v1`: a call there authenticates as the
source, not as a person, and has no principal to present. Authentication under `/api/v1` is a
property of the mount, and two authentication models on one mount is how one of them
eventually ends up wrong.

**A token unless public is written out.** An endpoint source takes `Authorization: Bearer`
with the token the instance minted for it, 32 bytes from the CSPRNG, stored only as a SHA-256
with an eight-character prefix beside it, and compared in constant time. `auth: {kind: public}`
admits anyone, and only when the document says so. A re-apply keeps the token; `dg source
rotate-token` replaces it at once.

**Or a signature, with `auth: {kind: hmac}`.** The caller presents no token; it sends the
moment it signed in `X-Dirigent-Timestamp`, as whole Unix seconds, and HMAC-SHA256 over
`<timestamp>.<raw body>` -- the bytes as they arrived, not a re-serialization of the parsed
JSON, because those are not the same string -- in `X-Dirigent-Signature`, or the header
`auth.header` names. A `sha256=` prefix is accepted. A provider that signs only the body, with
no timestamp, cannot call a signed source directly.

**A signature is taken once.** A timestamp further than `DIRIGENT_SOURCE_SIGNATURE_WINDOW`
(5 minutes) from the server's clock when the body has arrived, either way, is refused 401, and
because the timestamp is signed it cannot be moved. Inside the window, a signature taken is
recorded in `source_signatures` until a minute after its timestamp leaves the window, and the
same signature presented again is refused 401. The record is in the database, so it holds across replicas and restarts,
and it is written only for a signature that verified, so it costs a stranger nothing and gives
them no way to fill it. A signature is spent by being verified, whatever the call is answered
afterwards, so a sender retrying a 429 or a 503 signs again; `webhook.post` and `dg source call`
do. One body signed twice in one second under one secret is one signature, and the second call
is refused, so a sender that means two calls makes their bodies differ.

The comparison is constant-time and operates on bytes rather than strings, because a header is
attacker-controlled and `hmac.compare_digest` raises on a non-ASCII `str`. The signing secret
is minted at apply from the CSPRNG and shown once, or set with `dg source set-secret` when the
sender issues it, and is sealed with the instance key, the way a connection's secret is. None
of it is stored in clear: a listing shows `secret_fingerprint`, 12 hex characters of an HMAC of
it under a key derived from the instance key. It says whether the secret changed. It cannot be
recomputed from the secret alone, so a reader who can list sources cannot test a guess at a
hand-set secret against it, and neither can a holder check which secret they have. A bearer token keeps
its eight-character prefix, because a minted token has 256 bits of entropy and the 48 shown
leave 208 to guess, while a signing secret can be one a provider issued, of any length, so a
prefix could be most of it. A re-apply keeps it, and `dg source rotate-token` replaces it. A signature is checked as soon as
the capped body is read, before the source's own rate and before anything is written, so a
call without one costs the read and no more.

**The token or secret is shown once, in the apply that created the source.** It is in the
apply's result, which `dg apply` writes as a record. An apply run in CI that creates a source
therefore writes that source's token or signing secret into the CI log. Either create sources
from a terminal, or treat a credential first shown in a log as exposed and rotate it before
giving it to a caller.

**A credential never reaches a run.** The input a run is entered with carries the request's
headers with `authorization`, `cookie`, `proxy-authorization` and `x-dirigent-signature`
removed.

**Nothing before the source's own rate writes a row.** A call is checked in one order: the
instance's bucket for the caller's address, the method and the route
(`DIRIGENT_SOURCE_INTAKE_RATE_PER_MINUTE`, before any source is read), the route, the token or, for a signed source, the capped read, the
timestamp and the signature, then the source's own `rate`. A refusal at any of those -- 429, 404, 405, 401, and a
signed source's 408 and 413 -- is counted in telemetry (`dirigent.source.inputs`) and logged, writes
nothing and spends nothing from the source's own bucket, so a stranger without the token or
the secret, or a caller in a loop, cannot cause writes or starve the source's real callers.
The first bucket is counted per address, so a stranger elsewhere spends their own count: behind a
reverse proxy that is the proxy's address unless uvicorn trusts it, so set `FORWARDED_ALLOW_IPS`
to the proxy's address, or every caller shares one count and a stranger can again spend it.
Every spelling of a route and every value of its parameters share one count, and every path no
route answers shares another, so a caller cannot widen its own count by spelling a path anew.
The record of a signature taken is the one write ahead of the rate, and only a caller holding
the secret causes it.
From there on every refusal, and every accepted input, is recorded against the source. Both
buckets are in memory and therefore per process: behind N API replicas the
effective limit is the configured rate times N, documented rather than fixed, because a row
updated on every call turns a cheap refusal into a database write.

**The body is bounded before it is read.** Reading stops one byte past the source's
`max_body` or the instance's `DIRIGENT_SOURCE_MAX_BODY`, whichever is smaller. For a source
taking a token, the content type is checked against what the source `accepts` before a byte of
the body is read; a signed source reads its capped body first, because the signature covers it.
A text body is decoded only from UTF-8, UTF-16, ASCII, ISO-8859-1 or Windows-1252, under their usual
spellings, so handling a capped body costs time in step with its size. Any other `charset` is
refused 415 (`source.charset_refused`) without decoding. A JSON body nesting more than 128 levels
of lists and objects is refused 400 (`source.body_too_deep`) and starts no run. A stored value
deeper than the engine can validate, from any source, fails the step that reads it
(`run.config_refused`) and holds back no other work. A JSON body holding half a surrogate pair
is refused 400 (`source.body_not_json`), because no database can store it.
A read holds no database connection: the call's transaction ends before it, and the source and
its pipeline are read again after it. A body that has not arrived whole within
`DIRIGENT_SOURCE_BODY_TIMEOUT` (default 30 seconds) is answered 408 and the connection closed,
so a stranger who stops sending holds one socket for that long and nothing the API shares.

**A value no database can hold is stored as text.** A JSON answer from an outside service can hold
half a surrogate pair, which JSONB refuses and no response can encode, or a NUL, which PostgreSQL
refuses in JSONB and in text. Every JSON column writes either as the six characters of its escape,
and so does every column holding text a run, a caller or a service produced: what a failure said, a
fan-out item's key, what a waiting step last saw, a notification's subject and body, and the path
and label a source's journal records. So the step settles once, its alert is queued, and its run stays
readable. A reader then sees `\u0000` where the NUL was, the same six characters a string that held
them all along reads back as. A column with a length keeps what fits of the escaped text.

**Checking a body leaves the worker running.** `validate.schema` evaluates off the event loop, so
the step's timeout and the lease heartbeat keep running over a value of any size, and
`uniqueItems` costs time in step with the array. Two limits remain. A thread cannot be stopped, so
an evaluation that passed its timeout finishes in the background: `unevaluatedItems` and
`unevaluatedProperties` still grow with the square of the value, about a minute for an array at
the default 1 MiB cap. And a regular expression holds the interpreter's lock, so a `pattern`,
`patternProperties` or `propertyNames` pattern that backtracks without end, over a string the
caller chose, holds the whole worker: an author who feeds a public source to a schema writes
patterns that cannot.

**A reply cannot act on the origin it shares with the UI.** An endpoint's reply is served on the
UI's origin, so it answers with `X-Content-Type-Options: nosniff` and
`Content-Security-Policy: sandbox; default-src 'none'; frame-ancestors 'none'` whatever it
rendered. A `text/html` reply is displayed but runs no script, and has no access to the
instance's cookies or storage. A reply may not set `set-cookie`, `www-authenticate`, `refresh`,
`clear-site-data`, `content-security-policy`, `x-content-type-options`, `x-frame-options`,
`strict-transport-security`, `cross-origin-*`, or what a proxy acts on (`x-accel-*`,
`x-sendfile`), among others. That is refused at apply (`source.reply_bad_header`) and again when
the reply renders, where a value a reference resolved to that holds a line break is refused too
(`run.reply_refused`). `location`, `content-disposition` and `access-control-*` remain the
pipeline's to set, so a reply can redirect, name a download or answer a browser caller.

**A failed step's text stays on the run.** A held caller whose run fails before a reply answers is
told the run and the step, and nothing the step said: that text can hold the artifact root, an
internal address or a query value, and a caller may have no right to read the run. A reply can
still put a step's error in its own body, as the author chooses.

**An open stream answers to its credential.** A run's log tail and event stream read the token or
session they were opened with on every poll, in the transaction that reads what goes out. Once it
is revoked, expired or its account deactivated, the next poll sends nothing more and ends the
stream with `expired`, so a client reopening is refused like any new request. A quiet stream polls
every five seconds at the slowest, which is the longest that takes.

**A route is one source's.** Two sources answering one method at one template are refused at
apply, across pipelines, and a unique constraint holds it when two applies race.

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

A document's author can often write the files beside it too, so a `.env`, `dirigent.yaml` or
`.dirigent/dirigent.yaml` in the working directory cannot set the allowlist. It comes from the
process environment, the file `DIRIGENT_CONFIG_FILE` names, or
`~/.config/dirigent/dirigent.yaml`. A deployment that runs `dg server` from a directory holding
its configuration names that file with `DIRIGENT_CONFIG_FILE`.

The same files cannot set any other setting that reaches past the checkout. A hostile
`database_url` would hand the instance's state to another server, `artifact_root` and `work_root`
would read and write outside the project, `host` would publish a local instance, `ui_dir` would
serve a page on the instance's origin, `secret_key_file` would read any file this user can, and
`retention_*`, `apply_dir` and `apply_prune` would rewrite a database the host named. The
[settings reference](settings.md) marks each of these host only. A project's `pipelines` directory
has to be inside the project, and `dg apply` refuses a document that is a link to a file outside it.

A checkout cannot choose where a secret you type goes either. `dg auth login`, `dg auth password`,
`dg admin user password`, `dg connection create` and `dg source set-secret` refuse a server a project's
`.dirigent/profiles.yaml` or `.env` names off this host, before they ask for anything or send
anything, unless you named it yourself with `--url` or the shell's `DG_URL`. A server on this host is
not affected, which is what a scaffolded project names.

A checkout cannot supply the state either. The default database is `.dirigent/state/dirigent.db`
under the working directory, and a state that arrived with a clone could hold queued runs, which
would execute on `dg dev` if the shell allowlists their blocks. So before opening or deleting any
SQLite database in a directory spelled `.dirigent/state`, dirigent refuses it when:

- `.dirigent` or `state` is a symbolic link, or either belongs to another user;
- `state` can be written by group or others, or `.dirigent` by others;
- anything directly inside `state` is a link, a special file, or another user's;
- the enclosing git repository tracks anything under it, including under another case's or another
  Unicode normalisation's spelling of the path, both of which a filesystem may open as the same one.

A clone's files are the user's own with ordinary modes, so the last check is what stops a
committed database. git is not run to make it: a repository's own configuration can start programs,
so the index is read as bytes, which starts nothing. An index that cannot be read refuses the state.
Each file check is made on a descriptor reached without following a link. dirigent creates the
directory with mode `0700`. A database opened by SQLite is opened by path, so a process already
running as this user could still swap the file between the check and the open.

`dg dev --wipe-state` deletes through a descriptor as well, and refuses the same links, another
user's directory and a tracked state, leaving the files in place. It does clear a state that is
only too open, and links inside the directory are removed rather than followed.

This covers a state delivered by git. A tar or zip archive carries no index, so a database
unpacked from one looks exactly like one this user made and is opened: do not run `dg dev` in an
unpacked tree you do not trust, or pass `--wipe-state` the first time. A host that names a database
anywhere else, through the environment or `DIRIGENT_CONFIG_FILE`, has chosen it, and these checks
do not apply.

**All of this protects a separately installed `dg`, and only that.** `uv run dg`, and anything else
that resolves `dg` from the project, runs the checkout's own `pyproject.toml` first: its dependencies
and its build backend are code the checkout chose, and they have run before dirigent reads a single
setting. In a checkout you do not trust, run a `dg` installed outside it, such as with
`uv tool install dirigent-cli`.

The gate is enforced **twice**: when a run is created, and again when a worker claims the
step. Two checks rather than one, so that tightening the configuration stops work that was
already queued.

`dg run --local --enable-unsafe shell.run` adds to the allowlist for exactly one command. It
never turns the gate off, and it does not affect a server.

`docker.run` deserves its own sentence. Its containers default to `network: none`, because an
image a stored pipeline named should not reach the worker's network unless the step says so.
Allowlisting `docker.run` is a decision about the host, not about a pipeline.

The privileged dind sidecar in `infra/compose.yaml` does not change that. Allowlisting a `docker.*`
block grants root-equivalent control of that daemon and everything mounted in it, including every
run's working files on that worker, and a privileged container inside a privileged sidecar is one
step from the host's kernel. `docker.compose.up` passes on whatever a document's services ask for.
The stack keeps the daemon on a network it shares with the worker alone, so the database and the
artifact bucket have no name a container can resolve. That narrows what is easy to reach and is
not a firewall. Their addresses do not route on the Linux runner CI measures and do route on Docker
Desktop, as [measured here](docker.md#the-reference-shape-a-dind-sidecar), and it does not contain a
pipeline that has taken over the sidecar. **Run these blocks on a dedicated worker host, tagged
`--tag docker`**, with `requires.workers: [docker]` on the pipelines that use them. See
[what allowlisting these blocks grants](docker.md#what-allowlisting-these-blocks-grants).

A `docker` connection carries the two docker credentials there are, and both are sealed: the
client TLS key that reaches a remote daemon, and the registry password a `docker.build` pushes
with. Sealed means encrypted at rest, redacted in every API response, and never an argument or
an inherited variable. Each reaches the CLI only as a 0600 file in a 0700 directory in the
system's temporary directory, outside the roots a sibling step can read -- the key as
`DOCKER_CERT_PATH`, the login as a `DOCKER_CONFIG` of its own -- and both directories are removed when the step leaves, whether it succeeded, failed or was
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
than the worker's process, and the process a program runs in starts with `PATH`, `LANG`,
`LC_ALL` and `TZ` and nothing else from the worker's environment, so a way past the shadow finds
no secret behind it. An engine that runs behind no allowlist must not be a way around one.

`shell.run` additionally passes only `PATH`, `LANG`, `LC_ALL`, and `TZ` plus whatever the
allowlist names -- never the worker's environment wholesale -- and gets a working directory
of its own under the run's work directory that it cannot climb out of.

It also gets a deadline it cannot outlive, and neither can anything it starts. The command
runs in a session of its own, and that whole session is killed when the block's own timeout
expires, when the engine's step timeout cancels the attempt, and on any other way out of the
block. A command is usually `sh -c`, so killing only the process that was started would
leave the children doing the work still running.

### What an allowlisted command can still reach

The denial above and the built environment stop a step from being *handed* a secret. They are
not a boundary against a command that goes looking, and allowlisting `shell.run` means allowing
that. A command runs as the worker's user, so it can do what that user can do.

What holds, and what it covers:

- **Every block's child process starts from an explicit environment.** `shell.run`,
  `docker.compose.*`, `docker.build` and `git.checkout` build one from `PATH`, `LANG`, `LC_ALL`,
  `TZ` and what the step names, and a `docker.run` container gets only what its step names. A
  secret is not in what they inherit.
- **The program holding a docker connection's secrets is the host's choice.** `docker.compose.*` and
  `docker.build` hand a connection's TLS key and registry password to the `docker` on the worker's own
  `PATH`, with its config in a private directory. A document cannot name another program, set a
  variable that steers it (`PATH`, `HOME`, `DOCKER_CONFIG` and the like, listed in
  [docker.md](docker.md#files-live-in-the-runs-work-directory)), or plant a plugin or credential helper in the work
  directory. `git.checkout` takes no such field and no `env`, and `shell.run` holds no connection.
- **`dg worker` and `dg dev` take `DIRIGENT_SECRET_KEY` out of `os.environ` at start-up.** That
  covers what `os.environ` reaches: a subprocess a plugin starts without naming an environment,
  and a library reading a variable.
- **On Linux, `dg worker`, `dg dev`, `dg server` and `dg scheduler` clear their dumpable flag at
  start-up.** The kernel keeps the environment a process started with in `/proc/<pid>/environ`,
  and removing a variable from `os.environ` does not change it. With the flag cleared, a process of
  the same user cannot open that file, or `mem`, `maps` or `fd` beside it, and cannot attach with
  ptrace, so `cat /proc/$PPID/environ` in a command gets `Permission denied`. That covers
  `DIRIGENT_DATABASE_URL` and everything else the process was started with, not only the key. Each
  process pays for it: it writes no core dump, and a debugger or `py-spy` of the same user cannot
  attach, so use root for that. It does nothing on other platforms, where no such file exists.

What does not hold:

- **Whatever started the process still holds the same environment.** A shell, `uv run` or a
  supervisor that stays alive above the worker keeps its own `/proc/<pid>/environ`, which any
  process of the user can read. So exec the worker or start it from a clean environment; the image
  does, because `dg` is the entrypoint. `dg server --reload` loses the flag in the process it
  reloads, and that is a development mode.
- **Root reads it all the same.** A worker running as root on a host starts commands that hold
  `CAP_SYS_PTRACE`, which passes the check. A container's default capabilities leave that one out.
- **A key file only moves the problem.** `DIRIGENT_SECRET_KEY_FILE` keeps the key out of
  `/proc/<pid>/environ` altogether, so prefer it, and it is what makes a leaked environment dump
  harmless. But a command running as the worker's user can open the same file the worker did,
  unless the deployment removes it or takes it away from that user after start-up.

**So treat a worker that may run `shell.run` as holding the instance's key.** Where that matters,
run those steps on a dedicated worker with its own `--tag`, on a host that holds nothing else, and
declare `requires.workers` on the pipelines that use them. An instance with no key configured
still starts, so a worker whose steps open no connection can be started without one; a stack
whose artifact root resolves through a sealed connection cannot, because every worker opens it.

### A document whose aliases expand

A document is YAML, and a few hundred bytes of aliases nested inside each other expand to billions
of values wherever the document is written out: a digest, an export, a request. So a document is
measured before it is built, at every door that reads one, and refused when its aliases would add
more than 100,000 values or 16 MiB of text, contain themselves, or nest past what Python's stack
holds. An alias used to repeat a block of config is nowhere near that. The same bound holds the
YAML `convert.std` reads.

### A reference in a shell string

`shell.run` and `docker.run` take a command as a shell string, and a `${...}` in one never
becomes shell source. The engine rewrites each reference to a variable it invents and sets that
variable in the command's environment, so what a webhook payload carries is text the shell
expands and does not parse.

Quoting decides whether the value stays one word, so the engine reads the command as a shell would:
quotes, comments, here-documents, substitutions and parameter expansions. Inside double quotes or a
here-document the variable takes no quotes of its own, and anywhere else it takes a pair. Inside
single quotes a shell keeps the text, so a command gets `"$DIRIGENT_V0"` there rather than the value,
which is still safe if a shell it starts reads that text later.

**A command the engine cannot read to its end is refused** when it holds a reference, at apply
(`document.step_shell_unreadable`) and when the step starts (`reference.shell_unreadable`), because
where the value lands in it is not known. That is a quote, substitution, `[[` or here-document never
closed, a here-document delimiter holding a reference, a bare `\${x}`, or `$'..\'..'`, which bash
and dash close in different places. A command with no reference is never read.

Bash also evaluates a value as an arithmetic expression in several places, and a subscript in that
expression runs a command substitution: `a[$(id)]` runs `id`. So in each of these a reference must
resolve to an integer, and anything else fails the step as `rejected` before the command starts:

- `$(( ))`, `(( ))` and `$[ ]`
- the operands of `[[ -eq ]]`, `-ne`, `-lt`, `-le`, `-gt`, `-ge`, and of `[[ -v ]]`. Another clause
  of the same `[[ ]]` is not held to it, and neither is a numeric comparison in `[ ]` or `test`,
  which does not evaluate.
- the operand of `-v` to `[`, `test` or `printf`, and a name `read` assigns to
- `let` and `unset`, in any word
- `declare`, `typeset`, `local`, `readonly` and `export`, in the word's name, so `export X=${v}` takes
  any value and `export ${v}=1` does not
- anywhere in a command that declares an integer variable, with `declare -i` or the like, because a
  later assignment to it evaluates, or a nameref, with `declare -n`, because reading it does. So one
  such line holds every reference in that command.
- an indexed array's subscript, as `a[${v}]=1`, `a[${v}]+=1` or `${a[${v}]}`, or a compound
  assignment's, as `a=([${v}]=1)`. An array the same command declares with `declare -A` is not held
  to it in the first form, and neither is `echo a[${v}]`, which is a glob.
- a declaration whose compound assignment is one quoted word, as `declare -a "a=(${v})"`, which bash
  parses again. `declare -a a=("${v}")` is not held to it.
- `${var:offset}` and `${var:offset:length}`, but not `${var:-default}` and its kin

Declare the parameter as `type: integer` and a caller's bad value is refused at the door instead. A
step that needs another value there uses `argv`, which involves no shell.

`$(( ))`, `(( ))` and `$[ ]` are also looked for with no regard to quoting, so nothing the reader gets
wrong can hide one. That reads a literal opener as one too: after `'$(( '`, in a comment or in a
program another tool reads, a reference must be an integer until the opener closes. So must one
inside a `$( )` within any of the places above, because the shell evaluates what that prints.

`let`, `unset`, `[[`, `-v`, `read`, the `-i` and `-n` declarations and `=(` are looked for the same
way, on the word that starts each stretch of a command between one `;`, `&`, `|`, `(`, backquote or
newline and the next, once any keyword, assignment, redirection, function header and case pattern is
passed over. So `f() { let x=${v}; }` and `2>/dev/null let x=${v}` are held, `echo let ${v}` and
`echo "let me ${v}"` are not, and `echo "a; let me ${v}"` is, at the cost of a text that only
reads like a command.

What the check does not cover is a command that hands a value on: the author's own variable to
arithmetic, `eval`, `read`, `printf -v`, `getopts` or `${!var}`, a value read from `env`, and a program
in single quotes given to `bash -c`, none of which is read from the command text. Where the value came
from a caller and a step needs one of those, use `argv`, which involves no shell, or hold the value to
a schema first.

### A reference in a program

The same rule holds for what a step hands to another language. A value reaches SQL as a bound
parameter and never as text (see [SQL](sql.md)). In a jq program a reference is bound to a jq
variable, so `.tenant == "${params.t}"` compares against the value however it is quoted, and a
program that is only a reference is refused. In a `report.render` template a reference is refused at
apply and at the start of the step, because `values` is how a template reads anything. So it is in
the inline `content` of `docker.compose.up` and `docker.compose.down`, because a value spliced into
YAML can add `privileged`, a volume or a command: the file writes `$${NAME}`, which compose
interpolates, and `env` carries the value under `NAME`, where it stays one value whatever it holds. A
template or a program that means the literal text writes `$${...}`.

## Secrets lifecycle

A connection's secret fields never sit in a readable column. The mechanism is envelope
encryption, split by field rather than by blob: a connection kind declares which of its fields
are secret by typing them `SecretStr`, the public settings stay as queryable JSON on the row,
and only the secret fields go into a Fernet-sealed envelope. The same declaration that makes
the API redact a field is what makes the engine encrypt it, so the two cannot drift apart.

A secret field given an empty value is stored unset rather than sealed, whichever way the row
was written: an empty string is nobody's credential, and sealing one would leave a field that
every read afterwards reports as set. A required secret given empty is refused.

Each envelope is stamped with a short, non-reversible **key id** (the first twelve hex
characters of the key's own SHA-256), so an instance can tell which key sealed a row without
trying to decrypt it -- and so a failure to open one says "sealed by key `abc123…`" rather than
"decryption failed".

**Decryption happens on the worker path alone**, at the moment a block asks the step context
for its connection. It does not happen when a connection is listed, shown, or applied.

### Where the key comes from

`DIRIGENT_SECRET_KEY` or `DIRIGENT_SECRET_KEY_FILE`, and nothing else; naming both is refused at
start-up. Per twelve-factor, the key is configuration in the environment: an environment
variable, a line in the `.env` of the directory the process runs in, or a value in the
`dirigent.yaml` it reads at boot, in that order of precedence. `DIRIGENT_SECRET_KEY_FILE` names a
file holding it instead, such as a mounted secret under `/run/secrets`, read once at start-up.
**Dirigent assumes no secret manager.** There is no KMS integration, no Vault client, no
key-fetch hook. If your platform provides secrets, its job is to put this variable or that file
in place before dirigent starts; dirigent does not reach out for it.

A working directory's `.env` is read literally, so a `${VAR}` in it stays those characters and
cannot copy a value out of the environment. It is read only when it is a regular file, not a
symbolic link, that this user owns and neither group nor others may write.

`dg init --template local` writes a generated key into the project's `.env`, which that
project's `.gitignore` keeps out of the repository and whose mode is owner-only, so a local
instance seals credentials from its first command with nothing exported. A stack keeps its key
the other way round: it is in the `.env` compose reads, and compose passes it into each
container's environment.

The value has to be a Fernet key, 32 random bytes in url-safe base64, which is what
`dg secret-key` mints:

```bash
dg secret-key
```

Anything else, a passphrase included, is refused when the process starts, and the refusal does
not repeat the value. A passphrase has far less entropy than a key, and anyone holding a database
backup could test guesses against the envelopes offline. The command writes that key and nothing
else, on one plain line at a terminal and in a pipe alike, so `DIRIGENT_SECRET_KEY=$(dg secret-key)`
works in a shell and in a `.env`.

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
   list`, and `dg connection show CODE` for each). The secrets are not readable; you need them
   from wherever you actually keep them.
2. Stop the writers, or accept a window in which runs needing a credential fail.
3. Set the new `DIRIGENT_SECRET_KEY` on every process.
4. Re-enter each connection's secret fields, which seals them with the new key. The CLI has no
   update command, so this is `PATCH /api/v1/connections/{code}`, in place. A connection nothing
   uses can be deleted with `dg connection delete CODE` and made again with `dg connection create
   KIND CODE --set field=value` instead; one that a pipeline, an alert rule or a storage scheme
   names is refused the delete.
5. Run `dg connection check CODE` for each, which is the one command that actually opens an
   envelope and uses what is inside it.

The same applies to a signed endpoint source's secret, which is sealed with the same key.
Re-entering it is `dg source set-secret PIPELINE SOURCE --secret ...` with the secret its
senders already hold, or `dg source rotate-token`, which mints a new one every sender then has
to be given.

Treat losing the key as losing the credentials. Back it up somewhere that is not the database
backup, because a backup containing both the envelopes and the key that opens them is not an
encrypted backup.

### Where secrets are not

Marked-secret fields are redacted as `***` in every API response, and they never appear in a
pipeline definition, an export, or a process log. No route carries a credential in its path,
so a log line or an OpenTelemetry span name never holds one. A secret field that is not set reads as `null`, not as
`***`: the marker means a credential is stored.

A step or a source that names a connection of another kind than it reads is refused with
`run.connection_wrong_kind`, naming the connection and both kinds and opening nothing. A stored
connection that does not validate against the configuration it was read for fails with
`secret.connection_unreadable`, which names each field and the kind of error and no value, so
neither failure writes a secret into a run's attempts, its logs, a source's `last_error`, or a
process log.

A connection's `bearer_token` or `api_token` holding a control character, or a blank at either
end, is refused when it is stored (`secret.not_sendable`, 422), because no HTTP header can carry
it and the HTTP library refuses it by quoting the whole header. Whatever such a value already
stored, or any other secret, makes a library say is scrubbed by what writes it down: a connection
check's detail, a notification's error, a step's failure and log, and a source's `last_error` hold
`***` in its place. Rows written before this are not rewritten, so a token that reached them is
rotated.

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

**The endpoints.** Everything under `/endpoints` is a pipeline's endpoint sources, deliberately
outside `/api/v1`. If callers are outside your network and operators are inside, that split is
your seam: a proxy can publish `/endpoints/*` to the internet and keep `/api/v1/*` on the
internal side, with no change to dirigent. Note that this only works because the split is
structural. Do not invert it -- publishing `/api/v1` and firewalling `/endpoints` gets you
nothing, since `/api/v1` is the surface that holds the credentials.

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
  every log, and create schedules on anything.
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
  is off by default in any case. The one exception is a connection that sets
  `follow_redirects_with_auth`: its `base_url` is followed once, without the credential, and
  every request then goes, credential and all, to wherever it landed. Set it only on a
  `base_url` whose redirect you trust, such as `https://play.dhis2.org/2.43`.

  Nor can a step: a connection's credentials and headers go only to its own origin, the
  scheme, host and port of its `base_url`. `http.request`, `http.ready` and `webhook.post`
  refuse a literal absolute `url` or `path` beside a `connection` at apply
  (`http.url_beside_connection`), and refuse one a reference resolves to at run time unless it
  is on that origin (`http.off_origin`), before anything is sent. A step whose config still
  holds a reference is not checked at apply, so its literal URL is refused at run time the same
  way. A `Host` header a step sets beside a `connection` is held to that origin too, at run
  time and before anything is sent (`http.host_off_origin`), because a front that routes on
  `Host` would otherwise hand the credential to another name it serves. The headers such a front
  may read instead, `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto` and the others in that
  family, are refused beside a `connection` the same way (`http.routing_header_refused`), whatever
  their value and however they are spelled. An absolute link the
  service itself hands back, such as a next page on the same origin, is still followed. A step that calls another service names no connection and gives the `url`.
- **Rate limiting on the authenticated API.** Only login and endpoint sources are limited.
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
