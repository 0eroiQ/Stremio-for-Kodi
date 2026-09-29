"""Optional support screen. No payment API, account reads, or entitlement writes.

This is a separate short-lived entrypoint so opening support does not launch
another Home instance. The QR is bundled and works without a QR dependency.
"""
from pathlib import Path
import hashlib
import json
import re
import sys
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent
XML = 'stremio-support-development.xml'
BACK_ACTIONS = (10, 92, 216, 247)


def load_config(base=BASE):
    asset_dir = Path(base) / 'resources' / 'branding'
    raw = (asset_dir / 'support.json').read_bytes()
    if len(raw) > 4096:
        raise ValueError('Invalid support configuration')
    config = json.loads(raw)
    if not isinstance(config, dict) or config.get('schemaVersion') != 1:
        raise ValueError('Invalid support configuration')
    url = config.get('url', '')
    if not isinstance(url, str) or not re.fullmatch(
            r'https://(?:donate|buy)\.stripe\.com/(?:test_)?[A-Za-z0-9]+', url):
        raise ValueError('Unsupported support URL')
    is_test = urlsplit(url).path.startswith('/test_')
    if config.get('mode') != ('test' if is_test else 'live'):
        raise ValueError('Support mode does not match the link')
    qr = asset_dir / 'support-qr.png'
    qr_data = qr.read_bytes()
    if len(qr_data) > 1024 * 1024 or not qr_data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid support QR image')
    if hashlib.sha256(qr_data).hexdigest() != config.get('qr_sha256'):
        raise ValueError('Support QR integrity check failed')
    return url, is_test, qr


def dialog_class(gui):
    class SupportDialog(gui.WindowXMLDialog):
        def onInit(self):
            url, is_test, qr = load_config()
            self.getControl(101).setImage(str(qr), False)
            self.setProperty('support_url', url)
            self.setProperty('support_mode', 'TEST CHECKOUT - NO REAL PAYMENTS' if is_test
                             else 'Optional one-time developer tip')
            self.setProperty('support_help',
                'Scan the QR with your phone to preview the Stripe test page.\n\n'
                'This link cannot collect real donations. Do not enter real card details.'
                if is_test else
                'Scan the QR with your phone to support development on Stripe.\n\n'
                'Choose an amount you are comfortable with. Support is entirely optional.')
            self.setFocusId(1)

        def onClick(self, control_id):
            if control_id == 1:
                self.close()

        def onAction(self, action):
            if action.getId() in BACK_ACTIONS:
                self.close()

    return SupportDialog


def main():
    import xbmcgui
    # Validate before allocating the modal, including on partial installations.
    try:
        load_config()
        for folder in (BASE, BASE / 'core'):
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
        from lib.theme import window as themed_window
        window = themed_window(dialog_class(xbmcgui), XML, str(BASE), 'Main', '1080i')
        try:
            window.doModal()
        finally:
            del window
    except Exception:
        # Avoid logging exception contents or opening an unverified external URL.
        xbmcgui.Dialog().ok('Support Stremio for Kodi',
                           'The support screen is unavailable. Please try again later.')


if __name__ == '__main__':
    main()
