# Stremio for Kodi

A single Kodi Program add-on combining the StremioELEC program interface and media backend. The embedded Nimbus interface retains its existing home, search, discover, library, add-ons, settings and media detail windows.

<p align="center">
  <img src="docs/screenshots/home-brothers.png" alt="Stremio for Kodi Home — Brothers" width="100%">
</p>

## Screenshots

### Home — New & Latest

Remote-friendly Home browsing with poster badges, cinematic artwork and clear focus states.

![Stremio for Kodi Home — The Deputy](docs/screenshots/home-deputy.png)

### Library

Browse your library with type filters, sorting and refresh controls while keeping the same hero-driven interface.

![Stremio for Kodi Library](docs/screenshots/library.png)

### Addons

Manage installed Stremio addons directly from the interface, including Configure, Disable, Remove and Add addon actions.

![Stremio for Kodi Addons](docs/screenshots/addons.png)

### Episodes

Browse seasons and episodes with watched-state checkmarks and TV-friendly horizontal navigation.

![Stremio for Kodi Episodes](docs/screenshots/episodes.png)

## Install

For installation and automatic updates, download [repository.stremioforkodi-1.0.0.zip](https://github.com/0eroiQ/Stremio-for-Kodi/releases/latest/download/repository.stremioforkodi-1.0.0.zip). In Kodi, choose **Add-ons → Install from zip file**, select that ZIP, then **Install from repository → Stremio for Kodi Repository → Program add-ons → Stremio for Kodi**. Enable automatic updates for the addon if desired.

For a standalone installation, download `script.stremioelec-1.0.36.zip` from [Releases](https://github.com/0eroiQ/Stremio-for-Kodi/releases), then choose **Add-ons → Install from zip file** in Kodi. Launch **Stremio for Kodi** from Program add-ons.

The stable add-on ID is `script.stremioelec`. Its media resolver and subtitle service are included in the same package; `plugin.video.stremioelec` is no longer required. Existing legacy profile data is copied non-destructively on first use. Existing destination settings take precedence.

Requires Kodi with the Python 3 add-on API. QR code support is optional. The add-on does not change the global Kodi skin. The bundled Nimbus masks and overlays load directly from the addon, independently of the global skin. Kodi still supplies the active font definitions, so typography can vary between global skins.

## Startup shell mode

Optional **Settings → Startup → Launch Stremio for Kodi when Kodi starts** opens the addon automatically at the earliest startup point supported for Kodi service addons. The public default is off. Startup delay can be Immediate, 1, 2, 3 or 5 seconds.

At the top-level Stremio Home shell, Back does not silently fall through to Kodi Home. It shows **Exit** or **Cancel**; Cancel changes nothing and only Exit closes Stremio for Kodi. Back inside media-detail dialogs keeps its normal in-app navigation behavior.

## Support and error reports

Anonymous automatic error reporting is enabled by default and can be disabled under **Settings → Support → Automatically send anonymous error reports**. The first launch shows a one-time notice explaining this preference. When an unexpected fatal error is captured, the addon sends a small sanitized report and shows a Kodi notification such as **Error reported · <Error ID>**. If automatic reporting is disabled or a send fails, an addon-owned Nimbus-style dialog offers **Report issue** or **Dismiss** without opening a browser.

Reports contain only the Stremio for Kodi version, Kodi/Python versions, broad platform, error type, Error ID and sanitized basename/function/line stack frames. They exclude Stremio tokens, addon/provider URLs, API keys, media URLs, account details, device identifiers, local filesystem paths and raw exception messages. Matching reports are aggregated by Error ID. A scheduled GitHub Action in this repository turns those aggregates into GitHub issues using the repository's short-lived GitHub Actions token; no GitHub credential is shipped in the Kodi addon.

You can also use **Settings → Support → Report a problem now** at any time.

## Project layout

- `addon.xml` plus the small `default.py`, `plugin.py`, `service.py` and `subtitle_service.py` bootstraps: Kodi entry points kept at the add-on root.\n- `core/`: Stremio account, protocol, metadata, stream, subtitle and supporting runtime modules.\n- `lib/`: Nimbus UI, browsing, settings, caching, Premium client and other application modules.\n- `resources/`: embedded Nimbus skin assets, settings and runtime data.
- `tools/build-stremio-addon.py`: builds the installation ZIP from source.
- `tests/test_stremio_addon.py`: packaging, syntax, migration and launch-route regressions.

## Build and test

```sh
python3 -m unittest discover -s tests
python3 tools/build-stremio-addon.py --output dist
```

ZIP packages are distributed through GitHub Releases. The `kodi-repository` branch holds the Kodi feed and released packages; `main` holds the source. The Publish Kodi repository workflow publishes stable release assets to that feed and attaches the repository installer to each release. It can also be run manually with a stable release tag. CI checks each push and pull request. To prepare a new version, update `addon.xml`, run the checks, and build the matching ZIP before publishing a release.

## Validation

Version 1.0.2 was launched in local macOS Kodi. Catalog loading and sidebar navigation were visually checked; media details were also checked in an isolated Kodi profile. These checks do not establish playback compatibility on every device or provider.

## Credits and license

GPL-2.0-or-later; see `LICENSE`. Nimbus layouts, artwork and fonts are by Ivar Brandt and their respective authors. Original attribution and bundled license notices are retained under `resources/skins/Main/`.

## Public client and Premium boundary

The Kodi client is designed to be safe to publish as open source. Free playback, browsing and account features remain client-side. Premium authority, customer records, payment state and entitlement grants stay server-side on `vortexo.app`.

Kodi does not use a second Vortexo login. The client sends its existing Stremio `authKey` only to the fixed HTTPS Vortexo session endpoint. Vortexo verifies that session with Stremio, derives the stable Stremio UID server-side, and returns a short-lived signed Vortexo access token. Premium API calls then use only that Vortexo token; they do not repeatedly send the Stremio auth key. The client never supplies a UID, price, payment result or feature grant. If Vortexo is unavailable or Premium is disabled, free Stremio for Kodi functionality continues to work.

The client also contains a bounded **Get Premium** handoff. It asks the private Vortexo backend for a customer-bound purchase session using the short-lived Vortexo token, then displays the returned `vortexo.app` checkout URL as a QR code. The client cannot choose the product, price, payment result, customer UID or feature grants. Pricing and production commerce remain controlled by the private Vortexo backend, and free functionality continues to work if Premium checkout is unavailable.

## Account setup

Signed-out users see a Stremio QR linking screen before Home. Scan the code or open the official link, then complete sign-in on your phone. Request a new link if needed. Exiting leaves the addon signed out. Language and location are available under Add-on settings.

## Account Home rows

Home syncs your account add-on collection on launch and follows its add-on and catalog order. Catalogs requiring search/filter input are excluded from Home, as in the [Stremio catalog protocol](https://stremio.github.io/stremio-addon-sdk/api/). Continue Watching comes from your account library when available. Empty or unavailable catalogs are skipped during navigation; if account sync is unavailable, the saved account collection is used. Home does not inject fixed Cinemeta rows or local-only add-ons.

The number of rows is generated from the account collection. Each selected row stays at the same screen position, with the next available row title below. Up to 100 returned titles are shown per catalog. Initial loading time depends on the installed catalog providers. Reopen the addon after changing the account collection to sync it again.

Discover uses the signed-in account addons and their supported catalog filters. Press Up from the first row to change filters or browse another page where supported. Library shows saved account titles grouped by type, with sorting and account refresh from the same filter bar. Both use the Home hero and poster layout.

Browsing responses are cached in the addon Kodi profile across restarts: catalogs for 15 minutes and metadata for 24 hours, with a 64 MiB response-data budget. Kodi manages artwork caching. Account synchronization, stream and subtitle responses are not cached by this layer.

Optional MDbList ratings: open addon Settings > Ratings, enter an API key or use Import API key from Nimbus, and select a rating source. Reopen the addon after changing these settings. Lookup supports IMDb movie/show IDs; unavailable ratings retain the original Stremio rating.

### Premium service boundary

Premium authority is never a local boolean. The public client exchanges the existing Stremio session for a short-lived signed Vortexo token, then uses that token for private Vortexo Premium APIs.

The first server-gated feature client is **AI Translation**. Translation requests contain only bounded subtitle/dialogue text, language codes and local segment IDs. The Stremio auth key, Stremio UID, Vortexo customer ID, provider API key and payment state are not sent in the translation payload. The private Vortexo backend verifies the signed token and current Premium entitlement before a translation provider can be invoked.

The built-in direct IMDb trailer resolver described below is currently a **free local feature** because its implementation is already public in this repository. The server-side `trailers` Premium entitlement is reserved for future Vortexo-hosted trailer enhancements; the project does not pretend that public local trailer code can be securely paywalled.

### Built-in trailers

Trailers resolve directly from IMDb and play with Kodi's native player. No YouTube or SlyGuy addon, API key or trailer login is required. Settings → Trailers controls enablement, maximum MP4 quality (1080p/720p/480p), autoplay and delay. HLS is used when MP4 is unavailable. Availability depends on IMDb: titles without an IMDb ID or a playable trailer report unavailable; YouTube-only clips are not resolved. The supplied SlyGuy Trailers 0.2.0 IMDb route informed the protocol integration; no SlyGuy framework or credentials are bundled.

Automatic trailers play in the Home and details hero with a background-sized video plane and edge fade. Back stops the preview and restores artwork. Home and playback settings also provide an addon-owned fullscreen Back-to-Stop keymap for all Kodi videos; disable the setting and reopen the addon to remove only that keymap.
