import ast
import errno
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'core'))
from lib.report_feedback import attach_feedback, report_labels, validate_feedback, feedback_text
from lib import error_report as reporter
import account

ENV = {'addonVersion':'1.0.41', 'kodiVersion':'21.3', 'platform':'Android', 'pythonVersion':'3.11.7'}
FEATURE = {'kind':'feature', 'category':'subtitles', 'title':'Remember subtitle size',
           'description':'Remember the subtitle size between episodes on this device.', 'frequency':'not-applicable'}

class StorageTests(unittest.TestCase):
    def test_transient_profile_permission_is_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            store = account.Store(folder)
            real = Path.mkdir
            calls = []
            def first_denied(path, *args, **kwargs):
                calls.append(1)
                if len(calls) == 1: raise PermissionError(errno.EACCES, 'private test path')
                return real(path, *args, **kwargs)
            with patch.object(Path, 'mkdir', first_denied), patch.object(account.time, 'sleep'):
                store.save({'fixture':True})
            self.assertEqual(len(calls), 2)
            self.assertEqual(store.load(), {'fixture':True})

    def test_transient_temp_creation_is_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            store = account.Store(folder)
            real = account.tempfile.mkstemp
            calls = []
            def flaky(*args, **kwargs):
                calls.append(1)
                if len(calls) < 3: raise PermissionError(errno.EACCES, 'locked')
                return real(*args, **kwargs)
            with patch.object(account.tempfile, 'mkstemp', flaky), patch.object(account.time, 'sleep'):
                store.save({'fixture':'saved'})
            self.assertEqual(len(calls),3)
            self.assertEqual(store.load()['fixture'],'saved')
            self.assertFalse(list(Path(folder).glob('.account-*')))

    def test_persistent_permission_preserves_last_good_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store=account.Store(folder); store.save({'fixture':'old'})
            with patch.object(account.os, 'replace', side_effect=PermissionError(errno.EACCES, '/private/password=SECRET')) as replace, patch.object(account.time,'sleep'):
                with self.assertRaises(account.AccountStorageError) as raised:
                    store.save({'fixture':'new'})
            self.assertEqual(replace.call_count,6)
            self.assertEqual(store.load()['fixture'],'old')
            self.assertEqual(raised.exception.stage,'replace_state')
            self.assertNotIn('SECRET', str(raised.exception))
            self.assertFalse(list(Path(folder).glob('.account-*')))

    def test_disk_full_is_not_ignored_or_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            store=account.Store(folder); store.save({'fixture':'old'})
            with patch.object(account.os,'fsync',side_effect=OSError(errno.ENOSPC,'disk full')), patch.object(account.os,'replace') as replace, patch.object(account.time,'sleep') as sleep:
                with self.assertRaises(account.AccountStorageError) as raised:
                    store.save({'fixture':'new'})
                replace.assert_not_called(); sleep.assert_not_called()
            self.assertEqual(raised.exception.reason,'disk_full')
            self.assertEqual(store.load()['fixture'],'old')
            self.assertFalse(list(Path(folder).glob('.account-*')))

    def test_storage_reporting_context_contains_no_sensitive_message(self):
        tree=ast.parse((ROOT/'lib/signin.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='sign_in_failure')
        scope={'AccountStorageError':account.AccountStorageError}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<test>','exec'),scope)
        error=account.AccountStorageError('create_temp',PermissionError(errno.EACCES,'/private/secret'))
        context,message=scope['sign_in_failure'](error)
        self.assertIn('storage:',context); self.assertNotIn('/',context)
        self.assertNotIn('/private',message)
        self.assertIn('permission_or_locked',context)

class FeedbackTests(unittest.TestCase):
    def payload(self, feedback=FEATURE):
        return attach_feedback(reporter.build_payload('Manual report',environment=ENV),feedback)

    def test_feature_has_its_own_type_fingerprint_and_labels(self):
        p=self.payload()
        self.assertEqual(p['reportVersion'],2)
        self.assertEqual(p['errorType'],'FeatureRequest')
        self.assertEqual(p['stack'],[])
        self.assertEqual(report_labels(p,initial=True),['feature-request','area:subtitles','platform:android','source:manual','needs-triage'])
        other=self.payload(dict(FEATURE,title='Remember subtitle position'))
        self.assertNotEqual(p['fingerprint'],other['fingerprint'])

    def test_automatic_and_legacy_manual_receive_labels(self):
        auto={'context':'Stremio sign-in','errorType':'PermissionError','platform':'Windows'}
        self.assertEqual(report_labels(auto),['bug','area:login','platform:windows','source:auto'])
        unknown={'context':'Manual report','errorType':'ManualReport','platform':'Android'}
        self.assertEqual(report_labels(unknown),['needs-info','area:general','platform:android','source:manual'])

    def test_client_cannot_inject_labels_or_priority(self):
        for field in ('labels','priority','state','token'):
            with self.assertRaises(ValueError): validate_feedback(dict(FEATURE,**{field:'injected'}))

    def test_sensitive_feedback_is_rejected(self):
        values=['https://example.org/private','authKey=SECRET','email@example.org','C:\\Users\\Name\\file',
                '/Users/person/private','Bearer private-value','@someone look at this','```injection```',
                'provider.example.com/account','\u202eevil display','hello\nsecret','ghp_'+'a'*36]
        for value in values:
            with self.subTest(value=value[:10]), self.assertRaises(ValueError):
                feedback_text(value,5,1000)

    def test_realistic_unicode_and_symbols_are_accepted(self):
        self.assertEqual(feedback_text('Bosanski titlovi č ć š ž đ',5,100),'Bosanski titlovi č ć š ž đ')
        self.assertEqual(feedback_text('Add 4K + HDR option',5,100),'Add 4K + HDR option')

    def test_cancel_type_category_consent_and_text_sends_nothing(self):
        for selections, consent, inputs in (([-1],True,[]),([1,-1],True,[]),([1,3],False,[]),([1,3],True,['']),([1,3],True,['A valid title',''])):
            dialog=Mock(); dialog.select.side_effect=selections; dialog.yesno.return_value=consent; dialog.input.side_effect=inputs
            with patch.object(reporter,'show_report_dialog') as show, patch.object(reporter,'send_report') as send:
                self.assertFalse(reporter.manual_report(dialog)); show.assert_not_called(); send.assert_not_called()

    def test_feature_review_precedes_final_confirmation_no_auto_send(self):
        dialog=Mock(); dialog.select.side_effect=[1,3]; dialog.yesno.return_value=True
        dialog.input.side_effect=[FEATURE['title'],FEATURE['description']]
        with patch.object(reporter,'_environment',return_value=ENV), patch.object(reporter,'show_report_dialog',return_value=False) as show, patch.object(reporter,'send_report') as send:
            self.assertFalse(reporter.manual_report(dialog))
        dialog.textviewer.assert_called_once(); show.assert_called_once(); send.assert_not_called()
        self.assertEqual(show.call_args[0][0]['feedback'],FEATURE)

    def test_bug_requires_frequency_and_description(self):
        dialog=Mock(); dialog.select.side_effect=[0,0,2]; dialog.yesno.return_value=True
        dialog.input.side_effect=['Login is not saved','The login disappears after I restart Kodi.']
        with patch.object(reporter,'show_report_dialog',return_value=True) as show:
            self.assertTrue(reporter.manual_report(dialog))
        p=show.call_args[0][0]
        self.assertEqual(p['errorType'],'ManualReport')
        self.assertEqual(p['feedback']['frequency'],'after-restart')
        self.assertIn('area:login',report_labels(p))

if __name__=='__main__': unittest.main()
