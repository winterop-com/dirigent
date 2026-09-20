"""A private directory for the credential files a CLI reads, and the writes that fill it.

A tool that takes a credential takes it from a file: git through an askpass helper, docker
through a client key and a config directory. The file is 0600 inside a 0700 directory, is
created with those permissions rather than fixed after, and goes away when the step leaves
however it leaves.
"""

import contextlib
import os
import shutil
import stat
import tempfile
from collections.abc import Generator
from pathlib import Path

#: A file only its owner may read or write.
PRIVATE = stat.S_IRUSR | stat.S_IWUSR

#: A file only its owner may read, write or run.
EXECUTABLE = stat.S_IRWXU


@contextlib.contextmanager
def private_directory(parent: Path, prefix: str) -> Generator[Path]:
    """Make a 0700 directory under a parent, and remove it and everything in it afterwards."""
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    directory.chmod(stat.S_IRWXU)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def write(path: Path, text: str, mode: int = PRIVATE) -> None:
    """Write one credential file, created with its final permissions rather than fixed after."""
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(handle, "w") as sink:
        sink.write(text)


__all__ = ["EXECUTABLE", "PRIVATE", "private_directory", "write"]
