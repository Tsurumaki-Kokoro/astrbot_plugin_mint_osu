import importlib
import unittest
from datetime import datetime, timezone

from test_plugin import package


class LeaderboardTests(unittest.TestCase):
    def test_weekly_awards_and_group_scope(self):
        module = importlib.import_module(package + ".song_leaderboard")
        store = module.SongLeaderboard(":memory:")
        self.addCleanup(store.close)
        now = datetime(2026, 11, 19, tzinfo=timezone.utc).timestamp()
        for player, score in (("准哥", 10000), ("快哥", 9000)):
            for index in range(3):
                store.record("room", now + index, "房主", "房主", "标准曲名",
                             (player, player, score, 2000 if score == 10000 else 1000, 0),
                             False, [("路人", "路人", "different", 200, 0)])
        board = store.render("room", now=now)
        self.assertIn("「最佳搜狗」 · 准哥", board)
        self.assertIn("「报起来吧！」 · 快哥", board)
        self.assertIn("「先报了再说」 · 路人", board)
        self.assertNotIn("准哥", store.render("other", now=now))
        self.assertNotIn("准哥", store.render("room", previous=True, now=now))
