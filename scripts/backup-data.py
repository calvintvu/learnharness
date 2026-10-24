#!/usr/bin/env python3
"""Back up an idle app's stable data snapshot; never pull, rebase, or force-push."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
ENV.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes")


class Deferred(Exception):
    pass


def git(*args, env=None, input=None):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, env=env or ENV, input=input,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or f"git {args[0]} failed")
    return result.stdout


def git_path(name):
    return ROOT / os.fsdecode(git("rev-parse", "--git-path", name).strip())


def record(status, message):
    path = git_path("learnharness-backup.json")
    previous = json.loads(path.read_text()) if path.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous.update(last_attempt=now, status=status, message=message)
    if status == "success":
        previous["last_success"] = now
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(previous, indent=2) + "\n")
    temporary.replace(path)
    print(f"{status.upper()}: {message}", flush=True)


def assert_idle():
    base = os.environ.get("LH_BACKUP_URL", "http://127.0.0.1:3000").rstrip("/")
    def read(path):
        with urlopen(base + path, timeout=10) as response:
            return json.load(response)
    activity = read("/api/activity")
    chats = read("/api/chats")
    if not isinstance(activity.get("jobs"), list) or not isinstance(activity.get("extractions"), list):
        raise RuntimeError("Unexpected activity API response")
    if not isinstance(chats.get("chats"), list):
        raise RuntimeError("Unexpected chats API response")
    if activity["jobs"] or activity["extractions"] or any(
        chat.get("busy") or chat.get("compacting") for chat in chats["chats"]
    ):
        raise Deferred("Learning or background work is active; retry later")


def snapshot():
    data = ROOT / "data"
    if not data.is_dir() or data.is_symlink():
        raise RuntimeError("Expected a real data/ directory in this checkout")
    names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "data")
    result = {}
    for raw in names.split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(data):
            raise RuntimeError(f"Refusing a symlink or escaped data path: {name}")
        if not path.exists():
            continue  # A deleted tracked file is removed from the snapshot's tree.
        try:
            stat = path.stat()
            if stat.st_size >= 100 * 1024 * 1024:
                raise RuntimeError(f"File exceeds regular GitHub storage limits: {name}")
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise Deferred("Data changed during the snapshot; retry later") from error
        result[name] = (content, 0o755 if stat.st_mode & 0o111 else 0o644)
    return result


def backup():
    if git("branch", "--show-current").strip() != b"main":
        raise Deferred("Checkout is not on main; retry after repository maintenance")
    for marker in ["rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"]:
        if git_path(marker).exists():
            raise Deferred("Git maintenance is in progress; retry later")
    if git("diff", "--cached", "--name-only"):
        raise Deferred("The Git index has staged changes; leave them for the user")
    head = git("rev-parse", "HEAD").strip().decode()
    git("fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main")
    remote = git("rev-parse", "origin/main").strip().decode()
    if git("merge-base", remote, head).strip().decode() != remote:
        raise RuntimeError("origin/main has changes missing locally; reconcile manually before backing up")

    assert_idle()
    first = snapshot()
    time.sleep(2)
    assert_idle()
    if first != snapshot():
        raise Deferred("Data changed during the snapshot; retry later")
    for name, (content, _) in first.items():
        if name.endswith(".json"):
            json.loads(content)
        elif name.endswith(".jsonl"):
            for line in content.splitlines():
                if line.strip():
                    json.loads(line)

    # Use a separate index and tree so code, secrets, and later live writes cannot
    # enter this commit. The original worktree and data files remain untouched.
    with tempfile.TemporaryDirectory(prefix="learnharness-backup-") as directory:
        temporary = Path(directory)
        worktree = temporary / "snapshot"
        (worktree / "data").mkdir(parents=True)
        for name, (content, mode) in first.items():
            target = worktree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
        env = {**ENV, "GIT_INDEX_FILE": str(temporary / "index")}
        git("read-tree", head, env=env)
        if first or git("ls-tree", head, "--", "data"):
            git(f"--work-tree={worktree}", "add", "--all", "--", "data", env=env)
        tree = git("write-tree", env=env).strip().decode()
        if tree != git("rev-parse", f"{head}^{{tree}}").strip().decode():
            if git("branch", "--show-current").strip() != b"main" or git("diff", "--cached", "--name-only"):
                raise Deferred("Repository changed during backup; retry later")
            message = "Back up learning data " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            commit = git("commit-tree", tree, "-p", head, "-m", message, env=env).strip().decode()
            git("update-ref", "-m", message, "refs/heads/main", commit, head)
            git("reset", "--quiet", commit, "--", "data")
            print(f"Created data snapshot {commit[:12]}", flush=True)
        else:
            print("No new data changes; checking for an unpushed backup", flush=True)

    # This also retries a previous failed push even when no new files changed.
    git("push", "--porcelain", "origin", "refs/heads/main:refs/heads/main")
    record("success", "Data is backed up to origin/main at " + git("rev-parse", "--short", "HEAD").decode().strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Show the last result, schedule, and recent logs")
    args = parser.parse_args()
    if args.status:
        path = git_path("learnharness-backup.json")
        print(path.read_text() if path.exists() else "No backup attempt recorded yet", flush=True)
        for command in [
            ["systemctl", "--user", "list-timers", "--all", "learnharness-backup.timer", "--no-pager"],
            ["journalctl", "--user", "-u", "learnharness-backup.service", "-n", "12", "--no-pager"],
        ]:
            subprocess.run(command, check=False)
        return 0
    with git_path("learnharness-backup.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another backup or rebase holds the repository lock", flush=True)
            return 75
        try:
            backup()
            return 0
        except Deferred as error:
            record("deferred", str(error))
            return 75
        except Exception as error:
            record("failed", str(error))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
