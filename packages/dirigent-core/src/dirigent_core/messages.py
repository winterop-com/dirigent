"""Every refusal the core makes, catalogued: one catalogue per area, one message per refusal.

A code is stable API. The text is English and may be reworded; the code and the params it
renders are what another language, a log reader and a test all hold on to.
"""

from dirigent_common import Catalogue, Message

DATABASE = Catalogue("database")

SCHEMA_STALE = DATABASE.define(
    "schema_stale",
    "the database at {where} was written by a different dirigent: {differences} difference(s), "
    "first {first}; before 1.0 the schema is not migrated, so start from an empty state "
    "(`dg dev --wipe-state`, or delete the state directory) or point at a database this version created",
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
    "pipeline {code} has {runs} run(s) still in flight and cannot be deleted; finish or cancel them first",
)

PIPELINE_DEACTIVATED = PIPELINE.define("deactivated", "pipeline {code} is deactivated")

PIPELINE_NO_VERSIONS = PIPELINE.define("no_versions", "pipeline {code} has no versions yet")

PIPELINE_NO_SUCH_VERSION = PIPELINE.define("no_such_version", "pipeline {code} has no version {version}")


SECRET = Catalogue("secret")

SECRET_KEY_MISSING = SECRET.define(
    "key_missing",
    "no secret key is configured: set DIRIGENT_SECRET_KEY before storing or reading "
    "connection secrets (generate one with `dg secret-key`)",
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

UNKNOWN_EXAMPLE = HOST.define("unknown_example", "no example {code} is installed; `dg examples list` says what is.")

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

CARRIED_CONNECTIONS = DOCUMENT.define(
    "carried_connections",
    "this document carries its own connections ({named}), which an instance will not store: "
    "create them with `dg connection create` and let the document name them",
)

CARRIED_SCHEMAS = DOCUMENT.define(
    "carried_schemas",
    "this document carries its own schemas ({named}), which an instance will not store: "
    "create them with `dg schema create` and let the document name them in requires.schemas",
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

WEBHOOK_MAPPING_REFUSED = DOCUMENT.define("webhook_mapping_refused", "{detail}")

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

FOR_EACH_READS_OUTPUT = DOCUMENT.define(
    "for_each_reads_output",
    "${{{reference}}} reads a step's output, and fan-out is expanded when the run is created: "
    "for_each may read params, run, and an upstream fan-out's grid as ${{steps.<name>.items}}, "
    "but not a step's output",
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


WEBHOOK = Catalogue("webhook")

SIGNATURE_REQUIRED = WEBHOOK.define("signature_required", "this webhook requires a {header} header")

SIGNATURE_MISMATCH = WEBHOOK.define("signature_mismatch", "the signature does not match the body")

PATH_ADDRESSES_NOTHING = WEBHOOK.define("path_addresses_nothing", "the mapping path {path} addresses nothing")

PAYLOAD_MISSING = WEBHOOK.define("payload_missing", "the payload has no {walked}.{part} ({available})")

MAPPING_REFUSED = WEBHOOK.define("mapping_refused", "{detail}")

EMPTY_SIGNING_SECRET = WEBHOOK.define("empty_signing_secret", "an empty webhook signing secret is not a secret")

NO_SECRET_KEY = WEBHOOK.define(
    "no_secret_key",
    "a webhook signing secret cannot be stored without the instance's secret key",
)

DUPLICATE_WEBHOOK = WEBHOOK.define("duplicate", "pipeline {pipeline} already has a webhook coded {code}")

UNKNOWN_WEBHOOK = WEBHOOK.define("unknown", "pipeline {pipeline} has no webhook coded {code}")

BODY_TOO_LARGE = WEBHOOK.define(
    "body_too_large",
    "the body is at least {size} bytes, and this instance reads at most {maximum}",
)

BODY_NOT_JSON = WEBHOOK.define("body_not_json", "the body is not JSON: {detail}")

BODY_NOT_OBJECT = WEBHOOK.define("body_not_object", "a webhook payload is a JSON object, not {kind}")

WEBHOOK_DISABLED = WEBHOOK.define("disabled", "this webhook is disabled")

UNKNOWN_TOKEN = WEBHOOK.define("unknown_token", "no webhook accepts this token")

WEBHOOK_PIPELINE_GONE = WEBHOOK.define("pipeline_gone", "the pipeline this webhook belongs to no longer exists")

WEBHOOK_PIPELINE_INACTIVE = WEBHOOK.define("pipeline_inactive", "pipeline {code} is deactivated")

WEBHOOK_PIPELINE_NO_VERSIONS = WEBHOOK.define("pipeline_no_versions", "pipeline {code} has no versions yet")

WEBHOOK_PIPELINE_UNREADABLE = WEBHOOK.define("pipeline_unreadable", "pipeline {code} has no readable current version")

WEBHOOK_PARAMS_REFUSED = WEBHOOK.define(
    "params_refused",
    "the mapped payload does not satisfy the pipeline's parameters: {detail}",
)

WEBHOOK_RUN_REFUSED = WEBHOOK.define("run_refused", "{detail}")

PATH_NOT_ROOTED = WEBHOOK.define("path_not_rooted", "{path} is not a payload path: it does not start with '$'")

PATH_EMPTY = WEBHOOK.define("path_empty", "{path} is not a payload path: it addresses nothing")

PATH_BAD_ROOT = WEBHOOK.define(
    "path_bad_root",
    "{path} is not a payload path: the root is followed by {found} rather than '.'",
)

PATH_EMPTY_SEGMENT = WEBHOOK.define("path_empty_segment", "{path} is not a payload path: an empty segment")

NAME_UNDECLARED = WEBHOOK.define("name_undeclared", "{name} is not a parameter this pipeline declares ({declared})")

REQUIRED_UNMAPPED = WEBHOOK.define(
    "required_unmapped",
    "the required parameter {name} is not mapped, so no delivery could supply it",
)


ALERT = Catalogue("alert")

UNKNOWN_NOTIFIER = ALERT.define("unknown_notifier", "no notifier {notifier} is installed ({installed})")

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


RUN = Catalogue("run")

RUN_UNKNOWN_CONNECTION = RUN.define("unknown_connection", "no connection coded {ref} ({available})")

RUN_UNKNOWN_SCHEMA = RUN.define("unknown_schema", "no schema coded {code} ({available})")

UNKNOWN_CONNECTION_KIND = RUN.define(
    "unknown_connection_kind",
    "connection {ref} has kind {kind}, which no installed plugin contributes",
)

STEP_NOT_IN_VERSION = RUN.define("step_not_in_version", "step {step} is not in the pinned pipeline version")

CONFIG_REFUSED = RUN.define("config_refused", "{detail}")

CONFIG_FAILED = RUN.define("config_failed", "{kind}: {detail}")

BLOCK_NOT_INSTALLED = RUN.define("block_not_installed", "block {block} is not installed")

BLOCK_RAISED = RUN.define("block_raised", "{kind}: {detail}")

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

FAN_OUT_READS_OUTPUT = RUN.define(
    "fan_out_reads_output",
    "step {step} maps over {expression}: fan-out is expanded when the run is created, so for_each "
    "may read params, run, and an upstream fan-out's grid as ${{steps.<name>.items}}, "
    "but not a step's output",
)

FAN_OUT_NOT_A_LIST = RUN.define(
    "fan_out_not_a_list",
    "step {step} maps over {expression}, which resolved to {kind}, not a list",
)

STEP_REFUSED = RUN.define("step_refused", "step {step}: {detail}")

NO_ATTEMPT_TO_RETRY = RUN.define("no_attempt_to_retry", "run {run} has no attempt of step {step} to retry")

NOT_RETRYABLE = RUN.define("not_retryable", "step {step} is {status}, and only a settled failure can be retried")

RUN_VERSION_GONE = RUN.define("version_gone", "run {run} pins a pipeline version that is gone")

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
