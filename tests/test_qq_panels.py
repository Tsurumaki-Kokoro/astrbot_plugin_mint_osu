import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import update_qq_panels as panels
spec = importlib.util.spec_from_file_location('panel_arguments', ROOT / 'arguments.py')
arguments = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = arguments
spec.loader.exec_module(arguments)


class QQPanelTests(unittest.TestCase):
    def test_panel_limits_and_command_parser_coverage(self):
        panel = json.loads(panels.PAYLOAD_PATH.read_text())
        panels.validate_panel(panel)
        names = {i['name'][1:] for i in panel['items']}
        self.assertEqual(names, {'minthelp', 'statme', 'stat', 'pr', 'recent', 'bp', 'nb',
                                'fix', 'analyze', 'history', 'score', 'scorehistory',
                                'beatmap', 'bind', 'mode', 'unbind'})
        for item in panel['items']:
            suffix = {'/stat': ' Player Name', '/bind': ' Player Name', '/mode': ' 3',
                      '/score': ' 123', '/scorehistory': ' 123', '/beatmap': ' 123'}.get(item['name'], '')
            self.assertEqual(arguments.parse_command(item['name'] + suffix, []).name, item['name'][1:])

    def test_pagination_collects_all_records(self):
        with patch.object(panels, 'request_json', side_effect=[
            {'records': [{'panel_id': 'a'}], 'next_cursor': 'next', 'is_end': False},
            {'records': [{'panel_id': 'b'}], 'is_end': True}]) as request:
            self.assertEqual([r['panel_id'] for r in panels.list_panels('group', {})], ['a', 'b'])
            self.assertIn('cursor=next', request.call_args.args[1])

    def test_verification_accepts_qq_normalization_and_rejects_changed_command(self):
        expected = {'items': [{'name': '/bp', 'desc': '最佳成绩', 'type': 'command', 'only_admin': False}]}
        actual = {'items': [{'name': 'bp', 'desc': '最佳成绩', 'type': 'command'}]}
        self.assertTrue(panels.panel_matches(actual, expected))
        actual['items'][0]['name'] = 'pr'
        self.assertFalse(panels.panel_matches(actual, expected))
