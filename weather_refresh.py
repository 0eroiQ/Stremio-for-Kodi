"""Short-lived background refresh for the addon-owned weather widget."""
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
for directory in (BASE, BASE / 'core'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


def main():
    try:
        from weather import refresh
        refresh(force='force' in sys.argv[1:])
    except Exception:
        # A failed weather request must not block launching the media addon.
        import xbmc
        xbmc.log('Stremio for Kodi: weather refresh unavailable', xbmc.LOGWARNING)


if __name__ == '__main__':
    main()
