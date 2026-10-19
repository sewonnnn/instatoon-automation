from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, message, code="invalid_input"):
    if not condition:
        raise ToolError(code, message)


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value), "Invalid identifier")
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, value):
        require(isinstance(value, str) and value, "Expected a repository-relative path")
        path = (self.root / value).resolve()
        require(path.is_relative_to(self.root), "Path must stay inside the workspace")
        return path

    def output(self, value):
        path = self.path(value)
        require(path.is_relative_to(self.root / "outputs") and path != self.root / "outputs", "Output must be under outputs/")
        return path

    def relative(self, path):
        return str(Path(path).resolve().relative_to(self.root))

    def artifact(self, path, role):
        return {"path": self.relative(path), "sha256": digest(path), "role": role}

    def verify(self, ref):
        require(isinstance(ref, dict) and isinstance(ref.get("sha256"), str), "Artifact needs path and sha256")
        path = self.path(ref["path"])
        require(path.is_file(), f"Missing artifact: {ref['path']}", "missing_artifact")
        require(digest(path) == ref["sha256"], f"Changed artifact: {ref['path']}", "stale_artifact")
        return path


@contextmanager
def lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def new_directory(destination):
    """Publish a complete directory once, never overwrite an existing result."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with lock(destination.parent):
        require(not destination.exists(), f"Already exists: {destination.name}", "conflict")
        temp = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination.parent))
        try:
            yield temp
            os.rename(temp, destination)
        finally:
            if temp.exists():
                shutil.rmtree(temp)


def artifact_refs(value):
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            yield value
        for child in value.values():
            yield from artifact_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from artifact_refs(child)
