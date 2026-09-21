# dirigent-block-jq

The jq engine for the transform verbs: `transform.jq` reshapes a whole value with a jq
program, `map.jq` replaces every element of a list with what a program makes of it, and
`filter.jq` keeps the elements a program answers true for.

A jq program is evaluated in a child process rather than in the worker, because jq holds the
GIL for as long as a program runs and there is no way to interrupt one. The runner that child
starts is a module of this package, run by path so it costs jq and the standard library to
start.
