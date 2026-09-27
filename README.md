# Stremio for Kodi

A single Kodi Program add-on combining the StremioELEC program interface and media backend. The embedded Nimbus interface retains its existing home, search, discover, library, add-ons, settings and media detail windows.

## Install

Download `script.stremioelec-1.0.3.zip` from [Releases](https://github.com/0eroiQ/Stremio-for-Kodi/releases), then choose **Add-ons → Install from zip file** in Kodi. Launch **Stremio for Kodi** from Program add-ons.

The stable add-on ID is `script.stremioelec`. Its media resolver and subtitle service are included in the same package; `plugin.video.stremioelec` is no longer required. Existing legacy profile data is copied non-destructively on first use. Existing destination settings take precedence.

Requires Kodi with the Python 3 add-on API. QR code support is optional. The add-on does not change the global Kodi skin. Its supplied Nimbus windows use skin textures and fonts; appearance has been visually checked with Nimbus active on macOS and can differ with another global skin.

## Project layout

- `addon.xml`, `default.py`, `plugin.py`, backend modules, `lib/` and `resources/`: complete add-on source at the repository root.
- `tools/build-stremio-addon.py`: builds the installation ZIP from source.
- `tests/test_stremio_addon.py`: packaging, syntax, migration and launch-route regressions.

## Build and test

```sh
python3 tests/test_stremio_addon.py
python3 tools/build-stremio-addon.py --output dist
```

ZIP packages are distributed through GitHub Releases, not committed to the source tree. CI checks each push and pull request. To prepare a new version, update `addon.xml`, run the checks, and build the matching ZIP before publishing a release.

## Validation

Version 1.0.2 was launched in local macOS Kodi. Catalog loading and sidebar navigation were visually checked; media details were also checked in an isolated Kodi profile. These checks do not establish playback compatibility on every device or provider.

## Credits and license

GPL-2.0-or-later; see `LICENSE`. Nimbus layouts, artwork and fonts are by Ivar Brandt and their respective authors. Original attribution and bundled license notices are retained under `resources/skins/Main/`.
