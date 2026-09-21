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
