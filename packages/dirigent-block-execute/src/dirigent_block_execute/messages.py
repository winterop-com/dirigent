"""Every refusal the execute family makes, catalogued under the ``execute`` prefix."""

from dirigent_common import Catalogue

EXECUTE = Catalogue("execute")

TIMED_OUT = EXECUTE.define("timed_out", "{what} did not finish within {seconds}s")

NO_GIT = EXECUTE.define(
    "no_git",
    "git is not on the worker's PATH, so nothing here can check a repository out; "
    "the worker image installs it, a bare host may not",
)

GIT_EXITED = EXECUTE.define("git_exited", "git {command} exited {code}: {detail}")

CHECKOUT_THROUGH_A_SYMLINK = EXECUTE.define(
    "checkout_through_a_symlink",
    "the checkout target {target} leads through the symlink {walked}, which can point "
    "anywhere; a target is a path of real directories under the run's work directory {base}",
)

CHECKOUT_OUTSIDE_THE_WORK_DIRECTORY = EXECUTE.define(
    "checkout_outside_the_work_directory",
    "the checkout target {target} lands at {destination}, which is outside the run's work directory {base}",
)

COMPOSE_UP_EXITED = EXECUTE.define("compose_up_exited", "docker compose up exited {code}: {detail}")

COMPOSE_DOWN_EXITED = EXECUTE.define("compose_down_exited", "docker compose down exited {code}: {detail}")

NO_REGISTRY_CREDENTIAL = EXECUTE.define(
    "no_registry_credential",
    "docker.build cannot push through a connection with no registry credential: set "
    "username and password on the docker connection, and registry unless it is Docker Hub",
)

BUILD_EXITED = EXECUTE.define("build_exited", "docker build exited {code}: {detail}")

NO_IMAGE_ID = EXECUTE.define("no_image_id", "docker build reported success but wrote no image id to the iidfile")

LOGIN_FAILED = EXECUTE.define("login_failed", "docker login to {registry} failed: {detail}")

PUSH_EXITED = EXECUTE.define("push_exited", "docker push {tag} exited {code}: {detail}")

CONTAINER_GONE = EXECUTE.define(
    "container_gone",
    "container {container} disappeared before its result could be collected",
)

OUTPUT_NOT_WRITTEN = EXECUTE.define(
    "output_not_written",
    "the container did not write the declared output {name} to {path}",
)

NO_DAEMON = EXECUTE.define(
    "no_daemon",
    "the Docker daemon at {socket} did not answer ({detail}); a worker in a "
    "container has no daemon unless the host's socket is mounted into it, and "
    "mounting it grants the container root on the host",
)

DAEMON_REFUSED = EXECUTE.define("daemon_refused", "the daemon refused to {action}: {detail}")

COMMAND_EXITED = EXECUTE.define("command_exited", "the command exited {code}: {detail}")


# What a config refuses at validation. Pydantic owns the code a validator's refusal reaches
# the wire under, so these are rendered into the ``ValueError`` it wraps.

PUSH_NEEDS_A_CONNECTION = EXECUTE.define(
    "push_needs_a_connection",
    "docker.build cannot push without a connection: set connection to a docker connection "
    "holding registry, username and password",
)

PUSH_NEEDS_A_TAG = EXECUTE.define(
    "push_needs_a_tag",
    "docker.build pushes the tags it built, so a push needs at least one tag",
)

BUILD_PATHS_STAY_INSIDE = EXECUTE.define(
    "build_paths_stay_inside",
    "the context and Dockerfile are paths inside the run's work directory, so they cannot be absolute or climb out",
)

COMPOSE_UP_ONE_SOURCE = EXECUTE.define(
    "compose_up_one_source",
    "docker.compose.up takes either file or content, and exactly one of them",
)

COMPOSE_DOWN_ONE_SOURCE = EXECUTE.define(
    "compose_down_one_source",
    "docker.compose.down takes at most one of file or content",
)

COMPOSE_PATHS_STAY_INSIDE = EXECUTE.define(
    "compose_paths_stay_inside",
    "a compose file or env file is a path inside the run's work directory, so it cannot be absolute or climb out",
)

GIT_ONE_CREDENTIAL = EXECUTE.define(
    "git_one_credential",
    "a git connection carries one credential: a token for an https remote or an ssh_key for an ssh one, never both",
)

GIT_TOKEN_NEEDS_HTTPS = EXECUTE.define(
    "git_token_needs_https",
    "a token is HTTP basic auth, so the url must be http or https, not {url}",
)

GIT_KEY_NEEDS_SSH = EXECUTE.define("git_key_needs_ssh", "an ssh_key needs an ssh remote, and {url} is not one")

CHECKOUT_STAYS_INSIDE = EXECUTE.define(
    "checkout_stays_inside",
    "a checkout target is a path inside the run's work directory, so it cannot be absolute or climb out",
)

SHELL_ONE_FORM = EXECUTE.define("shell_one_form", "shell.run takes either argv or command, and exactly one of them")

CWD_STAYS_INSIDE = EXECUTE.define(
    "cwd_stays_inside",
    "cwd is a path inside the run's work directory, so it cannot be absolute or climb out",
)

NOT_A_DAEMON_SCHEME = EXECUTE.define(
    "not_a_daemon_scheme",
    "a docker host is one of {schemes}, and {host} is none of them",
)

TLS_IS_ALL_THREE = EXECUTE.define(
    "tls_is_all_three",
    "client TLS is all three of tls_ca, tls_cert and tls_key, or none of them",
)

TLS_NEEDS_TCP = EXECUTE.define(
    "tls_needs_tcp",
    "client TLS is how a tcp:// daemon is reached, so the host must be a tcp:// one",
)

CREDENTIAL_IS_A_PAIR = EXECUTE.define(
    "credential_is_a_pair",
    "a registry credential is a username and a password together, never one of them",
)

REGISTRY_WITHOUT_A_CREDENTIAL = EXECUTE.define(
    "registry_without_a_credential",
    "a registry ({registry}) with no username and password authenticates to nothing",
)

DOCKER_CONNECTION_NAMES_NEITHER = EXECUTE.define(
    "docker_connection_names_neither",
    "a docker connection names a daemon, a registry credential, or both, and this names neither",
)

RUN_ONE_FORM = EXECUTE.define(
    "run_one_form",
    "docker.run takes either argv or command, and never both; omit both to run the image's own entrypoint",
)

RUN_ONE_CPU_FIELD = EXECUTE.define("run_one_cpu_field", "docker.run takes either cpus or nano_cpus, and never both")

RUN_ONE_DAEMON = EXECUTE.define(
    "run_one_daemon",
    "a connection names the daemon, so docker.run takes either connection or socket_path",
)

MOUNTED_FILE_STAYS_INSIDE = EXECUTE.define(
    "mounted_file_stays_inside",
    "a mounted file is named inside its mount, so it cannot be absolute or climb out",
)

OUTPUT_STAYS_INSIDE = EXECUTE.define(
    "output_stays_inside",
    "an output without a URI scheme is a path inside the run's work directory, so it cannot be absolute or climb out",
)

RESERVED_ENVIRONMENT = EXECUTE.define(
    "reserved_environment",
    "env_allowlist may not inherit the instance's own configuration: {reserved}. "
    "{prefix}* holds this instance's secrets, including the envelope key for "
    "every stored connection; pass what the step needs through env, or a connection.",
)
