"""Map provider metadata to Nimbus FlixInfoIcon labels."""
import re
from datetime import datetime


def tags(row):
    date = str(row.get('released') or row.get('releaseInfo') or row.get('year') or '')
    try:
        date = datetime.strptime(date[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        pass
    runtime = str(row.get('runtime') or '')
    match = re.fullmatch(r'(\d+)\s*(?:min|mins|minutes)?', runtime.strip(), re.I)
    if match:
        minutes = int(match[1])
        runtime = '{} HR {} MINS'.format(minutes // 60, minutes % 60) if minutes >= 60 else '{} MINS'.format(minutes)
    return {'premiered': date, 'certificate':str(row.get('certification') or row.get('mpaa') or ''),
            'genre_tag':' '.join((row.get('genres') or [])[:2]), 'runtime_tag':runtime}
