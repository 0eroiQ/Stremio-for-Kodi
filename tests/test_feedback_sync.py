import copy
import importlib.util
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class SyncTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('sync_candidate',ROOT/'tools/sync-error-reports.py')
        self.sync=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.sync)
        self.sync.TOKEN='test-token-not-real'
        fixtures=json.loads((ROOT/'tests/fixtures/server-feedback.json').read_text())
        self.feed=copy.deepcopy(fixtures)
        self.issues={}; self.labels={}; self.calls=[]
        self.sync.request_json=self.fake

    def fake(self,url,method='GET',body=None):
        self.calls.append((url,method,copy.deepcopy(body)))
        if url==self.sync.ENDPOINT: return copy.deepcopy(self.feed)
        path=urllib.parse.urlsplit(url).path
        if path=='/search/issues':
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['q'][0]
            fp=query.split()[-1]
            return {'items':[dict(v,number=k) for k,v in self.issues.items() if fp in v.get('title','')]}
        root='/repos/'+self.sync.REPOSITORY
        if path==root+'/labels' and method=='POST':
            self.labels[body['name']]=body; return body
        if path.startswith(root+'/labels/'):
            name=urllib.parse.unquote(path.split('/labels/',1)[1])
            if name not in self.labels: raise urllib.error.HTTPError(url,404,'Not Found',{},None)
            return self.labels[name]
        if path==root+'/issues' and method=='POST':
            number=max(self.issues.keys(),default=0)+1
            self.issues[number]=dict(body,number=number,state='open')
            return self.issues[number]
        if path.startswith(root+'/issues/'):
            parts=path[len(root+'/issues/'):].split('/')
            issue=self.issues[int(parts[0])]
            if len(parts)==2 and parts[1]=='labels':
                issue['labels']=list(dict.fromkeys(issue.get('labels',[])+body['labels'])); return issue['labels']
            if method=='PATCH': issue.update(body)
            return copy.deepcopy(issue)
        raise AssertionError('Unexpected API call '+path)

    def test_server_feed_becomes_tagged_bug_and_feature_issues(self):
        self.sync.sync()
        feature=next(v for v in self.issues.values() if v['title'].startswith('[Feature Request] Remember subtitle size'))
        self.assertIn('feature-request',feature['labels'])
        self.assertIn('area:subtitles',feature['labels'])
        self.assertIn('platform:android',feature['labels'])
        self.assertIn('source:manual',feature['labels'])
        self.assertIn('Remember the subtitle size',feature['body'])
        bug=next(v for v in self.issues.values() if v['title'].startswith('[Bug Report]'))
        self.assertIn('bug',bug['labels']); self.assertIn('area:login',bug['labels'])
        old=next(v for v in self.issues.values() if v['title'].startswith('[Manual Report]'))
        self.assertIn('needs-info',old['labels']); self.assertNotIn('bug',old['labels'])

    def test_second_sync_is_idempotent(self):
        self.sync.sync(); before=copy.deepcopy(self.issues); self.calls=[]
        self.sync.sync()
        self.assertEqual(self.issues,before)
        self.assertFalse(any(method in ('POST','PATCH') for _,method,_ in self.calls))

    def test_existing_labels_and_closed_state_are_preserved(self):
        row=self.feed['reports'][0]
        self.feed['reports']=[row]
        self.issues[24]={'title':'Maintainer title '+row['fingerprint'],'body':'Maintainer notes',
                         'labels':['priority:low','maintainer-reviewed'],'state':'closed','number':24}
        self.sync.sync()
        issue=self.issues[24]
        self.assertEqual(issue['state'],'closed'); self.assertEqual(issue['body'],'Maintainer notes')
        self.assertIn('maintainer-reviewed',issue['labels']); self.assertIn('priority:low',issue['labels'])
        self.assertNotIn('needs-triage',issue['labels'])
        self.assertTrue(any(x.startswith('area:') for x in issue['labels']))
        self.assertFalse(any(method=='PATCH' for _,method,_ in self.calls))

    def test_unknown_client_labels_do_not_reach_github(self):
        row=next(r for r in self.feed['reports'] if r.get('feedback'))
        row['feedback']['labels']=['critical']
        self.feed['reports']=[row]
        self.sync.sync()
        self.assertEqual(self.issues,{})
        self.assertEqual(self.labels,{})

    def test_new_issue_limit_is_enforced(self):
        row=next(r for r in self.feed['reports'] if r.get('feedback'))
        self.feed['reports']=[dict(copy.deepcopy(row),fingerprint=format(i,'012x')) for i in range(20)]
        self.sync.sync()
        self.assertEqual(len(self.issues),self.sync.MAX_NEW_ISSUES)

    def test_credentials_only_go_to_exact_github_host_no_redirects(self):
        spec=importlib.util.spec_from_file_location('sync_http',ROOT/'tools/sync-error-reports.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.TOKEN='fixture-only-token'
        response=Mock();response.read.return_value=b'{}'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(mod.urllib.request,'build_opener',return_value=opener):
            mod.request_json('https://api.github.com.evil.invalid/feed')
            self.assertIsNone(opener.open.call_args[0][0].get_header('Authorization'))
            mod.request_json('https://api.github.com/repos/a/b/issues')
            self.assertEqual(opener.open.call_args[0][0].get_header('Authorization'),'Bearer fixture-only-token')
        with self.assertRaises(RuntimeError): mod.NoRedirect().redirect_request(None,None,None,None,None,None)
        with self.assertRaises(ValueError): mod.request_json('http://api.github.com/repos/a/b/issues')

if __name__=='__main__': unittest.main()
