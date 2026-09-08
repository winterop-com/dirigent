"""What a pipeline document may and may not pull out of the worker's own environment.

``shell.run`` and ``docker.run`` both let a step name worker environment variables to
inherit. That is the point of an allowlist -- a step that needs ``JAVA_HOME`` should be able
to say so -- but the worker's environment is also where dirigent's own secrets live, and
the allowlist is a field of a *pipeline document*. Without a denylist, anyone who can edit a
pipeline can write::

    env_allowlist: [DIRIGENT_SECRET_KEY]
    command: 'echo "$DIRIGENT_SECRET_KEY"'

and read the envelope key out of ``log_entries``, which every principal can read. That is a
privilege escalation from "can edit pipelines" to "can decrypt every stored connection
secret", which is precisely the boundary the unsafe-block allowlist exists to hold.

So the instance's own variables are refused when the document is validated, and filtered
again when the environment is built. Both, deliberately: validation is where a person is
told, and the filter is what holds for a document that never passed validation.
"""

import os
from collections.abc import Iterable, Mapping

#: Must stay in step with the prefix ``Settings`` reads.
RESERVED_ENV_PREFIX = "DIRIGENT_"


def is_reserved(name: str) -> bool:
    """Report whether an environment variable belongs to the instance rather than the step."""
    return name.upper().startswith(RESERVED_ENV_PREFIX)


def reject_reserved(allowlist: Iterable[str]) -> None:
    """Refuse an allowlist that reaches for the instance's own configuration."""
    reserved = sorted({name for name in allowlist if is_reserved(name)})
    if reserved:
        raise ValueError(
            f"env_allowlist may not inherit the instance's own configuration: {', '.join(reserved)}. "
            f"{RESERVED_ENV_PREFIX}* holds this instance's secrets, including the envelope key for "
            "every stored connection; pass what the step needs through env, or a connection."
        )


def allowed(names: Iterable[str], environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Read the named variables out of the worker's environment, minus the reserved ones."""
    source = environ if environ is not None else os.environ
    return {name: source[name] for name in names if name in source and not is_reserved(name)}
