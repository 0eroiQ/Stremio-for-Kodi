"""Pure state-aware action lists for long-press media menus."""


def episode_options(watched=False, prefix_watched=False, resume=False):
    return [
        {'action':'play', 'label':'Resume' if resume else 'Play', 'icon':'play'},
        {'action':'restart', 'label':'Play from Beginning', 'icon':'restart'},
        {'action':'toggle-watched',
         'label':'Mark as Unwatched' if watched else 'Mark as Watched',
         'icon':'unwatched' if watched else 'watched'},
        {'action':'through-unwatched' if prefix_watched else 'through-watched',
         'label':'Mark Here as Unwatched' if prefix_watched else 'Mark Here as Watched',
         'icon':'through-unwatch' if prefix_watched else 'through-watch'},
        {'action':'info', 'label':'More Info', 'icon':'info'},
    ]


def continue_options(kind, watched=False):
    rows = [{'action':'restart', 'label':'Watch from Beginning', 'icon':'restart'}]
    if kind == 'series':
        rows.extend([
            {'action':'episode', 'label':'Go to Episode', 'icon':'episode'},
            {'action':'series', 'label':'Go to Series', 'icon':'series'},
        ])
    rows.extend([
        {'action':'toggle-watched',
         'label':'Mark as Unwatched' if watched else 'Mark as Watched',
         'icon':'unwatched' if watched else 'watched'},
        {'action':'remove-continue', 'label':'Remove from Continue Watching', 'icon':'remove'},
        {'action':'info', 'label':'More Info', 'icon':'info'},
    ])
    return rows
