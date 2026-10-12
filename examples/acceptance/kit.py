"""A ready-made project for acceptance runs, so they start from a fixture
rather than building one each iteration.

    uv run python examples/acceptance/kit.py new DIR       # project + data
    uv run python examples/acceptance/kit.py rows DIR a orders 0
    uv run python examples/acceptance/kit.py rows DIR b customers none
    uv run python examples/acceptance/kit.py receiver DIR &  # webhook receiver
    uv run python examples/acceptance/kit.py status DIR 500  # make it fail
    uv run python examples/acceptance/kit.py crash DIR -- --run-key k1
    uv run python examples/acceptance/kit.py age-lock DIR    # as if 2 min passed

`new` writes two SQLite datasources (`a` holds `orders`, `b` holds
`customers`, each with a `row_count > 0` check notifying `hook`). `rows`
sets a table's row count, or drops it with `none` (the check then errors).
`receiver` listens on a free local port, writes its URL to `DIR/hook.url`
and every POST body as a line of `DIR/received.jsonl`, and answers with the
status in `DIR/hook.status` (200 when absent). Run tablewatch with
`TW_HOOK=$(cat DIR/hook.url)`. `crash` starts `tablewatch run` with the
arguments after `--` and kills it with SIGKILL as soon as the store has
recorded one dataset: a run that died mid-way. On SQLite its run-key lock
stays for 120 s after a kill (a retry before then exits 2, "another process
is already running"); `age-lock` makes every lock stale at once.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT = """\
name: acceptance
datasources:
  a: {type: sqlite, path: a.sqlite}
  b: {type: sqlite, path: b.sqlite}
notifiers:
  hook:
    type: webhook
    url: ${env:TW_HOOK}
"""
CHECK = """\
dataset: {table}
datasource: {source}
notify: hook

checks:
  {table}_present: row_count > 0
"""
TABLES = (("a", "orders"), ("b", "customers"))


def new(root: Path) -> None:
    (root / "checks").mkdir(parents=True, exist_ok=True)
    (root / "tablewatch.yml").write_text(PROJECT, encoding="utf-8")
    for source, table in TABLES:
        check = CHECK.format(table=table, source=source)
        (root / "checks" / f"{table}.yml").write_text(check, encoding="utf-8")
        rows(root, source, table, 3)
    print(f"project ready in {root}")


def rows(root: Path, source: str, table: str, count: int | None) -> None:
    db = sqlite3.connect(root / f"{source}.sqlite")
    try:
        db.execute(f'DROP TABLE IF EXISTS "{table}"')
        if count is not None:
            db.execute(f'CREATE TABLE "{table}" (k INTEGER)')
            db.executemany(
                f'INSERT INTO "{table}" VALUES (?)', [(i,) for i in range(count)]
            )
        db.commit()
    finally:
        db.close()


def receiver(root: Path) -> None:
    received = root / "received.jsonl"
    status_file = root / "hook.status"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with received.open("a", encoding="utf-8") as out:
                out.write(json.dumps(json.loads(body)) + "\n")
            status = int(status_file.read_text()) if status_file.exists() else 200
            self.send_response(status)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    (root / "hook.url").write_text(url, encoding="utf-8")
    print(f"receiving at {url}; bodies in {received}", flush=True)
    server.serve_forever()


def crash(root: Path, args: list[str]) -> None:
    store = root / ".tablewatch" / "results.db"
    command = ["tablewatch", "--project-dir", str(root), "run", *args]
    process = subprocess.Popen(command)
    deadline = time.monotonic() + 120
    while process.poll() is None and time.monotonic() < deadline:
        if _recorded(store):
            os.kill(process.pid, signal.SIGKILL)
            process.wait()
            print("killed after the first dataset was recorded")
            return
        time.sleep(0.01)
    print(f"the run ended (exit {process.returncode}) before it could be killed")


def age_lock(root: Path) -> None:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        db.execute(
            "UPDATE tablewatch_run_locks SET heartbeat_at = '2000-01-01 00:00:00'"
        )
        db.commit()
    finally:
        db.close()


def _recorded(store: Path) -> bool:
    if not store.exists():
        return False
    try:
        db = sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=0.1)
        try:
            return bool(
                db.execute("SELECT count(*) FROM tablewatch_dataset_runs").fetchone()[0]
            )
        finally:
            db.close()
    except sqlite3.Error:
        return False


def main(argv: list[str]) -> None:
    command, root = argv[0], Path(argv[1])
    if command == "new":
        new(root)
    elif command == "rows":
        count = None if argv[4] == "none" else int(argv[4])
        rows(root, argv[2], argv[3], count)
    elif command == "receiver":
        receiver(root)
    elif command == "status":
        (root / "hook.status").write_text(argv[2], encoding="utf-8")
    elif command == "age-lock":
        age_lock(root)
    elif command == "crash":
        crash(root, argv[argv.index("--") + 1 :] if "--" in argv else [])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
