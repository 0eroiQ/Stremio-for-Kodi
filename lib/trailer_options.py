"""Trailer playback routing without changing Kodi player settings."""
from urllib.parse import urlencode


def playback_url(video_id, preference, installed):
    choices = [('slyguy.trailers', 'plugin://slyguy.trailers/play/?'),
               ('plugin.video.youtube', 'plugin://plugin.video.youtube/play/?')]
    if preference in ('1', '2'):
        choices = [choices[int(preference)-1]]
    for addon, base in choices:
        if installed(addon):
            return base + urlencode({'video_id': video_id})
    return ''
