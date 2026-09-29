"""Regression coverage for GitHub issues #11, #14, #15, #16 and #17."""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IssueRegressionTests(unittest.TestCase):
    def test_account_save_does_not_require_os_fchmod(self):
        account = load("account_no_fchmod", CORE / "account.py")
        real_os = account.os

        class OSProxy:
            path = real_os.path
            fdopen = staticmethod(real_os.fdopen)
            fsync = staticmethod(real_os.fsync)
            replace = staticmethod(real_os.replace)
            close = staticmethod(real_os.close)

        account.os = OSProxy()
        with tempfile.TemporaryDirectory() as directory:
            store = account.Store(directory)
            store.save({"token": "test-only"})
            self.assertEqual(store.load()["token"], "test-only")

    def test_account_save_retries_transient_replace_error(self):
        account = load("account_replace_retry", CORE / "account.py")
        real_replace = account.os.replace
        attempts = []

        def flaky_replace(source, target):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError("sharing violation")
            return real_replace(source, target)

        with tempfile.TemporaryDirectory() as directory:
            store = account.Store(directory)
            with patch.object(account.os, "replace", side_effect=flaky_replace),                  patch.object(account.time, "sleep"):
                store.save({"token": "test-only"})
            self.assertEqual(len(attempts), 2)
            self.assertEqual(store.load()["token"], "test-only")

    def test_home_catalogs_fall_back_when_threads_cannot_start(self):
        catalogs = load("home_catalogs_thread_fallback", ROOT / "lib/home_catalogs.py")
        addons = [{
            "transportUrl": "https://example.org/manifest.json",
            "manifest": {"catalogs": [
                {"id": "one", "name": "One", "type": "movie"},
                {"id": "two", "name": "Two", "type": "series"},
            ]}
        }]

        class BrokenPool:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def map(self, *args, **kwargs):
                raise RuntimeError("can't start new thread")

        with patch.object(catalogs, "ThreadPoolExecutor", BrokenPool):
            rows = catalogs.load_rows(
                addons,
                lambda url: {"metas": [{"id": url, "name": "Title"}]},
                lambda url, resource, kind, identity: identity,
            )
        self.assertEqual([row["catalog_id"] for row in rows], ["one", "two"])
        self.assertFalse(any(row["failed"] for row in rows))

    def test_episode_cards_show_code_title_and_metadata_pills(self):
        tree = ET.parse(ROOT / "resources/skins/Main/1080i/script-stremio-info.xml")
        episodes = tree.find('.//control[@id="501"]')
        self.assertIsNotNone(episodes)
        xml = ET.tostring(episodes, encoding="unicode")
        for prop in ("episode_heading", "episode_runtime", "episode_imdb", "episode_date"):
            self.assertIn("ListItem.Property({})".format(prop), xml)
        self.assertIn("ratings/imdb.png", xml)
        self.assertIn('colordiffuse="99171920"', xml)

        source = (ROOT / "lib/nimbus.py").read_text()
        for prop in ("episode_heading", "episode_runtime", "episode_imdb", "episode_date"):
            self.assertIn("setProperty('{}'".format(prop), source)

    def test_episode_card_metadata_formatters(self):
        # Load only the helper functions so the test stays Kodi-independent.
        source = (ROOT / "lib/nimbus.py").read_text()
        tree = ast.parse(source)
        names = {"episode_runtime", "episode_rating", "episode_date"}
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name in names]
        scope = {
            "re": __import__("re"),
            "_MONTHS": ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<episode-formatters>", "exec"), scope)
        self.assertEqual(scope["episode_runtime"]("65 min"), "1h 5m")
        self.assertEqual(scope["episode_runtime"]("PT58M"), "58m")
        self.assertEqual(scope["episode_rating"]({"imdbRating": "8.2"}), "8.2")
        self.assertEqual(scope["episode_date"]({"released": "2019-12-20T00:00:00.000Z"}), "20 Dec 2019")


if __name__ == "__main__":
    unittest.main()
