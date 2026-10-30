"""What a local instance's state directory must be before anything opens or deletes it.

Every file check here is made on a descriptor reached without following a link. git is never
run: its index is read as bytes, so no configuration in the repository takes effect.
"""

import errno
import os
import shutil
import stat
import struct
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from dirigent_common import Message
from dirigent_core.config import STATE_DIR, Settings
from dirigent_core.errors import DomainError
from dirigent_core.messages import STATE_IS_A_LINK, STATE_NOT_YOURS, STATE_TRACKED, STATE_UNCHECKED, STATE_WRITABLE

#: The mode a state directory is created with, whatever the umask.
STATE_MODE: Final = 0o700

_STATE_PARTS: Final = Path(STATE_DIR).parts

#: Opens a directory, failing on a link in the last component instead of following it.
_DIRECTORY_NOFOLLOW: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

#: The object name widths a repository may use: SHA-1 and SHA-256.
_OBJECT_NAME_SIZES: Final = (20, 32)

#: The file types an index entry may carry: a blob, a link, a gitlink, a sparse directory.
_ENTRY_TYPES: Final = frozenset({0o10, 0o12, 0o16, 0o04})

#: The entry fields before the object name: ctime, mtime, dev, ino, mode, uid, gid, size.
_ENTRY_STAT_SIZE: Final = 40

_MODE_OFFSET: Final = 24
_FLAGS_SIZE: Final = 2
_NAME_LENGTH_MASK: Final = 0xFFF
_EXTENDED_FLAG: Final = 0x4000
_INDEX_HEADER_SIZE: Final = 12
_EXTENSION_HEADER_SIZE: Final = 8
_SPLIT_INDEX_EXTENSION: Final = b"link"


class StateRefused(DomainError):
    """A state directory that may not be opened or deleted, with the reason it was refused."""

    def __init__(self, reason: Message, /, **params: Any) -> None:
        """Render the reason, and keep it so a command can say it as its own refusal."""
        super().__init__(reason, **params)
        self.reason = reason


def is_state_directory(directory: Path) -> bool:
    """Report whether a directory is spelled the way a local instance's state directory is."""
    return directory.parts[-len(_STATE_PARTS) :] == _STATE_PARTS


def _open_below(parent: int, name: str, where: Path) -> int | None:
    """Open one directory below another without following a link, or answer None if it is absent."""
    try:
        opened = os.open(name, _DIRECTORY_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise StateRefused(STATE_IS_A_LINK, where=str(where)) from error
        raise StateRefused(STATE_UNCHECKED, where=str(where), detail=str(error)) from error
    try:
        if os.fstat(opened).st_uid != os.getuid():
            raise StateRefused(STATE_NOT_YOURS, where=str(where))
    except BaseException:
        os.close(opened)
        raise
    return opened


@contextmanager
def _held(directory: Path) -> Generator[tuple[int, int] | None]:
    """Hold a state directory and the directory it sits in, or None where it is not there."""
    absolute = directory.absolute()
    holder = absolute.parent
    try:
        project = os.open(holder.parent, os.O_RDONLY | os.O_DIRECTORY)
    except (FileNotFoundError, NotADirectoryError):
        yield None
        return
    except OSError as error:
        raise StateRefused(STATE_UNCHECKED, where=str(directory), detail=str(error)) from error
    try:
        above = _open_below(project, holder.name, holder)
    finally:
        os.close(project)
    if above is None:
        yield None
        return
    try:
        if os.fstat(above).st_mode & stat.S_IWOTH:
            raise StateRefused(STATE_WRITABLE, where=str(holder))
        state = _open_below(above, absolute.name, absolute)
        if state is None:
            yield None
            return
        try:
            yield above, state
        finally:
            os.close(state)
    finally:
        os.close(above)


def _refuse_entries(state: int, directory: Path) -> None:
    """Refuse a link, a special file or another user's file directly inside a state directory."""
    with os.scandir(state) as entries:
        for entry in entries:
            status = entry.stat(follow_symlinks=False)
            where = str(directory / entry.name)
            if not (stat.S_ISREG(status.st_mode) or stat.S_ISDIR(status.st_mode)):
                raise StateRefused(STATE_IS_A_LINK, where=where)
            if status.st_uid != os.getuid():
                raise StateRefused(STATE_NOT_YOURS, where=where)


def check_state_directory(directory: Path) -> None:
    """Refuse a state directory an instance should not open; one not there yet is fine."""
    with _held(directory) as held:
        if held is not None:
            _, state = held
            if os.fstat(state).st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise StateRefused(STATE_WRITABLE, where=str(directory))
            _refuse_entries(state, directory)
    _refuse_tracked(directory)


def check_state(settings: Settings) -> None:
    """Refuse the state directory these settings would open, if they open one."""
    database = settings.sqlite_path
    if database is not None and is_state_directory(database.parent):
        check_state_directory(database.parent)


def clear_state_directory(directory: Path) -> bool:
    """Delete a state directory, answering whether there was one, and never through a link.

    Writable modes and links inside it are not refused: deleting them is what clears them.
    """
    _refuse_tracked(directory)
    with _held(directory) as held:
        if held is None:
            return False
        above, _ = held
        shutil.rmtree(directory.name, dir_fd=above)
    return True


def _refuse_tracked(directory: Path) -> None:
    """Refuse a state directory the enclosing git repository tracks anything under."""
    absolute = Path(os.path.abspath(directory))
    try:
        found = _find_index(absolute)
        if found is None:
            return
        top, index = found
        data = _read_regular(index)
        if data is None:
            return
        tracked = _tracked_paths(data, index.parent)
    except (OSError, ValueError, struct.error, UnicodeDecodeError) as error:
        raise StateRefused(STATE_UNCHECKED, where=str(directory), detail=str(error)) from error
    prefix = absolute.relative_to(top).as_posix().casefold()
    # A case-insensitive filesystem opens .DIRIGENT/STATE when asked for .dirigent/state.
    for path in tracked:
        name = os.fsdecode(path).casefold()
        if prefix == "." or name == prefix or name.startswith(f"{prefix}/"):
            raise StateRefused(STATE_TRACKED, where=str(directory), repository=str(top))


def _find_index(start: Path) -> tuple[Path, Path] | None:
    """Find the innermost repository holding a path, as its working tree and its index file."""
    for top in (start, *start.parents):
        marker = top / ".git"
        try:
            status = marker.stat()
        except OSError:
            continue
        if stat.S_ISDIR(status.st_mode):
            return top, marker / "index"
        text = _read_regular(marker)
        if text is None or not text.startswith(b"gitdir:"):
            raise ValueError(f"{marker} names no repository")
        return top, top / os.fsdecode(text.removeprefix(b"gitdir:").strip()) / "index"
    return None


def _read_regular(path: Path) -> bytes | None:
    """Read a regular file without following a link, or answer None if it is absent."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as opened:
        if not stat.S_ISREG(os.fstat(opened.fileno()).st_mode):
            raise ValueError(f"{path} is not a regular file")
        return opened.read()


def _tracked_paths(data: bytes, directory: Path) -> list[bytes]:
    """List the paths an index holds, with those of the shared index a split one links to."""
    if data[:4] != b"DIRC":
        raise ValueError("not a git index")
    version, count = struct.unpack_from(">LL", data, 4)
    if version not in (2, 3, 4):
        raise ValueError(f"git index version {version}")
    # The width is the repository's own and nothing in the index says which it is.
    for size in _OBJECT_NAME_SIZES:
        try:
            paths, end = _read_entries(data, version, count, size)
        except (ValueError, struct.error, IndexError):
            continue
        shared = _shared_index_name(data, end, size)
        if shared is None:
            return paths
        base = _read_regular(directory / f"sharedindex.{shared}")
        if base is None:
            raise ValueError(f"the shared index {shared} is missing")
        return [*paths, *_tracked_paths(base, directory)]
    raise ValueError("a git index that does not parse")


def _read_entries(data: bytes, version: int, count: int, name_size: int) -> tuple[list[bytes], int]:
    """Walk an index's entries, failing on the first that is not one, and answer where they end."""
    paths: list[bytes] = []
    previous = b""
    offset = _INDEX_HEADER_SIZE
    fixed = _ENTRY_STAT_SIZE + name_size + _FLAGS_SIZE
    for _ in range(count):
        mode = struct.unpack_from(">L", data, offset + _MODE_OFFSET)[0]
        if mode >> 12 not in _ENTRY_TYPES:
            raise ValueError("not an index entry")
        flags = struct.unpack_from(">H", data, offset + fixed - _FLAGS_SIZE)[0]
        size = fixed + (_FLAGS_SIZE if version >= 3 and flags & _EXTENDED_FLAG else 0)
        start = offset + size
        if version == 4:
            strip, start = _read_varint(data, start)
            if strip > len(previous):
                raise ValueError("not an index entry")
            end = data.index(b"\0", start)
            path = previous[: len(previous) - strip] + data[start:end]
            offset = end + 1
        else:
            end = data.index(b"\0", start)
            path = data[start:end]
            offset += (size + len(path) + 8) & ~7
        if flags & _NAME_LENGTH_MASK != min(len(path), _NAME_LENGTH_MASK):
            raise ValueError("not an index entry")
        paths.append(path)
        previous = path
    return paths, offset


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read the prefix length a version 4 entry starts with, and answer where its name starts."""
    byte = data[offset]
    offset += 1
    value = byte & 0x7F
    while byte & 0x80:
        byte = data[offset]
        offset += 1
        value = ((value + 1) << 7) + (byte & 0x7F)
    return value, offset


def _shared_index_name(data: bytes, offset: int, name_size: int) -> str | None:
    """Name the shared index a split index links to, or None when it stands alone."""
    while offset + _EXTENSION_HEADER_SIZE + name_size <= len(data):
        signature = data[offset : offset + 4]
        length = struct.unpack_from(">L", data, offset + 4)[0]
        body = offset + _EXTENSION_HEADER_SIZE
        if signature == _SPLIT_INDEX_EXTENSION:
            name = data[body : body + name_size]
            return name.hex() if any(name) else None
        offset = body + length
    return None
