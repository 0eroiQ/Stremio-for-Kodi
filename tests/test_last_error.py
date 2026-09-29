"""Only synthetic diagnostics and fake network transports are used here."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from lib import error_report as reporter
from lib import last_error as store

ENV = {'addonVersion': '1.0.41', 'kodiVersion': '21.3', 'platform': 'Windows', 'pythonVersion': '3.8.15'}


def payload():
    try:
        raise RuntimeError('authKey=PRIVATE_SECRET https://example.invalid/token=PRIVATE /Users/private/name')
    except RuntimeError as error:
        return reporter.build_payload('Stremio sign-in', error, ENV)


class LastErrorTests(unittest.TestCase):
    def test_saves_only_diagnostic_and_survives_new_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'last-error.json'
            original = payload()
            self.assertTrue(store.remember_error(original, path, 100))
            record = store.load_last_error(path)
            self.assertEqual(record['payload'], original)
            self.assertEqual(record['savedAt'], 100)
            for forbidden in ('PRIVATE_SECRET', 'https://', '/Users/', 'authKey='):
                self.assertNotIn(forbidden, path.read_text())
            self.assertTrue(store.mark_sent(original['fingerprint'], path, 101))
            self.assertEqual(store.load_last_error(path)['sentAt'], 101)
            if sys.platform != 'win32':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_feedback_never_overwrites_captured_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'last-error.json'
            original = payload()
            store.remember_error(original, path, 100)
            manual = reporter.build_payload('Manual report', environment=ENV)
            self.assertFalse(store.remember_error(manual, path, 101))
            self.assertEqual(store.load_last_error(path)['payload'], original)

    def test_rejects_extra_fields_and_modified_fingerprint(self):
        original = payload()
        for value in (dict(original, authKey='secret'), dict(original, fingerprint='000000000000'),
                      dict(original, context='https://example.invalid/private')):
            with self.subTest(value=value['fingerprint']), self.assertRaises(ValueError):
                store.validate_payload(value)

    def test_invalid_missing_or_oversized_snapshot_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'last-error.json'
            self.assertIsNone(store.load_last_error(path))
            for text in ('{bad', '[]', 'x' * (store.MAX_BYTES + 1)):
                path.write_text(text)
                self.assertIsNone(store.load_last_error(path))

    def test_failed_atomic_write_keeps_previous_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'last-error.json'
            first = payload()
            store.remember_error(first, path, 100)
            with patch('lib.last_error.os.replace', side_effect=PermissionError('synthetic')):
                self.assertFalse(store.remember_error(first, path, 101))
            self.assertEqual(store.load_last_error(path)['savedAt'], 100)
            self.assertEqual([item.name for item in path.parent.iterdir()], ['last-error.json'])

    def test_old_sent_result_cannot_replace_new_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'last-error.json'
            original = payload()
            store.remember_error(original, path, 100)
            self.assertFalse(store.mark_sent('000000000000', path, 101))
            self.assertIsNone(store.load_last_error(path)['sentAt'])

    def test_caught_error_is_saved_when_automatic_reporting_is_off(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('lib.last_error._path', return_value=Path(directory) / 'last-error.json'), \
             patch.object(reporter, '_environment', return_value=ENV), \
             patch.object(reporter, 'automatic_enabled', return_value=False), \
             patch.object(reporter, 'show_report_dialog', return_value=False), \
             patch.object(reporter, 'send_report') as network:
            try:
                raise ValueError('private details must not be saved')
            except ValueError as error:
                self.assertFalse(reporter.handle_error('Playback', error))
            self.assertEqual(store.load_last_error()['payload']['errorType'], 'ValueError')
            network.assert_not_called()

    def test_successful_auto_send_is_marked(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('lib.last_error._path', return_value=Path(directory) / 'last-error.json'), \
             patch.object(reporter, '_environment', return_value=ENV), \
             patch.object(reporter, 'automatic_enabled', return_value=True), \
             patch.object(reporter, 'send_report', return_value=True):
            self.assertTrue(reporter.handle_error('Playback', ValueError('synthetic')))
            self.assertIsNotNone(store.load_last_error()['sentAt'])

    def test_no_saved_error_does_not_send_empty_report(self):
        dialog = Mock()
        with patch('lib.last_error.load_last_error', return_value=None), \
             patch.object(reporter, 'show_report_dialog') as modal, \
             patch.object(reporter, 'send_report') as network:
            self.assertFalse(reporter.report_last_error(dialog))
        dialog.ok.assert_called_once()
        dialog.textviewer.assert_not_called()
        modal.assert_not_called()
        network.assert_not_called()

    def test_replay_keeps_original_versions_and_fingerprint(self):
        dialog = Mock()
        original = payload()
        record = {'payload': original, 'savedAt': 100, 'sentAt': 101}
        with patch('lib.last_error.load_last_error', return_value=record), \
             patch.object(reporter, 'show_report_dialog', return_value=False) as modal, \
             patch.object(reporter, 'send_report') as network:
            self.assertFalse(reporter.report_last_error(dialog))
        self.assertEqual(modal.call_args.args[0], original)
        self.assertTrue(modal.call_args.kwargs['replay'])
        self.assertIn('Already sent', modal.call_args.args[1])
        self.assertIn('1.0.41', dialog.textviewer.call_args.args[1])
        network.assert_not_called()

    def test_feedback_menu_has_report_last_error_without_manual_questions(self):
        dialog = Mock()
        dialog.select.return_value = 2
        with patch.object(reporter, 'report_last_error', return_value=False) as replay:
            self.assertFalse(reporter.manual_report(dialog))
        self.assertIn('Report last error', dialog.select.call_args.args[1])
        self.assertEqual(dialog.select.call_count, 1)
        replay.assert_called_once_with(dialog)
        dialog.input.assert_not_called()

    def test_menu_cancel_is_no_op(self):
        dialog = Mock()
        dialog.select.return_value = -1
        with patch.object(reporter, 'report_last_error') as replay, \
             patch.object(reporter, 'send_report') as network:
            self.assertFalse(reporter.manual_report(dialog))
        replay.assert_not_called()
        network.assert_not_called()

    def test_last_error_dialog_starts_on_cancel(self):
        record = payload()
        gui = Mock()
        gui.WindowXMLDialog = object
        with patch.dict(sys.modules, {'xbmcgui': gui, 'addon_state': types.SimpleNamespace(get_addon=lambda: None)}):
            window_class, _ = reporter._report_window_class()
            fake = Mock()
            fake.payload = record
            fake.replay = True
            fake.summary = 'Synthetic preview'
            window_class.onInit(fake)
            fake.setFocusId.assert_called_once_with(202)
            fake.getControl.assert_any_call(201)


if __name__ == '__main__':
    unittest.main()
