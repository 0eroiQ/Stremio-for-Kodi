#!/usr/bin/env python3
"""Create/update GitHub issues from the sanitized aggregate report feed.

This runs inside the Stremio-for-Kodi repository and uses only that repository's
short-lived GITHUB_TOKEN. The Cloudflare intake never receives GitHub credentials.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = os.environ.get(
    "REPORTS_ENDPOINT",
    "https://vortexo.app/api/stremio-kodi/v1/reports"
)
REPOSITORY = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
MAX_NEW_ISSUES = 10


def request_json(url, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "stremio-for-kodi-error-sync",
            **({"Authorization": "Bearer " + TOKEN} if "api.github.com" in url else {}),
            **({"X-GitHub-Api-Version": "2022-11-28"} if "api.github.com" in url else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(1024 * 1024)
    return json.loads(raw or b"{}")


def iso(epoch):
    return datetime.fromtimestamp(int(epoch or 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def issue_body(report):
    stack = "\n".join(report.get("stack") or []) or "No automatic stack was captured."
    return f"""## Automatic anonymous error report

- Error ID: `{report['fingerprint']}`
- Reports: **{int(report.get('reportCount') or 0)}**
- First seen: {iso(report.get('firstSeen'))}
- Last seen: {iso(report.get('lastSeen'))}
- Context: `{report.get('context', 'unknown')}`
- Error type: `{report.get('errorType', 'unknown')}`
- Stremio for Kodi: `{report.get('addonVersion', 'unknown')}`
- Kodi: `{report.get('kodiVersion', 'unknown')}`
- Platform: `{report.get('platform', 'unknown')}`
- Python: `{report.get('pythonVersion', 'unknown')}`

### Sanitized stack

```text
{stack}
```

This issue is maintained automatically from aggregated anonymous technical reports.
The client does not send Stremio tokens, addon/provider URLs, API keys, media URLs,
account details, device identifiers, local filesystem paths, or raw exception messages.
"""


def title(report):
    context = re.sub(r"[^A-Za-z0-9 ._+()\-]", "", str(report.get("context") or "Unknown error")).strip()
    return f"[Auto Report] {context[:70]} — {report['fingerprint']}"


def find_issue(fingerprint):
    query = urllib.parse.quote(f"repo:{REPOSITORY} is:issue in:title {fingerprint}")
    data = request_json(f"https://api.github.com/search/issues?q={query}&per_page=10")
    for item in data.get("items", []):
        if fingerprint in (item.get("title") or ""):
            return item
    return None


def sync():
    feed = request_json(ENDPOINT)
    reports = feed.get("reports") or []
    if feed.get("schemaVersion") != 1 or not isinstance(reports, list):
        raise RuntimeError("unexpected report feed")

    created = 0
    updated = 0
    for report in reports[:100]:
        fingerprint = str(report.get("fingerprint") or "")
        if not re.fullmatch(r"[0-9a-f]{12}", fingerprint):
            continue
        existing = find_issue(fingerprint)
        body = issue_body(report)
        issue_title = title(report)
        if existing:
            # Closed reports remain closed; a human may have intentionally resolved them.
            if existing.get("state") != "open":
                continue
            issue = request_json(existing["url"])
            if issue.get("body") != body or issue.get("title") != issue_title:
                request_json(
                    f"https://api.github.com/repos/{REPOSITORY}/issues/{existing['number']}",
                    method="PATCH",
                    body={"title": issue_title, "body": body},
                )
                updated += 1
            continue

        if created >= MAX_NEW_ISSUES:
            continue
        request_json(
            f"https://api.github.com/repos/{REPOSITORY}/issues",
            method="POST",
            body={"title": issue_title, "body": body},
        )
        created += 1

    print(f"error report sync: created={created} updated={updated} feed={len(reports)}")


if __name__ == "__main__":
    try:
        sync()
    except Exception as error:
        print(f"error report sync failed: {type(error).__name__}", file=sys.stderr)
        raise
