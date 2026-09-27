"""Manage only the addon response cache, preserving account and Kodi artwork."""
def cache_action(clear=False):
    from pathlib import Path
    import xbmcgui
    import xbmcvfs
    from addon_state import get_addon
    from lib.disk_cache import DiskCache
    directory = Path(xbmcvfs.translatePath(get_addon().getAddonInfo('profile'))) / 'cache'
    try:
        cache = DiskCache(directory)
        with cache.connect() as db:
            if clear:
                db.execute('DELETE FROM responses')
            count, size = db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(value AS BLOB))),0) FROM responses').fetchone()
        text = ('Cache cleared. Reopen the addon to reload data.' if clear else
                '{} cached responses ({:.1f} MB).\nCatalogs: 15 minutes. Metadata and ratings: 24 hours.\nResponse data limit: 64 MB.'.format(count, size / 1048576))
        xbmcgui.Dialog().ok('Stremio for Kodi cache', text)
    except Exception:
        xbmcgui.Dialog().ok('Stremio for Kodi cache', 'Could not access the cache. Please try again after closing the addon.')
