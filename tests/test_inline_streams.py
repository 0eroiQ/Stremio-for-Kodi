"""Inline sources: safe text, geometry, focus, resolver mapping and late replies."""
import ast
import importlib.util
from pathlib import Path
import threading
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from lib.stream_presenter import line, presentation, playback_meta

ROOT = Path(__file__).resolve().parents[1]

class Item:
    def __init__(self, label): self.label, self.props = label, {}
    def setProperty(self, key, value): self.props[key] = value

class Control:
    def __init__(self): self.rows, self.pos, self.resets = [], 2, 0
    def reset(self): self.rows, self.pos, self.resets = [], 0, self.resets + 1
    def addItem(self, item): self.rows.append(item)
    def selectItem(self, pos): self.pos = pos
    def getSelectedPosition(self): return self.pos

class InlineTests(unittest.TestCase):
    def setUp(self):
        self.api, self.kodi = Mock(), Mock()
        self.gui = types.SimpleNamespace(ListItem=Item)
        self.mods = patch.dict('sys.modules', {'lib.backend': self.api, 'xbmcgui': self.gui, 'xbmc': self.kodi})
        self.mods.start(); self.addCleanup(self.mods.stop)
        import lib
        self.attr = patch.object(lib, 'backend', self.api, create=True)
        self.attr.start(); self.addCleanup(self.attr.stop)
        spec = importlib.util.spec_from_file_location('inline_test_module', ROOT / 'lib/inline_streams.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        class Shell(module.InlineStreams):
            def __init__(self):
                self.props, self.controls, self.focus = {}, {}, 501
                self.active_list, self.preview_suspended = 501, False
                self.meta = {'type':'series','id':'tt1','name':'Show',
                             'videos':[{'id':'tt1:2:4','name':'Episode','season':2,'episode':4}]}
                self.cancel_trailer, self.close = Mock(), Mock()
                self.section_cache = {}; self.init_streams()
            def getControl(self, cid): return self.controls.setdefault(cid, Control())
            def getFocusId(self): return self.focus
            def setFocusId(self, cid): self.focus = cid
            def getProperty(self, key): return self.props.get(key, '')
            def setProperty(self, key, value): self.props[key] = value
            def clearProperty(self, key): self.props.pop(key, None)
        self.win, self.module = Shell(), module
        self.rows = [{'provider':'A','label':'A · 4K HEVC 9 GB\nfilm.mkv','url':'https://example.test/a'},
                     {'provider':'B','label':'B · 1080p 2 GB\nother.mkv','url':'https://example.test/b'}]
        self.win.section_cache['streams:tt1:2:4'] = (self.rows,0,0)

    def test_text_is_single_line_and_no_raw_url(self):
        self.assertEqual(line('a\r\nb\t[B]c[/B]'), 'a b c')
        self.assertNotIn('secret', line('https://host.test/secret'))
        self.assertEqual(line('a[CR]b'), 'ab')
        value = presentation(self.rows[0])
        self.assertNotIn('\n', value['detail']); self.assertIn('H.265', value['title'])

    def test_open_back_restores_episode_without_playing(self):
        w=self.win; w.choose_source('tt1:2:4',resume_ms=65000)
        self.assertEqual(w.getProperty('streams_open'),'true'); self.assertEqual(w.focus,7100)
        action=Mock(); action.getId.return_value=92
        self.assertTrue(w.streams_action(action)); self.assertFalse(w._streams_open)
        self.assertEqual(w.getControl(501).pos,2); self.assertEqual(w.getControl(501).resets,0)
        self.kodi.executebuiltin.assert_called_with('SetFocus(501)')
        self.api.play.assert_not_called(); w.close.assert_not_called()

    def test_selection_plays_the_correct_original_stream(self):
        w=self.win; w.choose_source('tt1:2:4',resume_ms=65000)
        self.assertEqual(w.focus,7100)
        self.assertEqual(len(w._streams_visible),2)
        self.assertEqual(w._streams_visible,self.rows)
        w.getControl(7100).selectItem(1); w.streams_click(7100)
        meta,identity,row,resume=self.api.play.call_args.args
        self.assertIs(row,self.rows[1]); self.assertEqual(resume,65000)
        self.assertEqual((identity,meta['season'],meta['episode']),('tt1:2:4',2,4))
        self.assertEqual(meta['_media_type'],'episode'); self.assertFalse(w._streams_open)

    def test_unrecognized_click_does_not_operate_hidden_controls(self):
        self.win.choose_source('tt1:2:4')
        self.assertTrue(self.win.streams_click(21005)); self.api.play.assert_not_called()

    def test_empty_and_failed_results_leave_back_and_retry(self):
        w=self.win; w.choose_source('tt1:2:4')
        for result in (None,([],3,2)):
            w._show_stream_result(w._streams_generation,result)
            self.assertFalse(w.getProperty('streams_ready')); self.assertEqual(w.focus,7103)
            self.assertTrue(w.getProperty('streams_message')); self.assertTrue(w._streams_open)

    def test_late_reply_cannot_reopen_closed_panel(self):
        w=self.win; w.section_cache.clear()
        started,release=threading.Event(),threading.Event()
        def fetch(*args): started.set(); release.wait(2); return self.rows,0,0
        self.api.source_rows.side_effect=fetch
        w.choose_source('tt1:2:4'); self.assertTrue(started.wait(1))
        worker=w._streams_worker; w.close_streams(); release.set(); worker.join(2)
        self.assertFalse(w._streams_open); self.assertFalse(w.getProperty('streams_open'))
        self.assertIsNone(w._streams_worker); self.api.play.assert_not_called()

    def test_thread_failure_is_retryable_and_not_a_crash(self):
        w=self.win; w.section_cache.clear()
        with patch.object(self.module.threading,'Thread',side_effect=RuntimeError('no thread')):
            w.choose_source('tt1:2:4')
        self.assertFalse(w.getProperty('streams_loading')); self.assertEqual(w.focus,7103)

    def test_movie_metadata_is_preserved(self):
        meta={'id':'tt2','type':'movie','name':'Movie'}
        self.assertEqual(playback_meta(meta,'tt2'),meta)
        self.assertIsNot(playback_meta(meta,'tt2'),meta)

    def test_playback_queue_failure_leaves_panel_open(self):
        w=self.win; self.api.play.side_effect=OSError('private detail')
        w.choose_source('tt1:2:4'); w.getControl(7100).selectItem(0); w.streams_click(7100)
        self.assertTrue(w._streams_open)
        self.assertNotIn('private',w.getProperty('streams_message'))

    def test_episode_xml_is_inside_reversible_flip_group(self):
        tree=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-info.xml')
        group=tree.find('.//control[@id="7001"]')
        self.assertIsNotNone(group.find('.//control[@id="501"]'))
        self.assertIn('streams_open',group.findtext('visible'))
        self.assertEqual({a.get('type') for a in group.findall('animation')},{'Visible','Hidden'})
        panel=tree.find('.//control[@id="7000"]')
        self.assertGreaterEqual(int(panel.findtext('left')),900)
        self.assertIsNotNone(panel.find('.//effect[@type="rotatey"]'))
        for layout in panel.findall('.//control[@id="7100"]/*'):
            if layout.tag not in ('itemlayout','focusedlayout'): continue
            labels=layout.findall('control[@type="label"]')
            first,second=labels
            self.assertLessEqual(int(first.findtext('top'))+int(first.findtext('height')),int(second.findtext('top')))
            self.assertLessEqual(int(second.findtext('top'))+int(second.findtext('height')),114)

    def test_all_themes_keep_translucency_and_reduced_motion(self):
        from lib.theme import apply,PALETTES
        from lib.appearance import apply as appearance
        for index,palette in enumerate(PALETTES):
            tree=ET.parse(ROOT/'resources/skins/Main/1080i/script-stremio-info.xml')
            apply(tree,index)
            panel=tree.find('.//control[@id="7000"]')
            row=panel.find('.//itemlayout/control[@type="image"]/texture')
            self.assertEqual(row.get('colordiffuse'),'B8'+palette[2][2:])
            appearance(tree,{'animations':False})
            self.assertTrue(all(n.get('time')=='0' for n in panel.iter('effect')))
            self.assertTrue(all(n.get('delay','0')=='0' for n in panel.iter('effect')))

if __name__=='__main__': unittest.main()
