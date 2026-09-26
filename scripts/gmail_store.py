"""Owner-only local Gmail OAuth credential storage (no keyring required).

Desktop OAuth clients cannot keep secrets from the owner of the machine. This
store never places credentials in DMS settings, source code or argv. The files
are not encrypted at rest; protect the user's login and home directory.
"""

import hashlib
import os
import stat
import tempfile


def storage_root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    root = os.path.join(base, "dms-mail-reader-gmail")
    os.makedirs(root, mode=0o700, exist_ok=True)
    info = os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Unsafe Gmail credential directory")
    os.chmod(root, 0o700)
    return root


def filename(kind, identity):
    if kind not in ("client", "tokens"):
        raise ValueError("Unknown credential type")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return os.path.join(storage_root(), f"{kind}-{digest}.txt")


def load(kind, identity):
    path = filename(kind, identity)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise RuntimeError("Cannot read Gmail credential file") from exc
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise RuntimeError("Unsafe Gmail credential file permissions")
        return handle.read()


def save(kind, identity, value):
    path = filename(kind, identity)
    fd, temporary = tempfile.mkstemp(prefix=".credential-", dir=storage_root())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
