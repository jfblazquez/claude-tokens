"""Commits and files of a conversation's folder, behind the links the web UI draws on hashes and file names."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

GIT_TIMEOUT = 20
COMMIT = re.compile(r"[0-9a-f]{7,40}")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
MAX_REFS = 500
MAX_MATCHES = 50
MAX_FILE_BYTES = 2 << 20
MAX_DIFF_BYTES = 4 << 20
MAX_NAME_CHARS = 1024
MAX_DIR_ENTRIES = 5000
MAX_STATS = 200
# Untracked files come and go while a session works; the index file only changes with git add and checkouts.
INDEX_TTL = 10.0


class RepoError(Exception):
    pass


def git(cwd, *args, text=None, timeout=GIT_TIMEOUT):
    """stdout of a git command as bytes, or None when it fails or git is missing."""
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], input=text.encode("utf-8") if text is not None else None,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def repo_root(cwd):
    if not cwd or not Path(cwd).is_dir():
        return None
    out = git(cwd, "rev-parse", "--show-toplevel")
    return Path(out.decode("utf-8", "replace").strip()) if out else None


def find_commits(cwd, candidates):
    """{candidate: {sha, subject, author, date}} for the candidates that name a commit in cwd's repository."""
    wanted = sorted({c for c in candidates if isinstance(c, str) and COMMIT.fullmatch(c)})[:MAX_REFS]
    if not wanted or repo_root(cwd) is None:
        return {}
    out = git(cwd, "cat-file", "--batch-check=%(objectname) %(objecttype)", text="".join(f"{c}^{{commit}}\n" for c in wanted))
    if out is None:
        return {}
    shas = {}
    for candidate, line in zip(wanted, out.decode("utf-8", "replace").splitlines()):
        fields = line.split()
        if len(fields) == 2 and fields[1] == "commit" and FULL_SHA.fullmatch(fields[0]):
            shas[candidate] = fields[0]
    if not shas:
        return {}
    log = git(cwd, "show", "-s", "--no-walk=unsorted", "--format=%H%x1f%s%x1f%an%x1f%as%x1e", *sorted(set(shas.values())))
    info = {}
    for record in (log or b"").decode("utf-8", "replace").split("\x1e"):
        fields = record.strip("\n").split("\x1f")
        if len(fields) == 4:
            info[fields[0]] = {"sha": fields[0], "subject": fields[1], "author": fields[2], "date": fields[3]}
    return {c: info.get(sha, {"sha": sha}) for c, sha in shas.items()}


class FileIndex:
    """Basename -> repository paths, per repository root, so a name resolves without walking the tree."""

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}

    def get(self, root):
        try:
            stamp = os.stat(root / ".git" / "index").st_mtime_ns
        except OSError:
            stamp = None
        now = time.monotonic()
        with self.lock:
            entry = self.entries.get(root)
            if entry and entry[0] == stamp and now - entry[1] < INDEX_TTL:
                return entry[2]
        out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        index = {}
        for rel in sorted(set((out or b"").decode("utf-8", "replace").split("\0"))):
            if rel:
                index.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
        with self.lock:
            self.entries[root] = (stamp, now, index)
        return index


def display(path, root):
    if root is not None:
        try:
            return str(Path(path).relative_to(root))
        except ValueError:
            pass
    return str(path)


def find_files(cwd, names, index):
    """{name: [{path, display}]} for the names that are files: as a path from cwd or absolute, or the end of a path in
    cwd's repository. A bare name can match several files."""
    root = repo_root(cwd)
    files = index.get(root) if root is not None else {}
    found = {}
    for name in sorted({n for n in names if isinstance(n, str) and 0 < len(n) <= MAX_NAME_CHARS})[:MAX_REFS]:
        clean = name[2:] if name.startswith("./") else name
        paths = []
        direct = Path(os.path.expanduser(clean))
        if not direct.is_absolute() and cwd:
            direct = Path(cwd) / direct
        if direct.is_file():
            paths.append(Path(os.path.normpath(direct)))
        # ./x, ../x, /x and ~/x say where the file is; only a plain relative name may be anywhere in the repository.
        if root is not None and not name.startswith(("./", "../", "/", "~")):
            for rel in files.get(clean.rstrip("/").rsplit("/", 1)[-1], ()):
                if rel == clean or rel.endswith("/" + clean):
                    paths.append(root / rel)
        unique = list(dict.fromkeys(paths))[:MAX_MATCHES]
        if unique:
            found[name] = [{"path": str(p), "display": display(p, root)} for p in unique]
    return found


def read_file(cwd, path):
    """A file's text for the viewer; binary files and the bytes past MAX_FILE_BYTES are left out."""
    if not isinstance(path, str) or not path or len(path) > MAX_NAME_CHARS:
        raise RepoError("expected a file path")
    target = Path(os.path.expanduser(path))
    if not target.is_absolute():
        if not cwd:
            raise RepoError("relative path without a folder")
        target = Path(cwd) / target
    try:
        info = target.stat()
        if not target.is_file():
            raise RepoError("not a file")
        with target.open("rb") as f:
            data = f.read(MAX_FILE_BYTES)
    except OSError as error:
        raise RepoError(f"cannot read the file: {error.strerror or error}") from None
    root = repo_root(target.parent)
    binary = b"\0" in data[:8192]
    return {"path": str(target), "display": display(target, root), "root": str(root) if root else None, "size": info.st_size,
            "mtime": info.st_mtime, "stamp": stamp(info), "binary": binary, "truncated": info.st_size > len(data),
            "text": "" if binary else data.decode("utf-8", "replace")}


def stamp(info):
    """What changes when a file is written or a folder gains, loses or renames an entry."""
    return f"{info.st_mtime_ns}:{info.st_size}:{info.st_ino}"


def absolute(cwd, path):
    if not isinstance(path, str) or len(path) > MAX_NAME_CHARS:
        raise RepoError("expected a path")
    target = Path(os.path.expanduser(path or "."))
    if not target.is_absolute():
        if not cwd:
            raise RepoError("relative path without a folder")
        target = Path(cwd) / target
    return Path(os.path.normpath(target))


def stat_paths(paths):
    """{path: {type, size, mtime, stamp} or None when it is gone} for the absolute paths that open panels show."""
    stats = {}
    for path in [p for p in paths if isinstance(p, str) and os.path.isabs(p) and len(p) <= MAX_NAME_CHARS][:MAX_STATS]:
        try:
            info = os.stat(path)
        except OSError:
            stats[path] = None
            continue
        stats[path] = {"type": "dir" if os.path.isdir(path) else "file", "size": info.st_size, "mtime": info.st_mtime,
                       "stamp": stamp(info)}
    return stats


def list_dir(cwd, path):
    """A folder's entries, folders first, with the ones git ignores marked; the folder of the conversation by default."""
    target = absolute(cwd, path)
    try:
        info = target.stat()
        if not target.is_dir():
            raise RepoError("not a folder")
        names = sorted(os.listdir(target), key=lambda n: (n.lower(), n))
    except OSError as error:
        raise RepoError(f"cannot read the folder: {error.strerror or error}") from None
    entries = []
    for name in names[:MAX_DIR_ENTRIES]:
        full = target / name
        try:
            link = full.is_symlink()
            st = full.stat() if not link or full.exists() else full.lstat()
        except OSError:
            continue
        kind = "dir" if full.is_dir() else "file" if full.is_file() else "other"
        entries.append({"name": name, "type": kind, "link": link, "size": st.st_size if kind == "file" else None,
                        "mtime": st.st_mtime})
    entries.sort(key=lambda e: e["type"] != "dir")
    root = repo_root(target)
    if root is not None and entries:
        ignored = git(target, "check-ignore", "--stdin", "-z", text="".join(f"{e['name']}\0" for e in entries))
        hidden = set((ignored or b"").decode("utf-8", "replace").split("\0"))
        for e in entries:
            e["ignored"] = e["name"] in hidden or e["name"] == ".git"
    return {"path": str(target), "display": display(target, root), "root": str(root) if root else None,
            "parent": str(target.parent) if target.parent != target else None, "stamp": stamp(info), "entries": entries,
            "truncated": len(names) > MAX_DIR_ENTRIES}


def show_commit(cwd, sha):
    """A commit's header, changed files and patch against its first parent (all of it for a root commit)."""
    if not isinstance(sha, str) or not COMMIT.fullmatch(sha) or repo_root(cwd) is None:
        raise RepoError("unknown commit")
    head = git(cwd, "show", "-s", "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%cI%x1f%D%x1f%B", f"{sha}^{{commit}}", "--")
    if head is None:
        raise RepoError("unknown commit")
    fields = head.decode("utf-8", "replace").split("\x1f", 8)
    full, parents = fields[0], fields[1].split()
    span = [parents[0], full] if parents else ["--root", full]
    numstat = git(cwd, "diff-tree", "-r", "-M", "--numstat", "-z", "--no-commit-id", *span) or b""
    patch = git(cwd, "diff-tree", "-r", "-M", "-p", "--no-color", "--no-commit-id", *span, timeout=60) or b""
    return {"sha": full, "parents": parents, "author": fields[2], "author_email": fields[3], "author_date": fields[4],
            "committer": fields[5], "committer_date": fields[6], "refs": fields[7], "message": fields[8].rstrip("\n"),
            "files": numstat_files(numstat.decode("utf-8", "replace")), "root": str(repo_root(cwd)),
            "patch": patch[:MAX_DIFF_BYTES].decode("utf-8", "replace"), "truncated": len(patch) > MAX_DIFF_BYTES}


def numstat_files(text):
    """diff-tree -z --numstat: 'added\\tdeleted\\tpath\\0', or 'added\\tdeleted\\t\\0old\\0new\\0' for a rename."""
    files, parts, i = [], text.split("\0"), 0
    while i < len(parts) and parts[i]:
        added, deleted, path = (parts[i].split("\t", 2) + ["", ""])[:3]
        entry = {"added": None if added == "-" else int(added or 0), "deleted": None if deleted == "-" else int(deleted or 0)}
        if path:
            entry["path"] = path
            i += 1
        else:
            entry.update({"old_path": parts[i + 1] if i + 1 < len(parts) else "", "path": parts[i + 2] if i + 2 < len(parts) else ""})
            i += 3
        files.append(entry)
    return files
