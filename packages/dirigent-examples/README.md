# dirigent-examples

The dirigent example corpus as an installed distribution: 22 topic shelves of runnable
`dirigent/v1` documents, contributed to a host through the `examples()` extension point and
read by `dg examples`, `dg pipeline new`, and the instance's Examples screen.

The shelves are the repository's `examples/` directory; the root path is a symlink to the
real files here, so every `dg run --local examples/...` line keeps working in a checkout.
[`shelves/README.md`](src/dirigent_examples/shelves/README.md) is the corpus's own guide: the
shelves, the tag vocabulary, and what each document needs to run.
