"""Short-lived weather settings entry, independent of the running Home shell."""
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent
for directory in (BASE, BASE / 'core'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

def main():
    from lib.weather_setup import configure_weather
    action = next((value for value in sys.argv[1:]
                   if value in ('country', 'postcode', 'city', 'menu')), 'menu')
    if configure_weather(action=action):
        from lib.weather_widget import request_refresh
        request_refresh(force=True)

if __name__ == '__main__':
    main()
