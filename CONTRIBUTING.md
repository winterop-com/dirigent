# Contributing

Issues are welcome: a bug report, a question, or a proposal.

Dirigent is source-available rather than open source. Under [its licence](LICENSE) a
contribution can only be accepted with the copyright holder's agreement, so open an issue and
get that agreement there before writing a patch.

## A change

- `make install` once, then `make check` before every push: it runs the static gate, the UI's,
  and the tests.
- Every change ships with its test, and a test asserts on records rather than rendered text.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`).
- No attribution, co-author or generated-by lines in commits or pull requests.
- Open the pull request as a draft, and mark it ready when it is.
