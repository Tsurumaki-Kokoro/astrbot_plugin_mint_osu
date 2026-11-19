"""Weekly, group-scoped song guessing standings and awards."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from fractions import Fraction
import json
import sqlite3
from time import time

from .usage_stats import LOCAL


def week_start(timestamp):
    date = datetime.fromtimestamp(timestamp, LOCAL)
    return date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=date.weekday())


class SongLeaderboard:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS rounds (
                session TEXT NOT NULL, ended REAL NOT NULL, owner TEXT NOT NULL,
                owner_name TEXT NOT NULL, title TEXT NOT NULL, winner TEXT,
                expired INTEGER NOT NULL, attempts TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS rounds_session_week ON rounds(session, ended);
            CREATE INDEX IF NOT EXISTS rounds_expiry ON rounds(ended);
        """)

    def close(self):
        self.db.close()

    def record(self, session, ended, owner, owner_name, title, winner, expired, attempts):
        with self.db:
            self.db.execute("INSERT INTO rounds VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                session, ended, owner, owner_name, title,
                json.dumps(winner, ensure_ascii=False) if winner else None,
                expired, json.dumps(attempts, ensure_ascii=False),
            ))
            self.db.execute("DELETE FROM rounds WHERE ended < ?",
                            ((week_start(ended) - timedelta(days=14)).timestamp(),))

    def render(self, session, *, previous=False, now=None):
        start = week_start(time() if now is None else now) - timedelta(days=7 * previous)
        end = start + timedelta(days=7)
        rounds = self.db.execute(
            "SELECT owner, owner_name, title, winner, expired, attempts FROM rounds "
            "WHERE session = ? AND ended >= ? AND ended < ? ORDER BY ended, rowid",
            (session, start.timestamp(), end.timestamp()),
        ).fetchall()
        header = f"🎵 {'上周' if previous else '本周'}猜歌这一块 · {start:%m-%d}～{end - timedelta(days=1):%m-%d}"
        if not rounds:
            return header + "\n暂无已结算的猜歌。"

        names, streaks, wrong_max = {}, Counter(), Counter()
        wins, no_hints, model_wins, hosts, timeouts = (Counter() for _ in range(5))
        local_scores = defaultdict(list)
        fastest, fastest_wrong, near_miss = [], [], []
        last_winner, streak = None, 0

        for owner, owner_name, title, raw_winner, expired, raw_attempts in rounds:
            names[owner] = owner_name
            winner = json.loads(raw_winner) if raw_winner else None
            winner_id = winner[0] if winner else None
            if expired:
                timeouts[owner] += 1
            if winner:
                player, name, score, elapsed, hints = winner
                names[player] = name
                wins[player] += 1
                hosts[owner] += 1
                streak = streak + 1 if last_winner == player else 1
                streaks[player] = max(streaks[player], streak)
                last_winner = player
                if not hints:
                    no_hints[player] += 1
                    fastest.append((elapsed, player, title))
                if score is None:
                    model_wins[player] += 1
                else:
                    local_scores[player].append(score)
            else:
                last_winner, streak = None, 0

            wrong_this_round = Counter()
            for player, name, verdict, elapsed, similarity in json.loads(raw_attempts):
                names[player] = name
                if verdict == "different":
                    fastest_wrong.append((elapsed, player, title))
                    if player != winner_id:
                        wrong_this_round[player] += 1
                elif verdict == "same":
                    near_miss.append((similarity, player, title))
            for player, count in wrong_this_round.items():
                wrong_max[player] = max(wrong_max[player], count)

        lines = [header]
        for place, (player, count) in enumerate(wins.most_common(10), 1):
            lines.append(f"{place}. {names[player]} · {count} 局")
        if not wins:
            lines.append("本周还没有人答对。" if not previous else "上周无人答对。")

        def award(title, scores, describe):
            if scores:
                best = max(scores.values())
                players = "、".join(names[player] for player, value in scores.items() if value == best)
                lines.append(f"「{title}」 · {players}（{describe(best)}）")

        def moment(title, candidates, *, highest=False):
            if candidates:
                value, player, song = (max if highest else min)(candidates, key=lambda item: item[0])
                detail = f"匹配度 {value / 100:.2f}%" if highest else f"{value / 1000:.3f} 秒"
                lines.append(f"「{title}」 · {names[player]}（{detail} · 《{song}》）")

        award("最佳搜狗",
              {player: (Fraction(sum(scores), len(scores)), len(scores))
               for player, scores in local_scores.items() if len(scores) >= 3},
              lambda value: f"平均匹配度 {float(value[0]) / 100:.2f}% · {value[1]} 局")
        award("爽！这才叫音乐！", no_hints, lambda value: f"无提示答对 {value} 局")
        moment("报起来吧！", fastest)
        award("直接王朝", {player: value for player, value in streaks.items() if value >= 2},
              lambda value: f"连胜 {value} 局")
        award("再来亿局", hosts, lambda value: f"开出的题被答对 {value} 局")
        award("这也行！但确实准啊！", model_wins, lambda value: f"模型判对并结算 {value} 局")
        moment("这也能空啊！", near_miss, highest=True)
        moment("先报了再说", fastest_wrong)
        award("哦？哦？哦？", {player: value for player, value in wrong_max.items() if value >= 2},
              lambda value: f"单局提交 {value} 个不同错答")
        award("玩大哥，这个歌叫什么名字？", timeouts, lambda value: f"开出的题有 {value} 局超时")
        return "\n".join(lines)
