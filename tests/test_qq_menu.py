import importlib.util
import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_qq_menu", ROOT / "tools/update_qq_menu.py")
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class QQMenuTests(unittest.TestCase):
    def test_published_menu_respects_qq_limits(self):
        menu.validate_menu(json.loads(menu.PAYLOAD_PATH.read_text()))

    def test_private_menu_commands_are_complete_and_work_in_private_chat(self):
        spec = importlib.util.spec_from_file_location('private_menu_arguments', ROOT / 'arguments.py')
        arguments = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = arguments
        spec.loader.exec_module(arguments)
        payload = json.loads(menu.PAYLOAD_PATH.read_text())
        commands = []
        for item in payload['menu']['items']:
            for entry in item.get('sub_menu_items', [item]):
                text = entry['send_message']
                command = arguments.parse_command(text, [])
                self.assertNotIn(command.name, {'rank', 'top5', 'mpwatch'})
                commands.append(text)
        self.assertEqual(set(commands), {'/minthelp', '/statme', '/history', '/oa', '/pr', '/recent', '/bp', '/bp 1-10', '/nb', '/fix', '/analyze', '/unbind'})

    def test_verification_allows_platform_icons_but_rejects_changed_commands(self):
        expected = {"items": [{"name": "帮助", "type": "send_message", "send_message": "/minthelp"}]}
        actual = json.loads(json.dumps(expected))
        actual["items"][0]["icon"] = "https://example.com/icon.png"
        self.assertTrue(menu.menu_matches(actual, expected))
        actual["items"][0]["send_message"] = "/help"
        self.assertFalse(menu.menu_matches(actual, expected))
        self.assertFalse(menu.menu_matches({"items": []}, expected))

    def test_oversized_or_nested_submenus_are_rejected(self):
        item = {"name": "菜单", "type": "menu", "sub_menu_items": [
            {"name": "项目", "type": "send_message", "send_message": "/minthelp"}] * 6}
        with self.assertRaises(ValueError):
            menu.validate_menu({"menu": {"items": [item]}})
        item["sub_menu_items"] = [{"name": "嵌套", "type": "menu", "sub_menu_items": []}]
        with self.assertRaises(ValueError):
            menu.validate_menu({"menu": {"items": [item]}})
