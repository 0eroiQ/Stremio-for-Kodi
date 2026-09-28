"""Privacy regressions for generated GitHub issue drafts."""
import importlib.util
from pathlib import Path
import unittest
from urllib.parse import unquote_plus

ROOT = Path(__file__).resolve().parents[1]


def load_reporter():
    spec = importlib.util.spec_from_file_location(
        'error_report', ROOT / 'lib' / 'error_report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ErrorReportTests(unittest.TestCase):
    def test_report_excludes_raw_exception_message_and_secrets(self):
        reporter = load_reporter()
        try:
            raise RuntimeError(
                'secret-token=abc123 https://provider.example/manifest.json?key=private')
        except RuntimeError as error:
            url, report_id = reporter.build_issue_url(
                'Stremio sign-in',
                error,
                environment={
                    'addon': '1.0.33',
                    'kodi': '21.2',
                    'platform': 'Android',
                    'python': '3.11.0',
                })
        decoded = unquote_plus(url)
        self.assertEqual(len(report_id), 10)
        self.assertIn('RuntimeError', decoded)
        self.assertIn('Stremio sign-in', decoded)
        self.assertIn('1.0.33', decoded)
        self.assertNotIn('secret-token', decoded)
        self.assertNotIn('abc123', decoded)
        self.assertNotIn('provider.example', decoded)
        self.assertNotIn('key=private', decoded)

    def test_manual_report_has_no_stack_or_account_data(self):
        reporter = load_reporter()
        url, _ = reporter.build_issue_url(
            'Manual report',
            environment={
                'addon': '1.0.33',
                'kodi': '21.2',
                'platform': 'macOS',
                'python': '3.11.0',
            })
        decoded = unquote_plus(url)
        self.assertIn('No automatic stack was captured.', decoded)
        self.assertIn('does **not** include Stremio tokens', decoded)


if __name__ == '__main__':
    unittest.main()
