# dirigent-block-transform

The transform block family: `transform.jq`, `map.jq` and `filter.jq` reshape a value with a jq
program, and `convert.std` trades between json, ndjson, csv, yaml and xml on the standard
library.

A jq program is evaluated in a child process rather than in the worker, because jq holds the
GIL for as long as a program runs and there is no way to interrupt one. The runner that child
starts is a module of this package, run by path so it costs jq and the standard library to
start.
