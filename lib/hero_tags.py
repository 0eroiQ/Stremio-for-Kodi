"""Map provider metadata to Nimbus FlixInfoIcon labels."""
import re
from datetime import date as calendar_date


def tags(row):
    date = str(row.get('released') or row.get('releaseInfo') or row.get('year') or '')
    # Avoid strptime's lazy module import in Kodi's embedded Python sessions.
    match_date = re.match(r'^(\d{4})-(\d{2})-(\d{2})(?:T|$)', date)
    if match_date:
        try:
            year, month, day = map(int, match_date.groups())
            calendar_date(year, month, day)
            date = '{:02d}/{:02d}/{:04d}'.format(day, month, year)
        except ValueError:
            pass
    runtime = str(row.get('runtime') or '')
    match = re.fullmatch(r'(\d+)\s*(?:min|mins|minutes)?', runtime.strip(), re.I)
    if match:
        minutes = int(match[1])
        runtime = '{} HR {} MINS'.format(minutes // 60, minutes % 60) if minutes >= 60 else '{} MINS'.format(minutes)
    return {'premiered': date, 'certificate':str(row.get('certification') or row.get('mpaa') or ''),
            'genre_tag':' '.join((row.get('genres') or [])[:2]), 'runtime_tag':runtime}
