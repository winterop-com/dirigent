# dirigent-block-base

The base block family: what a pipeline needs whatever it integrates with. `log.write` puts a
line in the run's log, `report.render` renders text from a template, `validate.schema` holds a
value to a JSON Schema, `value.const` emits a fixed value, `pipeline.run` starts another
pipeline and waits for it, and the `time.sleep` and `time.window` sensors park an attempt
until a moment arrives.

It also contributes the `log` notifier, the one alert channel with no connection kind beside
it: there is no credential to mint, and an instance with nothing configured still says
something when a rule fires.
