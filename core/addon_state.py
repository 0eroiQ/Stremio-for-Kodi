"""Shared add-on identity and non-destructive migration from the former core."""
from pathlib import Path
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
import xbmcaddon
import xbmcvfs

ADDON_ID = 'script.stremioelec'


def migrate_profile(source, target, set_setting):
    """Copy missing legacy files once; never remove or replace either profile."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    marker = target / '.core-migrated-v1'
    if marker.exists():
        return
    if source.is_dir():
        current = target / 'settings.xml'
        existing = {s.get('id') for s in ET.parse(current).iter('setting')} if current.exists() else set()
        old_settings = source / 'settings.xml'
        if old_settings.exists():
            for setting in ET.parse(old_settings).iter('setting'):
                key = setting.get('id')
                if key and key not in existing:
                    set_setting(key, setting.get('value', setting.text or ''))
        for old in source.rglob('*'):
            if not old.is_file() or old.is_symlink() or old.name.startswith('.') or old == old_settings:
                continue
            new = target / old.relative_to(source)
            if new.exists():
                continue
            new.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=new.parent, prefix='.migration-')
            try:
                with os.fdopen(fd, 'wb') as out, old.open('rb') as inp:
                    shutil.copyfileobj(inp, out)
                try:
                    os.link(temporary, new)  # Atomic publication; existing data wins.
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary)
    marker.touch()


def get_addon():
    addon = xbmcaddon.Addon(ADDON_ID)
    migrate_profile(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.stremioelec'),
                    xbmcvfs.translatePath(addon.getAddonInfo('profile')), addon.setSetting)
    return addon
