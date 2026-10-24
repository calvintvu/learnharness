"""Integration tests using a temporary Git remote and local activity API."""
import functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/backup-data.py"


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.run_command("git", "init", "--bare", "--initial-branch=main", str(self.remote))
        self.run_command("git", "init", "--initial-branch=main", str(self.repo))
        self.git("config", "user.name", "Backup Test")
        self.git("config", "user.email", "backup@example.invalid")
        (self.repo / "scripts").mkdir()
        shutil.copy2(SCRIPT, self.repo / "scripts/backup-data.py")
        (self.repo / "data").mkdir()
        self.data = self.repo / "data/session.json"
        self.data.write_text('{"turn": 1}\n')
        (self.repo / "app.txt").write_text("application code\n")
        (self.repo / ".gitignore").write_text(".secrets/\ndata/debug/\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "main")
        self.busy = False
        owner = self
        class API(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/activity":
                    value = {"jobs": [{}] if owner.busy else [], "extractions": []}
                else:
                    value = {"chats": [{"busy": False, "compacting": False}]}
                content = json.dumps(value).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), API)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def run_command(self, *args, cwd=None):
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def git(self, *args):
        return self.run_command("git", *args, cwd=self.repo)

    def backup(self, expected=0):
        env = {**os.environ, "LH_BACKUP_URL": f"http://127.0.0.1:{self.server.server_port}"}
        result = subprocess.run(
            ["python3", str(self.repo / "scripts/backup-data.py")],
            cwd=self.repo, env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_snapshot_push_excludes_secrets_and_code_then_noop(self):
        self.data.write_text('{"turn": 2}\n')
        (self.repo / "data/new.jsonl").write_text('{"node": "example"}\n')
        (self.repo / ".secrets").mkdir()
        (self.repo / ".secrets/auth.json").write_text('{"key":"local only"}\n')
        (self.repo / "data/debug").mkdir()
        (self.repo / "data/debug/log.json").write_text('{}\n')
        (self.repo / "app.txt").write_text("uncommitted code\n")
        self.backup()
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines(),
                         ["data/new.jsonl", "data/session.json"])
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/main").split()[0], head)
        self.assertEqual(self.git("status", "--porcelain"), "M app.txt")
        self.backup()
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_busy_defers_without_changing_history(self):
        head = self.git("rev-parse", "HEAD")
        self.busy = True
        self.data.write_text('{"turn": 2}\n')
        self.backup(expected=75)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(json.loads((self.repo / ".git/learnharness-backup.json").read_text())["status"], "deferred")

    def test_invalid_json_and_staged_code_are_preserved(self):
        head = self.git("rev-parse", "HEAD")
        self.data.write_text('{"incomplete":')
        self.backup(expected=1)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        (self.repo / "app.txt").write_text("staged code\n")
        self.git("add", "app.txt")
        self.backup(expected=75)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "app.txt")

    def test_failed_push_retries_existing_snapshot(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.data.write_text('{"turn": 2}\n')
        self.backup(expected=1)
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("status", "--porcelain"), "")
        hook.unlink()
        self.backup()
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/main").split()[0], head)

    def test_remote_changes_refuse_automatic_merge(self):
        other = self.root / "other"
        self.run_command("git", "clone", str(self.remote), str(other))
        run = functools.partial(self.run_command, cwd=other)
        run("git", "config", "user.name", "Other Test")
        run("git", "config", "user.email", "other@example.invalid")
        (other / "app.txt").write_text("remote changes\n")
        run("git", "add", ".")
        run("git", "commit", "-m", "remote update")
        run("git", "push", "origin", "main")
        head = self.git("rev-parse", "HEAD")
        self.data.write_text('{"turn": 2}\n')
        self.backup(expected=1)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_data_deletion_is_backed_up(self):
        self.data.unlink()
        self.backup()
        self.assertEqual(self.git("ls-tree", "HEAD", "--", "data"), "")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.backup()


if __name__ == "__main__":
    unittest.main()
