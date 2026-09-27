# Stremio for Kodi

A single Kodi Program add-on combining the StremioELEC program interface and media backend. The embedded Nimbus interface retains its existing home, search, discover, library, add-ons, settings and media detail windows.

## Install

Download `script.stremioelec-1.0.9.zip` from [Releases](https://github.com/0eroiQ/Stremio-for-Kodi/releases), then choose **Add-ons → Install from zip file** in Kodi. Launch **Stremio for Kodi** from Program add-ons.

The stable add-on ID is `script.stremioelec`. Its media resolver and subtitle service are included in the same package; `plugin.video.stremioelec` is no longer required. Existing legacy profile data is copied non-destructively on first use. Existing destination settings take precedence.

Requires Kodi with the Python 3 add-on API. QR code support is optional. The add-on does not change the global Kodi skin. The bundled Nimbus masks and overlays load directly from the addon, independently of the global skin. Kodi still supplies the active font definitions, so typography can vary between global skins.

## Project layout

- `addon.xml`, `default.py`, `plugin.py`, backend modules, `lib/` and `resources/`: complete add-on source at the repository root.
- `tools/build-stremio-addon.py`: builds the installation ZIP from source.
- `tests/test_stremio_addon.py`: packaging, syntax, migration and launch-route regressions.

## Build and test

```sh
python3 -m unittest discover -s tests
python3 tools/build-stremio-addon.py --output dist
```

ZIP packages are distributed through GitHub Releases, not committed to the source tree. CI checks each push and pull request. To prepare a new version, update `addon.xml`, run the checks, and build the matching ZIP before publishing a release.

## Validation

Version 1.0.2 was launched in local macOS Kodi. Catalog loading and sidebar navigation were visually checked; media details were also checked in an isolated Kodi profile. These checks do not establish playback compatibility on every device or provider.

## Credits and license

GPL-2.0-or-later; see `LICENSE`. Nimbus layouts, artwork and fonts are by Ivar Brandt and their respective authors. Original attribution and bundled license notices are retained under `resources/skins/Main/`.

## Account setup

Signed-out users see a Stremio QR linking screen before Home. Scan the code or open the official link, then complete sign-in on your phone. Request a new link if needed. Exiting leaves the addon signed out. Language and location are available under Add-on settings.

## Account Home rows

Home syncs your account add-on collection on launch and follows its add-on and catalog order. Catalogs requiring search/filter input are excluded from Home, as in the [Stremio catalog protocol](https://stremio.github.io/stremio-addon-sdk/api/). Continue Watching comes from your account library when available. Empty or unavailable catalogs are skipped during navigation; if account sync is unavailable, the saved account collection is used. Home does not inject fixed Cinemeta rows or local-only add-ons.

The number of rows is generated from the account collection. Each selected row stays at the same screen position, with the next available row title below. Up to 100 returned titles are shown per catalog. Initial loading time depends on the installed catalog providers. Reopen the addon after changing the account collection to sync it again.

Discover uses the signed-in account addons and their supported catalog filters. Press Up from the first row to change filters or browse another page where supported. Library shows saved account titles grouped by type, with sorting and account refresh from the same filter bar. Both use the Home hero and poster layout.
