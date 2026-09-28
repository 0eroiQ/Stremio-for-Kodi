"""Fail closed if tracked source/history contains common credential signatures.

The scanner prints only pattern names and object/path locations, never secret values.
It is intentionally conservative and supplements (not replaces) GitHub secret scanning.
"""
import argparse
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "github_classic_pat": re.compile(rb"ghp_[A-Za-z0-9]{36}"),
    "github_fine_grained_pat": re.compile(rb"github_pat_[A-Za-z0-9_]{50,}"),
    "google_api_key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "stripe_live_secret": re.compile(rb"sk_live_[0-9A-Za-z]{20,}"),
    "stripe_live_publishable": re.compile(rb"pk_live_[0-9A-Za-z]{20,}"),
    "slack_token": re.compile(rb"xox[baprs]-[0-9A-Za-z-]{20,}"),
    "private_key_pem": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
}
SKIP = {".git"}


def scan_bytes(label, data):
    return [(name, label) for name, pattern in PATTERNS.items() if pattern.search(data)]


def scan_worktree(root):
    hits = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP for part in path.parts):
            continue
        try:
            hits.extend(scan_bytes(str(path.relative_to(root)), path.read_bytes()))
        except OSError:
            continue
    return hits


def scan_history():
    hits = []
    listed = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        check=True, capture_output=True, text=True
    ).stdout.splitlines()
    seen = set()
    for line in listed:
        sha, _, path = line.partition(" ")
        if not sha or sha in seen:
            continue
        seen.add(sha)
        kind = subprocess.run(
            ["git", "cat-file", "-t", sha],
            capture_output=True, text=True
        )
        if kind.returncode or kind.stdout.strip() != "blob":
            continue
        blob = subprocess.run(["git", "cat-file", "blob", sha], capture_output=True)
        if blob.returncode:
            continue
        label = (path or "<historical-blob>") + "@" + sha[:12]
        hits.extend(scan_bytes(label, blob.stdout))
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    hits = scan_worktree(Path.cwd())
    if args.history:
        hits.extend(scan_history())
    unique = sorted(set(hits))
    if unique:
        for name, location in unique:
            print("credential signature:", name, "at", location)
        raise SystemExit("Public-source credential audit failed.")
    print("Public-source credential audit passed; no known credential signatures found.")


if __name__ == "__main__":
    main()
