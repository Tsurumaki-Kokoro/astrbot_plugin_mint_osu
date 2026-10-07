import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_qq_menu", ROOT / "tools/update_qq_menu.py")
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class QQMenuTests(unittest.TestCase):
    def test_published_menu_respects_qq_limits(self):
        menu.validate_menu(json.loads(menu.PAYLOAD_PATH.read_text()))

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
