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
import urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.report_feedback import CATEGORIES, report_labels, validate_feedback
from datetime import datetime, timezone

ENDPOINT = os.environ.get(
    "REPORTS_ENDPOINT",
    "https://vortexo.app/api/stremio-kodi/v1/reports"
)
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "0eroiQ/Stremio-for-Kodi")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MAX_NEW_ISSUES = 10


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Unexpected report-sync redirect')


def request_json(url, method="GET", body=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Unsafe sync endpoint')
    github = parsed.netloc.lower() in ('api.github.com', 'api.github.com:443')
    headers = {'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
               'User-Agent': 'stremio-for-kodi-error-sync'}
    if github:
        headers.update({'Authorization': 'Bearer ' + TOKEN, 'X-GitHub-Api-Version': '2022-11-28'})
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode('utf-8'),
                                     method=method, headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Report-sync response too large')
    return json.loads(raw or b'{}')


def iso(epoch):
    return datetime.fromtimestamp(int(epoch or 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def issue_body(report):
    feedback = report.get('feedback')
    if feedback is not None:
        feedback = validate_feedback(feedback)
    performance = report.get('errorType') == 'PerformanceReport'
    manual = report.get('errorType') in ('ManualReport', 'FeatureRequest')
    heading = ('Performance report' if performance else
               'Feature request' if feedback and feedback['kind'] == 'feature' else
               'Manual bug report' if feedback else 'Manual report - details needed' if manual else
               'Automatic anonymous error report')
    stack = '\n'.join(report.get('stack') or []) or 'No automatic stack was captured.'
    content = ''
    if performance:
        timings = report.get('performance') if isinstance(report.get('performance'), dict) else {}
        safe = []
        for stage in sorted(timings):
            values = timings.get(stage) if isinstance(timings.get(stage), dict) else {}
            safe.append('- `{}`: **{} ms** · rows={} · items={}'.format(
                stage, int(values.get('ms') or 0), int(values.get('rows') or 0), int(values.get('items') or 0)))
        content = '\n### Home performance timings\n\n' + ('\n'.join(safe) or 'No timing samples were supplied.') + '\n'
    elif feedback:
        content = ('\n### User-submitted feedback\n\n```text\n' + feedback['title'] + '\n\n' +
                   feedback['description'] + '\n```\n\nCategory: ' + feedback['category'] +
                   '\n\nFrequency: ' + feedback['frequency'] + '\n')
    elif manual:
        content = '\nNo symptom or description was supplied by this older addon. More information is needed; this is not evidence of a specific crash.\n'
    return (f"## {heading}\n\n- Error ID: `{report['fingerprint']}`\n"
            f"- Reports: **{int(report.get('reportCount') or 0)}**\n"
            f"- First seen: {iso(report.get('firstSeen'))}\n- Last seen: {iso(report.get('lastSeen'))}\n"
            f"- Context: `{report.get('context', 'unknown')}`\n- Error type: `{report.get('errorType', 'unknown')}`\n"
            f"- Stremio for Kodi: `{report.get('addonVersion', 'unknown')}`\n"
            f"- Kodi: `{report.get('kodiVersion', 'unknown')}`\n- Platform: `{report.get('platform', 'unknown')}`\n"
            f"- Python: `{report.get('pythonVersion', 'unknown')}`\n" + content +
            '\n### Sanitized stack\n\n```text\n' + stack + '\n```\n\n' +
            ('The title and description above were explicitly submitted for public feedback. No account data or raw logs are attached.\n' if feedback else
             'This issue contains anonymous technical diagnostics only, not account details, raw exception messages or device paths.\n'))


def title(report):
    feedback = report.get('feedback')
    if feedback is not None:
        feedback = validate_feedback(feedback)
        prefix = 'Feature Request' if feedback['kind'] == 'feature' else 'Bug Report'
        return '[{}] {} - {}'.format(prefix, feedback['title'][:85], report['fingerprint'])
    context = re.sub(r'[^A-Za-z0-9 ._+()\-]', '', str(report.get('context') or 'Unknown error')).strip()
    prefix = ('Performance' if report.get('errorType') == 'PerformanceReport' else
              'Manual Report' if report.get('errorType') == 'ManualReport' else 'Auto Report')
    return '[{}] {} - {}'.format(prefix, context[:70], report['fingerprint'])


LABELS = {'bug': ('d73a4a', 'Something is not working'),
          'performance': ('5319e7', 'Performance report from Stremio for Kodi'),
          'feature-request': ('a2eeef', 'User-requested improvement'),
          'needs-triage': ('fbca04', 'New report awaiting maintainer review'),
          'needs-info': ('d4c5f9', 'Insufficient detail to diagnose'),
          'source:manual': ('bfd4f2', 'Explicitly submitted in the addon'),
          'source:auto': ('c5def5', 'Automatic anonymous diagnostics')}
LABELS.update({'area:' + key: ('c2e0c6', 'Report category: ' + label) for key, label in CATEGORIES})
LABELS.update({'platform:' + key: ('ededed', 'Reported platform: ' + key)
               for key in ('android', 'windows', 'macos', 'linux', 'ios', 'tvos', 'unknown')})
_LABEL_CACHE = set()


def ensure_labels(names):
    for name in names:
        if name not in LABELS:
            raise ValueError('Unsupported issue label')
        if name in _LABEL_CACHE:
            continue
        endpoint = 'https://api.github.com/repos/{}/labels/{}'.format(REPOSITORY, urllib.parse.quote(name, safe=''))
        try:
            request_json(endpoint)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            color, description = LABELS[name]
            try:
                request_json('https://api.github.com/repos/{}/labels'.format(REPOSITORY), 'POST',
                             {'name': name, 'color': color, 'description': description})
            except urllib.error.HTTPError as race:
                if race.code != 422:
                    raise
                request_json(endpoint)  # Another workflow may have created it.
        _LABEL_CACHE.add(name)


def find_issue(fingerprint):
    query = urllib.parse.quote(f"repo:{REPOSITORY} is:issue in:title {fingerprint}")
    data = request_json(f"https://api.github.com/search/issues?q={query}&per_page=10")
    for item in data.get("items", []):
        if fingerprint in (item.get("title") or ""):
            return item
    return None


def sync():
    if not TOKEN or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', REPOSITORY):
        raise RuntimeError('Repository and workflow token are required')
    feed = request_json(ENDPOINT)
    reports = feed.get('reports') or []
    if feed.get('schemaVersion') != 1 or not isinstance(reports, list):
        raise RuntimeError('Unexpected report feed')
    created = updated = tagged = 0
    for report in reports[:100]:
        if not isinstance(report, dict):
            continue
        fingerprint = str(report.get('fingerprint') or '')
        if not re.fullmatch(r'[0-9a-f]{12}', fingerprint):
            continue
        try:
            labels = report_labels(report)
            body, issue_title = issue_body(report), title(report)
        except (ValueError, TypeError, KeyError):
            continue
        existing = find_issue(fingerprint)
        if existing:
            number = int(existing['number'])
            endpoint = 'https://api.github.com/repos/{}/issues/{}'.format(REPOSITORY, number)
            issue = request_json(endpoint)
            current = {v if isinstance(v, str) else v.get('name') for v in issue.get('labels', [])}
            missing = [v for v in labels if v not in current]
            if missing:
                ensure_labels(missing)
                request_json(endpoint + '/labels', 'POST', {'labels': missing})
                tagged += 1
            # Label backfill never reopens an issue or replaces a maintainer's labels.
            if issue.get('state') == 'open' and (issue.get('body') != body or issue.get('title') != issue_title):
                request_json(endpoint, 'PATCH', {'title': issue_title, 'body': body})
                updated += 1
            continue
        if created >= MAX_NEW_ISSUES:
            continue
        labels = report_labels(report, initial=True)
        ensure_labels(labels)
        request_json('https://api.github.com/repos/{}/issues'.format(REPOSITORY), 'POST',
                     {'title': issue_title, 'body': body, 'labels': labels})
        created += 1
    print('report sync: created={} updated={} tagged={} feed={}'.format(created, updated, tagged, len(reports)))


if __name__ == "__main__":
    try:
        sync()
    except Exception as error:
        print(f"error report sync failed: {type(error).__name__}", file=sys.stderr)
        raise
