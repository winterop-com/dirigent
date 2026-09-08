# Security policy

## Reporting a vulnerability

Report privately through [GitHub's private vulnerability
reporting](https://github.com/winterop-com/dirigent/security/advisories/new). That opens a
draft advisory only the maintainers and you can see.

Please do not open a public issue for a vulnerability, and please do not report one by pull
request: a fix in the open describes the hole before anyone can upgrade.

What helps, in rough order of usefulness: what an attacker gets, the smallest sequence that
demonstrates it, the version or commit, and whether it needs an authenticated principal and
which role.

You should get an acknowledgement within a week. If you do not, assume it went astray and
say so on the advisory rather than assuming it was ignored.

## Supported versions

Nothing has been released yet. Until 1.0.0, the supported version is the `main` branch, and
a fix lands there rather than in a backport.

## What is in scope

The engine, the API and its authentication, the CLI, the client, and the standard blocks --
anything in `packages/`.

Two things are deliberately dangerous and are not vulnerabilities on their own:

- **`shell.run` and `docker.run` execute code on a worker.** They are refused unless the
  instance names them in `DIRIGENT_ENABLED_UNSAFE_BLOCKS`. That an operator who enables them
  can run code is the feature. A way to reach them *without* the allowlist is a
  vulnerability.
- **A pipeline can call any URL its worker can reach.** There is no egress allowlist, and
  [the security page](docs/security.md) says so. A way to make a worker call something the
  document did not name is a vulnerability.

## What is known and unfixed

[The security page](docs/security.md) keeps the current list of gaps, with what each one
does and does not protect. A report about something already listed there is still welcome --
it tells us it matters to somebody -- but it will be treated as a known gap rather than an
advisory.
