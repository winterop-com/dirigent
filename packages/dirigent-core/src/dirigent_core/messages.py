"""Every refusal the core makes, catalogued: one catalogue per area, one message per refusal.

A code is stable API. The text is English and may be reworded; the code and the params it
renders are what another language, a log reader and a test all hold on to.
"""

from dirigent_common import Catalogue, Message

DATABASE = Catalogue("database")

# What the settings refuse at validation. Pydantic owns the code a validator's refusal
# reaches the wire under, so this is rendered into the ``ValueError`` it wraps.

POOL_TOO_SMALL = DATABASE.define(
    "pool_too_small",
    "database_pool_size ({size}) plus database_max_overflow ({overflow}) is {ceiling} connections, "
    "and a worker at worker_concurrency={concurrency} needs at least {needed} (one per in-flight "
    "call, plus {headroom} for the heartbeat, the sweeper and the alert loop). Raise the pool or "
    "lower the concurrency.",
)

SCHEMA_STALE = DATABASE.define(
    "schema_stale",
    "the database at {where} was written by a different dirigent, first {first}; before 1.0 the "
    "schema is not migrated, so this instance needs an empty state to start from, or a database "
    "this version created",
)

AUTH = Catalogue("auth")

WEAK_PASSWORD = AUTH.define("weak_password", "a password must be at least {minimum} characters")

DUPLICATE_USER = AUTH.define("duplicate_user", "a user named {username} already exists")

DUPLICATE_EMAIL = AUTH.define("duplicate_email", "a user with the email {email} already exists")

LAST_ADMIN = AUTH.define(
    "last_admin",
    "{username} is the only active admin; promote another account before changing this one",
)

WRONG_PASSWORD = AUTH.define("wrong_password", "the current password is not correct")

PIPELINE = Catalogue("pipeline")

UNKNOWN_PIPELINE = PIPELINE.define("unknown", "no pipeline coded {code}")

PIPELINE_IN_USE = PIPELINE.define(
    "in_use",
    "pipeline {code} has runs still in flight ({runs}) and cannot be deleted; finish or cancel them first",
)

PIPELINE_DEACTIVATED = PIPELINE.define("deactivated", "pipeline {code} is deactivated")

PIPELINE_NO_VERSIONS = PIPELINE.define("no_versions", "pipeline {code} has no versions yet")

PIPELINE_NO_SUCH_VERSION = PIPELINE.define("no_such_version", "pipeline {code} has no version {version}")

SECRET = Catalogue("secret")

SECRET_KEY_MISSING = SECRET.define(
    "key_missing",
    "no secret key is configured: DIRIGENT_SECRET_KEY must hold one before a connection secret can be stored or read",
)

EMPTY_SECRET = SECRET.define("empty", "{fields} cannot be stored empty: a required secret needs a value")

SECRET_KEY_MISMATCH = SECRET.define(
    "key_mismatch",
    "the configured DIRIGENT_SECRET_KEY cannot open this envelope{sealed_by}: "
    "either the key changed or the row belongs to another instance",
)

ARTIFACTS = Catalogue("artifacts")

NOT_A_URI = ARTIFACTS.define("not_a_uri", "{uri} is not a URI: it names no scheme")

UNKNOWN_SCHEME = ARTIFACTS.define(
    "unknown_scheme",
    "no storage backend registered for scheme {scheme}; registered schemes: {registered}",
)

OUTSIDE_ROOT = ARTIFACTS.define(
    "outside_root",
    "{uri} resolves outside the artifact root {root}; write ${{artifacts}}/<path> for an object "
    "kept under this instance's root, or ${{run.scratch}}/<path> for one swept with the run",
)

UNKNOWN_STORAGE_CONNECTION = ARTIFACTS.define(
    "unknown_connection",
    "no connection coded {ref} to configure the {scheme} scheme from ({available})",
)

OBJECT_ALTERED = ARTIFACTS.define(
    "object_altered",
    "the object at {uri} is not what run {run} (attempt {attempt}) recorded when it wrote it: "
    "its size or digest differs, so something changed it after the write",
)

OBJECT_MISSING = ARTIFACTS.define(
    "object_missing",
    "there is nothing at {uri}: run {run} (attempt {attempt}) has an artifact row and storage "
    "has no object; restore the artifact root from the backup that matches this database, "
    "or prune the run",
)

HOST = Catalogue("host")

UNSUPPORTED_API_VERSION = HOST.define(
    "unsupported_api_version",
    "plugin {plugin} contributes api_version {api_version}; this host speaks {host_version}. "
    "Upgrade the plugin, or the host, so both agree.",
)

DUPLICATE_CONTRIBUTION = HOST.define(
    "duplicate_contribution",
    "{surface} {identifier} is contributed by both {first} and {second}. "
    "{surface_title}s are public API, so one of the two packages must be uninstalled or renamed.",
)

UNKNOWN_BLOCK = HOST.define(
    "unknown_block",
    "no block {block_id} is installed; the catalog has {catalog_size} blocks. "
    "Install the plugin package that contributes it.",
)

UNKNOWN_EXAMPLE = HOST.define("unknown_example", "no example {code} is installed.")

AMBIGUOUS_EXAMPLE = HOST.define(
    "ambiguous_example",
    "example {code} is carried by {plugins}; the code alone does not name one of them.",
)

SCHEMA = Catalogue("schema")

SCHEMA_NO_CODE = SCHEMA.define(
    "no_code",
    "this schema names no code: give one, or set $id, or store it from a file whose name is a code",
)

SCHEMA_INVALID = SCHEMA.define("invalid", "this is not a valid JSON Schema{at}: {detail}")

SCHEMA_IN_USE = SCHEMA.define(
    "in_use",
    "schema {code} cannot be removed while pipelines name it ({pipelines}); a pipeline must stop naming it first",
)

PARAMETER = Catalogue("parameter")

PARAMETER_INVALID = PARAMETER.define("invalid", "parameter {location} is invalid: {detail}")

PARAMETER_SCHEMA_INVALID = PARAMETER.define(
    "schema_invalid",
    "the pipeline's parameter schema is not itself valid JSON Schema ({problem}); apply a corrected document to fix it",
)

DOCUMENT = Catalogue("document")

NOT_YAML = DOCUMENT.define("not_yaml", "the document is not valid YAML or JSON: {detail}")

DOCUMENT_EMPTY = DOCUMENT.define("empty", "the document is empty")

NOT_A_MAPPING = DOCUMENT.define("not_a_mapping", "a document is a mapping, not {kind}")

DOCUMENT_UNSATISFIED = DOCUMENT.define("unsatisfied", "the document does not satisfy {format}")

WRONG_DOCUMENT_KIND = DOCUMENT.define(
    "wrong_kind",
    "this is a `kind: {kind}` document, and a pipeline document was wanted",
)

NO_FORMAT = DOCUMENT.define("no_format", "the document declares no format; add `format: {format}`")

WRONG_FORMAT = DOCUMENT.define(
    "wrong_format", "this instance reads {expected} documents, and this one declares {declared}"
)

UNKNOWN_DOCUMENT_KIND = DOCUMENT.define("unknown_kind", "{format} defines {known}, and this document declares {kind}")

# A message is rendered by the CLI, by the web UI and by any other client, so it states the
# fact and names no tool: the surface a person is on is what offers the way forward, and one
# that told them to leave it and type a command elsewhere would be a dead end in every surface
# but the one the command belongs to.
CARRIED_CONNECTIONS = DOCUMENT.define(
    "carried_connections",
    "this document carries its own connections ({named}), which an instance will not store: "
    "create them on the instance and let the document name them under requires.connections",
)

CARRIED_SCHEMAS = DOCUMENT.define(
    "carried_schemas",
    "this document carries its own schemas ({named}), which an instance will not store: "
    "create them on the instance and let the document name them under requires.schemas",
)

SCHEDULE_ONE_CLOCK = DOCUMENT.define(
    "schedule_one_clock",
    "schedule {code} must declare exactly one of cron, interval, or at ({named})",
)

TEMPLATE_REFUSED = DOCUMENT.define("template_refused", "{detail}")

TOO_MANY_TAGS = DOCUMENT.define(
    "too_many_tags", "a document declares at most {maximum} tags, and this one declares {counted}"
)

BAD_TAG = DOCUMENT.define(
    "bad_tag",
    "tags[{index}] {tag} is not a valid tag: a tag is lowercased, and what is left "
    "must be letters, digits and hyphens, start with a letter or digit, and be at most "
    "{maximum} characters",
)

DUPLICATE_TAG = DOCUMENT.define("duplicate_tag", "tags[{index}] {tag} is declared twice; a tag says one thing once")

SELF_DEPENDENCY = DOCUMENT.define("self_dependency", "step {step} depends on itself")

UNKNOWN_DEPENDENCY = DOCUMENT.define("unknown_dependency", "step {step} depends on unknown step {dependency}")

DUPLICATE_TRIGGER_CODES = DOCUMENT.define("duplicate_trigger_codes", "duplicate {label} codes: {codes}")

STEP_CYCLE = DOCUMENT.define("step_cycle", "the steps {steps} form a cycle")

WORKER_TAGS_MISSING = DOCUMENT.define(
    "worker_tags_missing",
    "no live worker carries {tags}; a run of this pipeline would wait until one does",
)

PARAMS_SCHEMA_INVALID = DOCUMENT.define(
    "params_schema_invalid",
    "the parameter schema is not itself valid JSON Schema{at}: {detail}",
)

CARRIED_SCHEMA_INVALID = DOCUMENT.define(
    "carried_schema_invalid",
    "the carried schema is not itself valid JSON Schema{at}: {detail}",
)

SCHEDULE_REFUSED = DOCUMENT.define("schedule_refused", "{detail}")

SCHEDULE_PARAMS_REFUSED = DOCUMENT.define("schedule_params_refused", "{detail}")

TARGET_PIPELINE_MISSING = DOCUMENT.define(
    "target_pipeline_missing",
    "no pipeline coded {code} exists on this instance; apply it before the document that schedules it",
)

TARGET_PIPELINE_INACTIVE = DOCUMENT.define(
    "target_pipeline_inactive",
    "the pipeline coded {code} is inactive; activate it before the document that schedules it",
)

REQUIRED_BLOCK_MISSING = DOCUMENT.define("required_block_missing", "block {block} is not installed on this instance")

REQUIRED_CONNECTION_MISSING = DOCUMENT.define(
    "required_connection_missing",
    "no connection coded {code} exists on this instance",
)

REQUIRED_PIPELINE_MISSING = DOCUMENT.define(
    "required_pipeline_missing",
    "no pipeline coded {code} exists on this instance; apply it before the document that runs it",
)

STORAGE_SCHEME_MISSING = DOCUMENT.define("storage_scheme_missing", "no storage backend claims {scheme} ({registered})")

REQUIRED_SCHEMA_MISSING = DOCUMENT.define(
    "required_schema_missing",
    "no schema coded {code} exists on this instance ({held})",
)

STEP_BLOCK_MISSING = DOCUMENT.define(
    "step_block_missing",
    "no block {block} is installed; install the plugin package that contributes it",
)

STEP_UNSAFE_BLOCK = DOCUMENT.define(
    "step_unsafe_block",
    "block {block} executes code on the worker and DIRIGENT_ENABLED_UNSAFE_BLOCKS "
    "does not name it (currently allowed: {permitted})",
)

STEP_CONFIG_INVALID = DOCUMENT.define("step_config_invalid", "{detail}")

STEP_CONNECTION_MISSING = DOCUMENT.define("step_connection_missing", "no connection coded {code} exists ({available})")

STEP_SCHEMA_MISSING = DOCUMENT.define("step_schema_missing", "no schema coded {code} exists ({available})")

# A run holds the bodies of the schemas its document names, read when it is created, so a
# code nothing can read until the run has started names no shape it could have held.
STEP_SCHEMA_INTERPOLATED = DOCUMENT.define(
    "step_schema_interpolated",
    "{code} is resolved once the run has started, and a schema is named by its code: a run "
    "takes the shapes its document names when it starts, so write the code this step checks against",
)

FOR_EACH_LITERAL = DOCUMENT.define(
    "for_each_literal",
    "for_each is a literal string, not a list: {for_each} maps over nothing. "
    "Write a list, or an interpolation such as ${{params.regions}}",
)

ADOPTION_ONE_FAILED = DOCUMENT.define(
    "adoption_one_failed",
    "a step that maps over another fan-out's items cannot use one_failed, which is ready "
    "before that fan-out has finished producing them",
)

TRIGGER_OWNED_ELSEWHERE = DOCUMENT.define(
    "trigger_owned_elsewhere",
    "{label} {code} on pipeline {pipeline} is declared by {owner}",
)

REFERENCE_NAMES_NOTHING = DOCUMENT.define("reference_names_nothing", "${{}} names nothing")

REFERENCE_UNDECLARED_PARAM = DOCUMENT.define(
    "reference_undeclared_param",
    "${{{reference}}} reads an undeclared parameter ({available})",
)

REFERENCE_NO_FAN_OUT = DOCUMENT.define(
    "reference_no_fan_out",
    "${{{reference}}} reads the fan-out item, but step {step} has no for_each",
)

REFERENCE_UNKNOWN_STEP = DOCUMENT.define(
    "reference_unknown_step",
    "${{{reference}}} names step {step}, which this pipeline does not have",
)

REFERENCE_NOT_UPSTREAM = DOCUMENT.define(
    "reference_not_upstream",
    "${{{reference}}} reads step {target}, which is not a prerequisite of {step}; add it to depends_on",
)

REFERENCE_GRID_IN_CONFIG = DOCUMENT.define(
    "reference_grid_in_config",
    "${{{reference}}} names the list step {target} maps over, which only for_each reads; "
    "inside config, read the matching item with ${{steps.{bare_target}.item.output.<field>}}",
)

REFERENCE_NOT_PAIRED = DOCUMENT.define(
    "reference_not_paired",
    "${{{reference}}} reads step {target}'s matching item, but {step} does not fan over "
    "{target}'s items; write for_each: ${{steps.{bare_target}.items}}",
)

REFERENCE_MALFORMED_ITEM = DOCUMENT.define(
    "reference_malformed_item",
    "${{{reference}}} is malformed: a matching item reads steps.<name>.item.output.<field>",
)

REFERENCE_MALFORMED_STEP = DOCUMENT.define(
    "reference_malformed_step",
    "${{{reference}}} is malformed: a step reference reads steps.<name>.output.<field>, "
    "steps.<name>.items, or steps.<name>.item.output.<field>",
)

REFERENCE_MALFORMED_RUN = DOCUMENT.define(
    "reference_malformed_run",
    "${{{reference}}} is malformed: run exposes only run.scratch, run.id, run.window.start and run.window.end",
)

REFERENCE_MALFORMED_ARTIFACTS = DOCUMENT.define(
    "reference_malformed_artifacts",
    "${{{reference}}} is malformed: artifacts is the storage root itself and has no fields; "
    "write ${{artifacts}}/<path>",
)

REFERENCE_UNKNOWN_NAMESPACE = DOCUMENT.define(
    "reference_unknown_namespace",
    "${{{reference}}} names {namespace}, which is not one of params, steps, item, run, artifacts",
)

FOR_EACH_STEP_REFERENCE = DOCUMENT.define(
    "for_each_step_reference",
    "${{{reference}}} is not a list for_each can map over: it reads an upstream step's output "
    "as ${{steps.<name>.output.<field>}}, or maps over another fan-out's grid when the whole "
    "value is ${{steps.<name>.items}}",
)

LATE_GRID_ONE_FAILED = DOCUMENT.define(
    "late_grid_one_failed",
    "a step whose for_each reads a step's output cannot use one_failed, which is ready before that output exists",
)

FOR_EACH_READS_ITEM = DOCUMENT.define(
    "for_each_reads_item",
    "${{{reference}}} reads the fan-out item, which does not exist yet inside for_each itself",
)

ADOPTED_NOT_FAN_OUT = DOCUMENT.define(
    "adopted_not_fan_out",
    "${{{reference}}} maps over step {target}'s items, but {target} has no for_each",
)

ADOPTED_NOT_UPSTREAM = DOCUMENT.define(
    "adopted_not_upstream",
    "${{{reference}}} maps over step {target}'s items, so {target} must be a direct "
    "prerequisite of {step}; add it to depends_on",
)

SCHEDULE = Catalogue("schedule")

SCHEDULE_EXACTLY_ONE_CLOCK = SCHEDULE.define(
    "exactly_one_clock",
    "a schedule declares exactly one of cron, interval, or at ({named})",
)

WHOLE_SECONDS = SCHEDULE.define(
    "whole_seconds",
    "an interval schedule fires every whole number of seconds, at least one, not every {seconds}s",
)

SCHEDULE_PARAMS = SCHEDULE.define("params", "{detail}")

UNKNOWN_TIMEZONE = SCHEDULE.define(
    "unknown_timezone",
    "{name} is not an IANA timezone this host knows (try 'UTC' or 'Europe/Oslo')",
)

BAD_CRON = SCHEDULE.define("bad_cron", "{expression} is not a cron expression: {detail}")

CRON_NO_FUTURE = SCHEDULE.define("cron_no_future", "{expression} names no future time")

NO_CRON = SCHEDULE.define("no_cron", "a cron schedule has no expression")

CRON_NO_TIME_AFTER = SCHEDULE.define("cron_no_time_after", "{cron} names no time after {after}: {detail}")

CRON_NO_TIME_BEFORE = SCHEDULE.define("cron_no_time_before", "{cron} names no time before {before}: {detail}")

NO_INTERVAL = SCHEDULE.define("no_interval", "an interval schedule has no interval")

NO_INSTANT = SCHEDULE.define("no_instant", "a one-time schedule has no instant")

BAD_INTERVAL = SCHEDULE.define("bad_interval", "{detail}")

BAD_MOMENT = SCHEDULE.define("bad_moment", "{text} is not a moment: write one as 2026-06-01T09:00:00Z")

DUPLICATE_SCHEDULE = SCHEDULE.define("duplicate", "pipeline {pipeline} already has a schedule coded {code}")

UNKNOWN_SCHEDULE = SCHEDULE.define("unknown", "pipeline {pipeline} has no schedule coded {code}")

BACKFILL_ONE_TIME = SCHEDULE.define(
    "backfill_one_time",
    "schedule {code} fires once at one instant, so it has no cadence to "
    "enumerate; a backfill needs a cron or an interval schedule",
)

BACKFILL_TOO_MANY = SCHEDULE.define(
    "backfill_too_many",
    "a backfill creates at most {cap} runs, and {code} over {start}..{end} enumerates {counted}; narrow the interval",
)

ALERT = Catalogue("alert")

DUPLICATE_RULE = ALERT.define("duplicate_rule", "an alert rule coded {code} already exists")

BAD_ALERT_TEMPLATE = ALERT.define("bad_template", "{field} is not a Jinja template: {detail}")

SCOPE_NEEDS_PIPELINE = ALERT.define(
    "scope_needs_pipeline", "a pipeline-scoped rule has to name the pipeline it watches"
)

ALERT_UNKNOWN_PIPELINE = ALERT.define("unknown_pipeline", "no pipeline coded {code}")

ALERT_UNKNOWN_CONNECTION = ALERT.define("unknown_connection", "no connection coded {code}")

TARGET_HAS_NO_NOTIFIER = ALERT.define(
    "target_has_no_notifier",
    "connection {code} is of kind {kind}, which no installed notifier delivers through ({installed})",
)

ALERT_VERSION_GONE = ALERT.define("version_gone", "run {run} pins a pipeline version that is gone")

NOTIFIER_NOT_ON_WORKER = ALERT.define("notifier_not_on_worker", "notifier {notifier} is not installed on this worker")

NOTIFICATION_IN_FLIGHT = ALERT.define(
    "notification_in_flight",
    "a worker is delivering this one; wait for it to finish or fail",
)

REFERENCE = Catalogue("reference")


def _unresolved(name: str, detail: str) -> Message:
    """Mint one reference refusal, all of which name the reference before saying why."""
    return REFERENCE.define(name, "${{{reference}}} cannot be resolved: " + detail)


NAMES_NOTHING = _unresolved("names_nothing", "it names nothing")

NO_ITEM = _unresolved("no_item", "this step does not fan out, so there is no item")

UNKNOWN_NAMESPACE = _unresolved(
    "unknown_namespace",
    "{namespace} is not a namespace; the reference language has params, steps, item, run, and artifacts",
)

NO_OUTPUT = _unresolved("no_output", "step {step} has no stored output ({available})")

NO_GRID = _unresolved(
    "no_grid",
    "step {step} has no grid here; steps.{bare_step}.items is the list a fan-out maps over, and only for_each reads it",
)

NOT_PAIRED = _unresolved(
    "not_paired",
    "this step does not fan over step {step}'s items; write for_each: ${{steps.{bare_step}.items}} to map over them",
)

ITEM_FAILED = _unresolved("item_failed", "step {step}'s item {index} did not succeed")

MALFORMED_STEP = _unresolved(
    "malformed_step",
    "a step reference reads steps.<name>.output.<field>, steps.<name>.items, or steps.<name>.item.output.<field>",
)

MALFORMED_RUN = _unresolved(
    "malformed_run",
    "run exposes only run.scratch, run.id, run.window.start and run.window.end",
)

MALFORMED_ARTIFACTS = _unresolved(
    "malformed_artifacts",
    "artifacts is the storage root itself and has no fields; write ${{artifacts}}/<path>",
)

NO_WINDOW = _unresolved(
    "no_window",
    "this run carries no window; a schedule-fired or backfilled run has one, "
    "and an ad hoc run only if it was started with one",
)

NO_FIELD = _unresolved("no_field", "{walked} has no {part} ({available})")

NOT_FAILED = _unresolved("not_failed", "step {step} did not fail, and its error is read only when it did")

SHELL_ARITHMETIC = _unresolved(
    "shell_arithmetic",
    "it is inside shell arithmetic, which evaluates a value as an expression, and it is not an integer",
)

RUN = Catalogue("run")

RUN_UNKNOWN_CONNECTION = RUN.define("unknown_connection", "no connection coded {ref} ({available})")

RUN_UNKNOWN_SCHEMA = RUN.define(
    "unknown_schema",
    "this run holds no shape coded {code}: it checks against the shapes its document named when "
    "it started ({available}), and takes no others while it runs",
)

RUN_SCHEMA_NOT_HELD = RUN.define(
    "schema_not_held",
    "no schema coded {code} exists on this instance ({held}), and this pipeline checks against "
    "it; store that shape, or apply a version of the pipeline that does not name it",
)

UNKNOWN_CONNECTION_KIND = RUN.define(
    "unknown_connection_kind",
    "connection {ref} has kind {kind}, which no installed plugin contributes",
)

STEP_NOT_IN_VERSION = RUN.define("step_not_in_version", "step {step} is not in the pinned pipeline version")

CONFIG_REFUSED = RUN.define("config_refused", "{detail}")

# A failure nobody anticipated has no sentence of its own, and a Python class name is not one:
# the person is told what failed and where the words are, and the class and the exception's own
# text ride in the params and in the step's log, which is what an operator reads.

CONFIG_FAILED = RUN.define(
    "config_failed",
    "the config of step {step} could not be prepared, and the failure names no value to correct",
)

BLOCK_NOT_INSTALLED = RUN.define("block_not_installed", "block {block} is not installed")

BLOCK_RAISED = RUN.define(
    "block_raised",
    "the {block} block failed with an error it does not explain; the step's log carries what it raised",
)

GONE_PROBES = RUN.define("gone_probes", "{detail} (after {probes} consecutive GONE probes)")

DEADLINE_PASSED = RUN.define("deadline_passed", "the deadline {deadline} passed before the step finished")

DEADLINE_SKIPPED = RUN.define("deadline_skipped", "the deadline {deadline} passed; the step is skipped")

CALL_TIMED_OUT = RUN.define("call_timed_out", "the block call timed out")

CALL_EXCEEDED_TIMEOUT = RUN.define("call_exceeded_timeout", "the block call exceeded the step timeout {timeout}")

UNSAFE_BLOCK = RUN.define(
    "unsafe_block",
    "block {block} executes code on the worker and is disabled; add it to DIRIGENT_ENABLED_UNSAFE_BLOCKS to allow it",
)

FAN_OUT_NOT_FANNING = RUN.define(
    "fan_out_not_fanning",
    "step {step} maps over step {adopted}'s items, but {adopted} does not fan out",
)

FAN_OUT_TOO_WIDE = RUN.define(
    "fan_out_too_wide",
    "step {step} maps over {count} items, and this instance allows at most {maximum} in one grid (fan_out_max_items)",
)

FAN_OUT_EMPTY = RUN.define(
    "fan_out_empty",
    "step {step} maps over {expression}, which {source} left empty, so the step is skipped",
)

FAN_OUT_WITHOUT_ITEM = RUN.define(
    "fan_out_without_item",
    "step {step} fans out, and an attempt with no item has nothing to run over",
)

GATE_NOT_RETRYABLE = RUN.define(
    "gate_not_retryable",
    "step {step} has no item to retry: its grid is read from {source} once, when the step "
    "becomes ready; retry {source}, or an item of {step} once the grid has expanded",
)

FAN_OUT_NOT_A_LIST = RUN.define(
    "fan_out_not_a_list",
    "step {step} maps over {expression}, which resolved to {kind}, not a list",
)

STEP_REFUSED = RUN.define("step_refused", "step {step}: {detail}")

NO_ATTEMPT_TO_RETRY = RUN.define("no_attempt_to_retry", "run {run} has no attempt of step {step} to retry")

NOT_RETRYABLE = RUN.define("not_retryable", "step {step} is {status}, and only a settled failure can be retried")

RUN_VERSION_GONE = RUN.define("version_gone", "run {run} pins a pipeline version that is gone")

RERUN_IN_FLIGHT = RUN.define("rerun_in_flight", "run {run} is still {status}, and only a settled run can be rerun")

RERUN_INPUT_GONE = RUN.define("rerun_input_gone", "run {run} no longer holds the input that entered it at {step}")

RETRY_CONCURRENCY = RUN.define(
    "retry_concurrency",
    "another run of pipeline {code} is in flight; retry once it has finished",
)

PARENT_GONE = RUN.define("parent_gone", "run {run} no longer exists")

CHILD_REFUSED = RUN.define("child_refused", "a run of pipeline {pipeline} could not be started: {detail}")

SELF_START = RUN.define(
    "self_start",
    "pipeline {pipeline} cannot start itself; a step that targets its own pipeline is a cycle, not a loop",
)

CHAIN_CYCLE = RUN.define(
    "chain_cycle",
    "pipeline {pipeline} is already running further up this chain, so starting it here is a cycle",
)

CHAIN_TOO_DEEP = RUN.define(
    "chain_too_deep",
    "a run of pipeline {pipeline} would be {depth} pipelines deep, and max_depth is {maximum}",
)

RUN_UNKNOWN_PIPELINE = RUN.define("unknown_pipeline", "this instance has no pipeline coded {code}")

RUN_PIPELINE_INACTIVE = RUN.define("pipeline_inactive", "pipeline {code} is deactivated")

RUN_PIPELINE_NO_VERSIONS = RUN.define("pipeline_no_versions", "pipeline {code} has no versions yet")

RUN_PIPELINE_UNREADABLE = RUN.define("pipeline_unreadable", "pipeline {code} has no readable current version")

REMOTE_JOB_FAILED = RUN.define("remote_job_failed", "the remote job failed")

REMOTE_JOB_SAID = RUN.define("remote_job_said", "{detail}")

REMOTE_JOB_GONE = RUN.define("remote_job_gone", "the remote no longer knows this job")

ITEM_UNPAIRED = RUN.define(
    "item_unpaired",
    "item {index} ({key}) of step {step} did not succeed, so this item is skipped",
)

BACKWARDS_WINDOW = RUN.define(
    "backwards_window",
    "a window runs forwards and covers something: {start} is not before {end}",
)

CANCELLED = RUN.define("cancelled", "this run was cancelled")

NOT_PAUSABLE = RUN.define("not_pausable", "run {run} is {status}, and only a queued or running run pauses")

NOT_PAUSED = RUN.define("not_paused", "run {run} is {status}, and only a paused run resumes")

CANCELLED_BY = RUN.define("cancelled_by", "cancelled by {principal}")

REPLACED_BY_NEWER_RUN = RUN.define("replaced_by_newer_run", "replaced by a newer run")

REPLACED_BY_RETRY = RUN.define("replaced_by_retry", "replaced by a manual retry")

GIVEN_NO_ENTRY = RUN.define(
    "given_no_entry",
    "pipeline {code} starts at its sources ({sources}), so a run of it enters through one of them",
)

ENTRY_NOT_A_SOURCE = RUN.define(
    "entry_not_a_source",
    "step {step} is not a source of pipeline {code}; a run enters at one of {sources}",
)

ENTRY_ON_NO_SOURCES = RUN.define(
    "entry_on_no_sources",
    "pipeline {code} has no sources, so a run of it is not entered at a step",
)

ENTRY_AMBIGUOUS = RUN.define(
    "entry_ambiguous",
    "pipeline {code} has the sources {sources}; name the one this run enters at",
)

ENTRY_INPUT_REFUSED = RUN.define(
    "entry_input_refused",
    "the input for source {step} is not one its kind {kind} can make whole: {detail}",
)

SOURCE_NOT_RETRYABLE = RUN.define(
    "source_not_retryable",
    "step {step} is a source, settled with the input the run was created for; running that input again is a new run",
)

REPLY_NOT_RETRYABLE = RUN.define(
    "reply_not_retryable",
    "step {step} is a reply, settled by the server once, when the steps it answers from settled",
)

SERVER_SETTLED = RUN.define("server_settled", "step {step} is a {kind}, which the server settles and no worker claims")

NOT_ENTERED = RUN.define("not_entered", "the input arrived at {entered}, so {step} was not entered")

REPLY_REFUSED = RUN.define("reply_refused", "reply {step} could not be rendered: {detail}")

REPLY_STATUS = RUN.define(
    "reply_status", "reply {step} answers with {status}, and a reply's status is a whole number from 200 to 599"
)

REPLY_BODY_FROM = RUN.define(
    "reply_body_from", "reply {step} streams its body from {value}, and body_from names a storage URI"
)

SOURCE = Catalogue("source")

SOURCE_FIELD_REFUSED = SOURCE.define(
    "field_refused",
    "a source takes name, description and sample, and nothing else; {field} goes on the step after it",
)

REPLY_FIELD_REFUSED = SOURCE.define(
    "reply_field_refused",
    "a reply takes depends_on, rule, name and description, and nothing else; {field} is not one of them",
)

STEP_ONE_FORM = SOURCE.define(
    "step_one_form",
    "a step is exactly one of block, source or reply, and this one writes {named}",
)

SAMPLE_OUTSIDE_SOURCE = SOURCE.define("sample_outside_source", "only a source takes a sample")

REPLY_BODY_TWICE = SOURCE.define("reply_body_twice", "a reply takes body or body_from, not both")

REPLY_BAD_STATUS = SOURCE.define(
    "reply_bad_status", "a reply's status is a whole number from 200 to 599 or a reference to one, not {status}"
)

REPLY_BAD_HEADER = SOURCE.define("reply_bad_header", "a reply does not set {header}, which the server writes itself")

UNKNOWN_KIND = SOURCE.define("unknown_kind", "no source kind {kind} is available on this instance ({known})")

SAMPLE_INVALID = SOURCE.define(
    "sample_invalid", "the sample of source {step} is not an input its kind {kind} can make whole: {detail}"
)

ROOT_BESIDE_SOURCES = SOURCE.define(
    "root_beside_sources",
    "step {step} depends on nothing in a pipeline with sources, so it would run on every input "
    "from every source; make it depend on the source it belongs to",
)

JOIN_OF_SOURCES = SOURCE.define(
    "join_of_sources",
    "step {step} waits with all_success on both {first} and {second}, and a run enters at one "
    "source only, so it could never run; join them with all_done or always",
)

SCHEDULE_ON_SOURCES = SOURCE.define(
    "schedule_on_sources",
    "pipeline {code} starts at its sources, and a schedule would enter none of them; run it from a source instead",
)

REQUIRED_PARAM_ON_SOURCES = SOURCE.define(
    "required_param_on_sources",
    "parameter {name} is required with no default, and a run a source creates takes the defaults; give it a default",
)

REPLACE_ON_HELD = SOURCE.define(
    "replace_on_held",
    "pipeline {code} has a {hosting} source, and concurrency: {policy} would drop an input the source "
    "has already taken; use allow or queue",
)

ROUTE_CLAIMED = SOURCE.define(
    "route_claimed",
    "{method} {template} is already answered by source {step} of pipeline {pipeline}",
)

REPLY_NOT_A_LEAF = SOURCE.define(
    "reply_not_a_leaf", "step {dependent} depends on reply {step}, and a reply is a leaf: nothing waits on it"
)

REPLY_NO_SOURCE = SOURCE.define(
    "reply_no_source",
    "reply {step} is downstream of no source that replies, so there is nobody for it to answer",
)

REFERENCE_ERROR_NOT_UPSTREAM = SOURCE.define(
    "reference_error_not_upstream",
    "{reference} reads the failure of {target}, which is not upstream of step {step}",
)

UNSUPPORTED_MEDIA = SOURCE.define(
    "unsupported_media",
    "this endpoint takes {accepted}, not {content_type}; a file is posted as a URI in a JSON body",
)

BODY_WITHOUT_TYPE = SOURCE.define(
    "body_without_type", "the body arrived with no content-type, and this endpoint takes {accepted}"
)

ENDPOINT_BODY_NOT_JSON = SOURCE.define("body_not_json", "the body is not JSON: {detail}")

ENDPOINT_BODY_NOT_TEXT = SOURCE.define("body_not_text", "the body is not {charset} text: {detail}")

REFERENCE_MALFORMED_ERROR = SOURCE.define(
    "reference_malformed_error",
    "{reference} reads a failure, which is written steps.<name>.error.code, .message, or .params",
)

SAMPLE_NOT_AN_OBJECT = SOURCE.define("sample_not_an_object", "a sample is written as an object, not a {kind}")

ENDPOINT_ACCEPTS_REFUSED = SOURCE.define(
    "endpoint_accepts_refused",
    "an endpoint reads JSON, urlencoded forms and text, and {accepts} is none of them; "
    "a file is posted as a URI in a JSON body",
)

ENDPOINT_METHOD_NOT_DECLARED = SOURCE.define(
    "endpoint_method_not_declared", "the method {method} is not one this endpoint answers ({methods})"
)

ENDPOINT_PATH_PARAMS_MISSING = SOURCE.define(
    "endpoint_path_params_missing", "the path template takes {names}, and path_params gives no value for it"
)

NO_ROUTE = SOURCE.define("no_route", "nothing on this instance answers {method} {path}")

METHOD_NOT_ANSWERED = SOURCE.define("method_not_answered", "{path} answers {allowed}, not {method}")

TOKEN_REFUSED = SOURCE.define(
    "token_refused", "this endpoint takes the bearer token minted for it, in an Authorization header"
)

INTAKE_RATE = SOURCE.define("intake_rate", "this instance takes {per_minute} calls a minute at one path")

SOURCE_RATE = SOURCE.define("rate", "this endpoint takes {per_minute} calls a minute")

SOURCE_PAUSED = SOURCE.define("paused", "source {code} of pipeline {pipeline} is paused")

SOURCE_PIPELINE_INACTIVE = SOURCE.define(
    "pipeline_inactive", "pipeline {pipeline} is deactivated, so its source {code} takes no input"
)

SOURCE_KIND_MISSING = SOURCE.define(
    "kind_missing", "source {code} is of kind {kind}, which is not installed on this instance"
)

SOURCE_BODY_TOO_LARGE = SOURCE.define("body_too_large", "the body is larger than the {limit} bytes this endpoint reads")

SOURCE_BACKLOGGED = SOURCE.define(
    "backlogged",
    "source {code} has {in_flight} runs unsettled, as many as it allows; send again once one settles",
)

SOURCE_RUN_SKIPPED = SOURCE.define(
    "run_skipped", "a run of pipeline {pipeline} is already in flight, and its concurrency is skip"
)

SOURCE_RUN_REFUSED = SOURCE.define("run_refused", "no run could be created: {detail}")

SENSOR_UNKNOWN = SOURCE.define(
    "sensor_unknown", "no sensor {block} is installed on this instance (the sensors a source pokes: {known})"
)

SENSOR_NOT_A_SOURCE = SOURCE.define(
    "sensor_not_a_source",
    "{block} is not a sensor a source pokes outside a run (those installed: {known})",
)

SENSOR_OUTSIDE_RUN = SOURCE.define(
    "sensor_outside_run", "{block} read {what}, which a sensor poked by a source has no run to give"
)

SOURCE_WAITING_FULL = SOURCE.define(
    "waiting_full", "this server holds {waiting} callers for their replies, as many as it may; send again shortly"
)

SOURCE_WAITING_SHARE = SOURCE.define(
    "waiting_share",
    "this server holds {waiting} callers of source {code} for their replies, as many as one source may; "
    "send again shortly",
)

REPLY_REJECTED = SOURCE.define("reply_rejected", "run {run} refused the input at step {step}: {detail}")

REPLY_FAILED = SOURCE.define("reply_failed", "run {run} failed at step {step} before any reply answered: {detail}")

REPLY_UNANSWERED = SOURCE.define("reply_unanswered", "run {run} is {status}, and no reply answered")

REPLY_TIMED_OUT = SOURCE.define(
    "reply_timed_out", "no reply of run {run} answered within {timeout}; the run carries on"
)

UNKNOWN_SOURCE = SOURCE.define("unknown", "pipeline {pipeline} has no source {code}")

ROUTE_RACED = SOURCE.define(
    "route_raced",
    "{method} {template} was claimed by another pipeline while this one was applied; apply again to see which",
)

SOURCE_SIGNATURE_REQUIRED = SOURCE.define(
    "signature_required", "this endpoint takes a signature of the body in a {header} header"
)

SOURCE_SIGNATURE_MISMATCH = SOURCE.define("signature_mismatch", "the signature does not match the body")

SOURCE_NOT_SIGNED = SOURCE.define(
    "not_signed", "source {code} of pipeline {pipeline} is {auth}, so it has no signing secret to set"
)

SOURCE_EMPTY_SECRET = SOURCE.define("empty_secret", "an empty signing secret is not a secret")

SOURCE_TAKES_NO_TOKEN = SOURCE.define(
    "takes_no_token", "source {code} of pipeline {pipeline} is {auth}, so it has no token to rotate"
)
