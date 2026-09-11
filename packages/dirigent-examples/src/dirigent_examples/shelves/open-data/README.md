# Open data

Real pipelines against real public systems. Every source on this shelf is a live, public API,
and every one of them but two is keyless: no account, no token, no registration, nothing to
stand up. `dg run --local examples/open-data/<file>.yaml` reaches the internet and comes back
with today's data.

The two exceptions say so in their headers and in the table below. `kobo-submissions-to-csv`
needs an account token, because the submissions are somebody's household survey and there is no
anonymous read; `odk-central-submissions` needs a server and an account for the same reason.
They are here because a shelf of only-open sources would never show where a credential belongs
-- in a connection the instance holds, not in the document.

That distinction is what "it runs" means on each row. Every keyless document here has been run
end to end against its live source and ended `succeeded` with real data;
`gdacs-disaster-updates` was run twice under one `dg run --local --root`, a day apart, to see
both the empty first day and the second day's difference. The two credentialed ones stop where the credential does: their
documents validate and their graphs are the same shape, but nobody's Kobo token or ODK Central
server is in this repository, so the request itself is what a reader has to supply.

Nothing here uses a block outside the core catalog, and nothing runs code on a worker: no
`shell.run`, no allowlist entry, no `--enable-unsafe`. Reshaping is jq, encoding is a codec,
waiting is a sensor.

| File | What it teaches |
| --- | --- |
| [open-meteo-weekly-report.yaml](open-meteo-weekly-report.yaml) | A windowed weekly schedule, a columnar API transposed to rows, and csv written under the window's start |
| [who-gho-indicators-to-parquet.yaml](who-gho-indicators-to-parquet.yaml) | A fan-out read back as one list, flattened into one table, written as one parquet file, and a manifest that counts what landed |
| [world-bank-population-trend.yaml](world-bank-population-trend.yaml) | Paging made visible: an envelope checked with `error()`, year-on-year arithmetic in jq, and a carried schema gating the rows |
| [usgs-earthquakes-alert.yaml](usgs-earthquakes-alert.yaml) | Haversine in jq, thresholds carried as data rather than spliced into a program, and posting **only** when something matched |
| [overpass-health-facilities.yaml](overpass-health-facilities.yaml) | A query language in a query parameter, nodes and ways reconciled to one shape, and the same rows written as csv and as parquet |
| [wikidata-country-reference.yaml](wikidata-country-reference.yaml) | SPARQL with content negotiation, the W3C results envelope unwrapped, and a reference table saved for other pipelines to read |
| [gdacs-disaster-updates.yaml](gdacs-disaster-updates.yaml) | A daily window, deduplication against yesterday's saved list, and what the first day looks like when there is no yesterday |
| [hdx-dataset-watch.yaml](hdx-dataset-watch.yaml) | The marker pattern: storage standing in for state, and a marker overwritten under `rule: all_done`, whichever way the comparison went |
| [github-releases-relay.yaml](github-releases-relay.yaml) | A rate limit as a design constraint, string comparison of ISO stamps, and the remaining budget recorded beside the result |
| [nominatim-geocode-facilities.yaml](nominatim-geocode-facilities.yaml) | One request per second expressed as the shape of the graph: a chain with `time.sleep` between the lookups, not a fan-out |
| [kobo-submissions-to-csv.yaml](kobo-submissions-to-csv.yaml) | Where a credential belongs, and why a csv needs its columns named up front |
| [odk-central-submissions.yaml](odk-central-submissions.yaml) | The same survey story with the secret in a connection, and an OData feed with grouped questions |
| [feeds-composition.yaml](feeds-composition.yaml) | `pipeline.run` over two of the above: parameters down, statuses up, and data across only through storage |

## The two patterns worth stealing

**Do nothing, successfully.** There is no `if` in the format and no conditional edge. What there
is: a decision written to storage as ndjson, and `storage.exists` asked for it with
`min_size: 1b` and `on_timeout: skip`. An empty decision encodes as an empty file, the floor is
never met, the sensor skips, and every step behind it skips with it -- while the run still ends
`succeeded`. `usgs-earthquakes-alert.yaml`, `hdx-dataset-watch.yaml` and
`github-releases-relay.yaml` each use it, and each says why at the step.

**Remember, without a state block.** Nothing carries over between runs except what a run wrote.
A marker is a small object at a stable path: a sensor asks whether it is there, a transform
reads it, the comparison decides, and the last step overwrites it under `rule: all_done`.
`hdx-dataset-watch.yaml` is the whole pattern in one file. Under `--local` the artifact root is
a throwaway directory, so every local run is a first sighting; on an instance, a stable prefix
or an `s3://` bucket is what makes the second run the interesting one.

## Two things the reference language will not do

A `${...}` reference reads `params`, `steps.<name>.output.<path>`, `item`, and `run` --
`run.scratch`, `run.id`, `run.window.start`, `run.window.end`. Two consequences show up
repeatedly on this shelf:

- **A parameter default is literal text.** `default: ${run.scratch}/marker.json` is those
  characters, not a path. Anything that has to resolve belongs in a step's config.
- **A jq program never has a value spliced into it.** Data reaches a program through `input`,
  which is why the earthquake filter carries its thresholds on every row it tests and the
  briefing puts the country in its input rather than in its program.
