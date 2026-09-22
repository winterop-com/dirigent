"""Every refusal the CLI decides on itself, and everything a health check reports."""

from dirigent_common import Catalogue

CLI = Catalogue("cli")

NOT_AN_OUTPUT_FORMAT = CLI.define("not_an_output_format", "{chosen} is not an output format")

OUTPUTS_ARE = CLI.define("outputs_are", "the outputs are {formats}")

FORMATTER_TAKES_NO_TEMPLATE = CLI.define(
    "formatter_takes_no_template",
    "a formatter renders whole records; it takes no template",
)

USE_JQ = CLI.define("use_jq", "to pick fields out, use jq:  dg dev | jq -r '.step'")

NOT_A_FORMATTER = CLI.define("not_a_formatter", "{named} is not a formatter")

FORMATTERS_ARE = CLI.define("formatters_are", "the formatters are {formatters}")

NEVER_MIGRATED = CLI.define("never_migrated", "the database has never been migrated")

RUN_DB_UPGRADE = CLI.define("run_db_upgrade", "run dg db upgrade")

UNKNOWN_CONNECTION_KIND = CLI.define("unknown_connection_kind", "no connection kind {kind} is installed ({known})")

CONNECTION_UNUSABLE = CLI.define("connection_unusable", "{code} is not a usable {kind} connection: {detail}")

INVALID_AGE = CLI.define("invalid_age", "{detail}")

NOTHING_TO_PRUNE = CLI.define("nothing_to_prune", "no family has an age, so there is nothing to prune")

GIVE_AN_AGE = CLI.define(
    "give_an_age",
    "give --runs, --logs, --deliveries, --firings or --notifications, or configure one",
)

SERVER_NEEDS_A_LEADER = CLI.define(
    "server_needs_a_leader",
    "dg server embeds the scheduler, and leadership is a PostgreSQL advisory lock: on SQLite "
    "nothing stops a second server double-firing every schedule",
)

USE_DG_DEV_STANDALONE = CLI.define("use_dg_dev_standalone", "use dg dev for the standalone mode")

OR_NO_SCHEDULER = CLI.define("or_no_scheduler", "or pass --no-scheduler")

OR_POSTGRES = CLI.define("or_postgres", "or point DIRIGENT_DATABASE_URL at PostgreSQL")

NO_DOCKER_DAEMON = CLI.define(
    "no_docker_daemon",
    "docker is not on this host's PATH, so there is no daemon to reap stacks from",
)

AUTH_REFUSED = CLI.define("auth_refused", "{detail}")

DEV_IS_SQLITE_ONLY = CLI.define("dev_is_sqlite_only", "dg dev is the SQLite standalone mode")

USE_DG_SERVER = CLI.define("use_dg_server", "use dg server on PostgreSQL")

NO_ADMIN_TO_SEED = CLI.define("no_admin_to_seed", "dg dev --seed has no admin account to seed as")

CREATE_AN_ADMIN = CLI.define("create_an_admin", "create one with dg admin user create --role admin")

WORKER_NEEDS_POSTGRES = CLI.define(
    "worker_needs_postgres",
    "dg worker refuses to start on SQLite: its claim fallback is only correct with exactly one process",
)

USE_DG_DEV = CLI.define("use_dg_dev", "use dg dev")

SCHEDULER_NEEDS_POSTGRES = CLI.define(
    "scheduler_needs_postgres",
    "dg scheduler refuses to start on SQLite: leadership is a PostgreSQL advisory lock, and "
    "without one nothing stops a second scheduler double-firing every schedule",
)

CANNOT_PROMPT = CLI.define("cannot_prompt", "--json cannot prompt for {label}; pass it as an option")

CANNOT_PROMPT_SET = CLI.define("cannot_prompt_set", "--json cannot prompt for {field}; pass it as --set {field}=...")

PARAMS_REFUSED = CLI.define("params_refused", "{detail}")

TRIGGERS_DOCUMENT_NOT_RUNNABLE = CLI.define(
    "triggers_document_not_runnable",
    "a triggers document declares clocks for a pipeline and cannot be run; run the pipeline it names",
)

PRUNE_IS_PROJECT_WIDE = CLI.define(
    "prune_is_project_wide",
    "--prune reconciles a whole project, so it cannot be used with a single document",
)

SOURCE_REFUSED = CLI.define("source_refused", "{detail}")

NO_DOCUMENT_AND_NO_PROJECT = CLI.define(
    "no_document_and_no_project",
    "no document was named and this directory is not a project; run dg init, or name a file",
)

AS_IS_ONE_DOCUMENT = CLI.define(
    "as_is_one_document",
    "--as recodes one document, so it cannot be used when applying a whole project",
)

PROJECT_IS_EMPTY = CLI.define("project_is_empty", "{directory} holds no documents")

ALL_TAKES_NO_CODE = CLI.define(
    "all_takes_no_code", "--all checks every pipeline, so it takes neither a code nor a version"
)

NAME_A_PIPELINE = CLI.define("name_a_pipeline", "name a pipeline, or pass --all to check every one of them")

LOG_LEVEL_NO_PATTERN = CLI.define("log_level_no_pattern", "--log-level {value} names no pattern before the =")

LOG_LEVEL_NOT_A_LEVEL = CLI.define("log_level_not_a_level", "--log-level {value}: {named} is not a level ({allowed})")

NOT_A_PRIORITY = CLI.define("not_a_priority", "--priority {value} is not a priority ({allowed})")

STRICT_NEEDS_WATCH = CLI.define(
    "strict_needs_watch", "--strict decides on a run's outcome, so it needs --watch or --local"
)

KEEP_IS_LOCAL_ONLY = CLI.define(
    "keep_is_local_only",
    "--keep leaves a --local run's throwaway instance behind; a real instance keeps its own",
)

ROOT_IS_LOCAL_ONLY = CLI.define(
    "root_is_local_only",
    "--root holds a --local run's instance in a directory; a real instance has its own",
)

PRIORITY_IS_NOT_LOCAL = CLI.define(
    "priority_is_not_local",
    "--priority orders a run against the others queued, and a --local run has none",
)

DOCUMENT_INVALID = CLI.define("document_invalid", "{code} does not validate")

RUN_SKIPPED = CLI.define("run_skipped", "{detail}")

CONCURRENCY_REFUSED = CLI.define("concurrency_refused", "the concurrency policy refused this run")

LOCAL_TAKES_NO_SERVER = CLI.define(
    "local_takes_no_server",
    "--local runs here with no server, so it cannot be combined with --url, --token, or --profile",
)

LOCAL_TAKES_A_DOCUMENT = CLI.define(
    "local_takes_a_document",
    "--local runs a document, and {target} is not a file, a URL, or '-'",
)

LOCAL_RUN_HAD_NO_OUTCOME = CLI.define("local_run_had_no_outcome", "the local run produced no outcome")

GUARD_REFUSED = CLI.define("guard_refused", "{detail}")

UNSAFE_FOR_THIS_RUN = CLI.define(
    "unsafe_for_this_run",
    "for this run only: dg run --local ... --enable-unsafe shell.run",
)

UNSAFE_FOR_THE_INSTANCE = CLI.define(
    "unsafe_for_the_instance",
    "for the instance:  export DIRIGENT_ENABLED_UNSAFE_BLOCKS='[\"shell.run\"]'",
)

NOT_A_RUN_STATUS = CLI.define("not_a_run_status", "{value} is not a run status ({allowed})")

NO_FAILURE_TO_RETRY = CLI.define("no_failure_to_retry", "run {run_id} has no settled failure of step {step} to retry")

NO_REPORT_DOCUMENT = CLI.define(
    "no_report_document",
    "run {run_id} has no report document; declare `report:` in the pipeline document",
)

NOT_A_BLOCK_KIND = CLI.define("not_a_block_kind", "{kind} is not a block kind ({allowed})")

SCHEMA_UNREADABLE = CLI.define("schema_unreadable", "{label} is not readable JSON or YAML: {detail}")

SCHEMA_NOT_AN_OBJECT = CLI.define(
    "schema_not_an_object",
    "{label} is not a JSON Schema: a schema is an object, and this is {kind}",
)

NOT_AUTHENTICATED = CLI.define("not_authenticated", "no token for {url}")

SET_DG_TOKEN = CLI.define("set_dg_token", "set DG_TOKEN")

OR_A_PROFILE_TOKEN = CLI.define("or_a_profile_token", "or add a token to a profile")

OR_DG_AUTH_LOGIN = CLI.define("or_dg_auth_login", "or mint one with dg auth login")

NO_SUCH_EXAMPLE = CLI.define("no_such_example", "{detail}")

NOT_A_STARTER = CLI.define("not_a_starter", "{code} is an example, not a starter")

STARTER_TAG_NEEDED = CLI.define(
    "starter_tag_needed",
    "a document is copyable only when it wears the {tag} tag",
)

ALREADY_THERE = CLI.define("already_there", "{path} is already there")

NAME_ANOTHER_CODE = CLI.define("name_another_code", "name another code with --code")

ONE_CLOCK = CLI.define("one_clock", "a schedule takes exactly one of --cron, --interval, or --at ({named} given)")

AT_TAKES_AN_INSTANT = CLI.define("at_takes_an_instant", "--at takes an ISO instant, and {value} is not one")

MAP_TAKES_A_PATH = CLI.define(
    "map_takes_a_path",
    "--map takes param=$.path.into.payload, and {entry} has no '='",
)

NOT_AN_ALERT_EVENT = CLI.define("not_an_alert_event", "{event} is not an alert event ({allowed})")

NOT_AN_IMPORTANCE = CLI.define("not_an_importance", "--importance {value} is not an importance ({allowed})")

ONE_BODY = CLI.define("one_body", "a rule takes one body: --body or --body-file, not both")

SCAFFOLD_REFUSED = CLI.define("scaffold_refused", "{detail}")

LOCAL_INSTANCE_HINT = CLI.define(
    "local_instance_hint",
    "nothing is listening there; uv run dg dev in the project starts its instance",
)

CALL_REFUSED = CLI.define("call_refused", "{detail}")

WINDOW_GRAMMAR = CLI.define(
    "window_grammar",
    "--window takes START..END: two ISO 8601 instants separated by '..'",
)

NOT_A_WINDOW = CLI.define("not_a_window", "{grammar}, not {value}")

INIT_CANCELLED = CLI.define("init_cancelled", "cancelled; nothing was written")

INIT_REFUSED = CLI.define("init_refused", "{detail}")

ADMIN_IS_FIXED_IN_A_STACK = CLI.define(
    "admin_is_fixed_in_a_stack",
    "--admin does not apply to the compose template; the stack's first admin is named admin",
)

INSTANCE_ALREADY_HERE = CLI.define("instance_already_here", "this directory holds an instance already: {path}")

INIT_WAY = CLI.define("init_way", "{command} {what}")

NO_FIRST_PASSWORD = CLI.define(
    "no_first_password",
    "no password for the first admin: pass --password, or set {variable}",
)


HEALTH = Catalogue("health")

WORKER_NEVER_REGISTERED = HEALTH.define("worker.never_registered", "no worker has ever registered{place}")

WORKER_ALL_STOPPED = HEALTH.define("worker.all_stopped", "every worker{place} has stopped")

WORKER_SILENT = HEALTH.define("worker.silent", "{noun} went silent, the last {quiet}s ago")

WORKER_BEATING = HEALTH.define("worker.beating", "a worker on {hostname} is beating")

WORKERS_BEATING = HEALTH.define("worker.beating_count", "{beating} of {alive} workers beating")

SCHEDULER_IDLE = HEALTH.define("scheduler.idle", "no schedule is waiting to fire")

SCHEDULER_OVERDUE = HEALTH.define(
    "scheduler.overdue",
    "{overdue} of {waiting} schedules overdue, the oldest by {late}s: nothing is firing them",
)

SCHEDULER_ON_TIME = HEALTH.define("scheduler.on_time", "{waiting} schedules waiting, none overdue")

SERVER_NOT_ANSWERING = HEALTH.define("server.not_answering", "nothing is answering at {where}")

SERVER_NOT_SERVING = HEALTH.define("server.not_serving", "nothing is serving {where}")

SERVER_ERRORED = HEALTH.define("server.errored", "the server at {where}: {kind}")

SERVER_REFUSED = HEALTH.define("server.refused", "the server at {where} answered {status_code} to {path}")

SERVER_OK = HEALTH.define("server.ok", "the server at {where} is {word}")

DATABASE_ABSENT = HEALTH.define("database.absent", "no database at {target}")

DATABASE_UNREACHABLE = HEALTH.define("database.unreachable", "{where} is unreachable: {kind}")

DATABASE_UNMIGRATED = HEALTH.define(
    "database.unmigrated",
    "the database at {where} answers, but holds no schema; run `dg db upgrade`",
)

DATABASE_BEHIND = HEALTH.define(
    "database.behind",
    "the database at {where} is at schema {stamped}, and this dirigent expects {head}; run `dg db upgrade`",
)

DATABASE_OK = HEALTH.define("database.ok", "the database at {where} answers, schema {stamped}")
