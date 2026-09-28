"""Privacy regressions for anonymous error reports."""
import json
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_reporter():
    spec = importlib.util.spec_from_file_location(
        'error_report', ROOT / 'lib' / 'error_report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ErrorReportTests(unittest.TestCase):
    def test_payload_excludes_raw_exception_message_and_secrets(self):
        reporter = load_reporter()
        try:
            raise RuntimeError(
                'secret-token=abc123 https://provider.example/manifest.json?key=private')
        except RuntimeError as error:
            payload = reporter.build_payload(
                'Stremio sign-in',
                error,
                environment={
                    'addonVersion': '1.0.34',
                    'kodiVersion': '21.2',
                    'platform': 'Android',
                    'pythonVersion': '3.11.0',
                })
        encoded = json.dumps(payload, sort_keys=True)
        self.assertEqual(len(payload['fingerprint']), 12)
        self.assertEqual(payload['errorType'], 'RuntimeError')
        self.assertEqual(payload['context'], 'Stremio sign-in')
        self.assertIn('1.0.34', encoded)
        self.assertNotIn('secret-token', encoded)
        self.assertNotIn('abc123', encoded)
        self.assertNotIn('provider.example', encoded)
        self.assertNotIn('key=private', encoded)

    def test_stack_contains_only_basename_line_and_function(self):
        reporter = load_reporter()

        def fail_here():
            raise ValueError('/Users/person/private/file?token=secret')

        try:
            fail_here()
        except ValueError as error:
            payload = reporter.build_payload(
                'Program entry',
                error,
                environment={
                    'addonVersion': '1.0.34',
                    'kodiVersion': '21.2',
                    'platform': 'macOS',
                    'pythonVersion': '3.11.0',
                })
        stack = '\n'.join(payload['stack'])
        self.assertIn('test_error_report.py:', stack)
        self.assertIn('fail_here', stack)
        self.assertNotIn('/Users/', stack)
        self.assertNotIn('token=secret', stack)

    def test_manual_report_has_no_stack_or_account_data(self):
        reporter = load_reporter()
        payload = reporter.build_payload(
            'Manual report',
            environment={
                'addonVersion': '1.0.34',
                'kodiVersion': '21.2',
                'platform': 'macOS',
                'pythonVersion': '3.11.0',
            })
        self.assertEqual(payload['errorType'], 'ManualReport')
        self.assertEqual(payload['stack'], [])
        self.assertNotIn('account', json.dumps(payload).lower())

    def test_default_setting_enables_automatic_reporting(self):
        settings = (ROOT / 'resources' / 'settings.xml').read_text()
        self.assertIn('id="error_reporting_auto"', settings)
        self.assertIn('default="true"', settings)
        self.assertIn('Report a problem now', settings)


if __name__ == '__main__':
    unittest.main()
