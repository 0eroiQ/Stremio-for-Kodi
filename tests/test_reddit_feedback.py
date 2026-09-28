"""Regressions for public Reddit feedback reports."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RedditFeedbackTests(unittest.TestCase):
    def test_qr_login_accepts_snake_case_auth_key(self):
        account = load("account_reddit", ROOT / "core" / "account.py")
        with patch.object(account, "request", return_value={"result": {"auth_key": "  test-token  "}}):
            self.assertEqual(account.read_link("code"), "test-token")

    def test_qr_login_accepts_top_level_auth_key(self):
        account = load("account_reddit_top", ROOT / "core" / "account.py")
        with patch.object(account, "request", return_value={"authKey": "test-token"}):
            self.assertEqual(account.read_link("code"), "test-token")

    def test_qr_create_accepts_top_level_shape(self):
        account = load("account_reddit_create", ROOT / "core" / "account.py")
        response = {
            "code": "abc123",
            "link": "https://link.stremio.com/abc123",
            "qrcode": "https://link.stremio.com/qr?data=test"
        }
        with patch.object(account, "request", return_value=response):
            code, link, qr = account.create_link_details()
        self.assertEqual(code, "abc123")
        self.assertEqual(link, response["link"])
        self.assertEqual(qr, response["qrcode"])

    def test_direct_debrid_url_is_kept_when_infohash_is_present(self):
        sources = load("sources_reddit", ROOT / "core" / "sources.py")
        stream = {
            "url": "https://debrid.example/video.mkv",
            "infoHash": "0123456789abcdef",
            "fileIdx": 3,
            "behaviorHints": {"filename": "Example.mkv"}
        }
        self.assertTrue(sources.direct_url(stream))

    def test_direct_url_is_kept_when_external_url_metadata_is_present(self):
        sources = load("sources_reddit_external", ROOT / "core" / "sources.py")
        stream = {
            "url": "https://cdn.example/video.mkv",
            "externalUrl": "https://provider.example/details/1",
            "behaviorHints": {}
        }
        self.assertTrue(sources.direct_url(stream))

    def test_direct_url_still_rejects_proxy_headers(self):
        sources = load("sources_reddit_headers", ROOT / "core" / "sources.py")
        stream = {
            "url": "https://cdn.example/video.mkv",
            "behaviorHints": {"proxyHeaders": {"request": {"Authorization": "secret"}}}
        }
        self.assertFalse(sources.direct_url(stream))


if __name__ == "__main__":
    unittest.main()
