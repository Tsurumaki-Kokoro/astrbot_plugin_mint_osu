"""Local usage analytics for the AstrBot dashboard."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
from time import time

LOCAL = timezone(timedelta(hours=8))
DAY = 86400
PAGE_SIZE = 30


class UsageStats:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA secure_delete = ON;
            CREATE TABLE IF NOT EXISTS commands (
                timestamp INTEGER, platform TEXT, group_id TEXT, command TEXT,
                result TEXT, duration_ms INTEGER
            );
            CREATE INDEX IF NOT EXISTS commands_time ON commands(timestamp);
            CREATE TABLE IF NOT EXISTS judgments (
                timestamp INTEGER, platform TEXT, group_id TEXT, provider TEXT,
                model TEXT, answer TEXT, title TEXT, result TEXT, settled INTEGER,
                duration_ms INTEGER, input_other INTEGER, input_cached INTEGER,
                output INTEGER, amount TEXT, currency TEXT, price_version TEXT,
                price_source TEXT, price_tier TEXT, price_rates TEXT
            );
            CREATE INDEX IF NOT EXISTS judgments_time ON judgments(timestamp);
            CREATE TABLE IF NOT EXISTS judgment_history (
                timestamp INTEGER, platform TEXT, group_id TEXT, provider TEXT, model TEXT,
                currency TEXT, result TEXT, settled INTEGER, amount TEXT, count INTEGER,
                input_other INTEGER, input_cached INTEGER, output INTEGER, usage_count INTEGER
            );
            CREATE INDEX IF NOT EXISTS judgment_history_time ON judgment_history(timestamp);
        """)
        self.prune()

    def close(self):
        self.db.close()

    def prune(self):
        now = int(time())
        with self.db:
            cutoff = now - 7 * DAY
            self.db.execute(
                """INSERT INTO judgment_history
                   SELECT timestamp / 3600 * 3600, platform, group_id, provider, model,
                          currency, result, settled, amount, count(*), sum(input_other),
                          sum(input_cached), sum(output), count(output)
                   FROM judgments WHERE timestamp <= ? GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9""",
                (cutoff,),
            )
            self.db.execute("DELETE FROM judgments WHERE timestamp <= ?", (cutoff,))
            self.db.execute("DELETE FROM judgment_history WHERE timestamp < ?", (now - 31 * DAY,))
            self.db.execute("DELETE FROM commands WHERE timestamp < ?", (now - 31 * DAY,))

    def command(self, timestamp, platform, group_id, command, result, duration_ms):
        with self.db:
            self.db.execute("INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?)",
                            (int(timestamp), platform, group_id, command, result, duration_ms))

    def judgment(self, timestamp, platform, group_id, provider, model, answer, title,
                 result, settled, duration_ms, usage, price):
        usage = usage or {}
        price = price or {}
        with self.db:
            self.db.execute("INSERT INTO judgments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (int(timestamp), platform, group_id, provider, model, answer, title, result,
                             settled, duration_ms, usage.get("input_other"), usage.get("input_cached"),
                             usage.get("output"), price.get("amount"), price.get("currency"),
                             price.get("version"), price.get("source"), price.get("tier"),
                             json.dumps(price["rates"]) if "rates" in price else None))

    @staticmethod
    def filters(days, platform, group, *, rolling=False, hour=None, weekday=None):
        now = datetime.fromtimestamp(time(), LOCAL)
        start = now.timestamp() - days * DAY if rolling else (
            now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        ).timestamp()
        clause = "timestamp > ?" if rolling else "timestamp >= ?"
        params = [int(start)]
        if hour is not None:
            clause += " AND (timestamp / 3600 + 8) % 24 = ?"
            params.append(hour)
        if weekday is not None:
            clause += " AND ((timestamp / 3600 + 8) / 24 + 3) % 7 = ?"
            params.append(weekday)
        if platform:
            clause += " AND platform = ?"
            params.append(platform)
        if group:
            clause += " AND group_id = ?"
            params.append("" if group == "__private__" else group)
        return clause, params

    def judgments(self, days, platform="", group="", model="", result="", page=1, *, hour=None, weekday=None):
        clause, params = self.filters(min(days, 7), platform, group, rolling=True, hour=hour, weekday=weekday)
        if model:
            clause += " AND model = ?"
            params.append(model)
        if result:
            clause += " AND result = ?"
            params.append(result)
        total = self.db.execute(f"SELECT count(*) FROM judgments WHERE {clause}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT * FROM judgments WHERE {clause} ORDER BY timestamp DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        )
        items = [dict(row) for row in rows]
        for item in items:
            if item["price_rates"]:
                item["price_rates"] = json.loads(item["price_rates"])
        return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}

    def summary(self, days, platform="", group="", *, hour=None, weekday=None):
        clause, params = self.filters(days, platform, group, hour=hour, weekday=weekday)
        rows = self.db.execute(
            f"""SELECT command, count(*) AS count,
                       sum(result = 'technical') AS errors, sum(result = 'business') AS business,
                       max(CASE WHEN position = (95 * total + 99) / 100 THEN duration_ms END) AS p95_ms
                FROM (
                    SELECT *, row_number() OVER (PARTITION BY command ORDER BY duration_ms) AS position,
                              count(*) OVER (PARTITION BY command) AS total
                    FROM commands WHERE {clause} AND command <> 'local_win'
                ) GROUP BY command ORDER BY count DESC, command""", params
        ).fetchall()
        days_usage, hours, groups = Counter(), Counter(), defaultdict(Counter)
        local_wins = private_count = 0
        for row in self.db.execute(
            f"""SELECT timestamp / 3600 AS hour, platform, group_id, command = 'local_win' AS local_win,
                       count(*) AS count FROM commands WHERE {clause} GROUP BY 1, 2, 3, 4""", params
        ):
            if row["local_win"]:
                local_wins += row["count"]
                continue
            dt = datetime.fromtimestamp(row["hour"] * 3600, LOCAL)
            day = dt.date().isoformat()
            days_usage[day] += row["count"]
            hours[dt.weekday(), dt.hour] += row["count"]
            if row["group_id"]:
                groups[row["platform"], row["group_id"]][day] += row["count"]
            else:
                private_count += row["count"]

        models = defaultdict(Counter)
        for row in self.db.execute(
            f"""SELECT provider, model, currency, result, settled, amount, count(*) AS count,
                       sum(input_other) AS input_other, sum(input_cached) AS input_cached,
                       sum(output) AS output, count(output) AS usage_count
                FROM judgments WHERE {clause} GROUP BY 1, 2, 3, 4, 5, 6
                UNION ALL
                SELECT provider, model, currency, result, settled, amount, sum(count),
                       sum(input_other), sum(input_cached), sum(output), sum(usage_count)
                FROM judgment_history WHERE {clause} GROUP BY 1, 2, 3, 4, 5, 6""", params * 2
        ):
            target = models[row["provider"], row["model"], row["currency"]]
            count = row["count"]
            for key in ("count", "input_other", "input_cached", "output", "usage_count"):
                target[key] += row[key] or 0
            target["settled"] += count * row["settled"]
            target["unsure"] += count * (row["result"] == "unsure")
            target["priced"] += count if row["amount"] is not None else 0
            target["amount"] += Decimal(row["amount"] or "0") * count

        group_clause, group_params = self.filters(days, platform, "", hour=hour, weekday=weekday)
        group_total = self.db.execute(
            f"SELECT count(*) FROM commands WHERE {group_clause} AND group_id <> '' AND command <> 'local_win'",
            group_params,
        ).fetchone()[0]
        return {
            "group_total": group_total, "private_count": private_count,
            "commands": [dict(row) for row in rows],
            "groups": sorted([
                dict(platform=kind, group_id=gid, count=sum(counts.values()), active_days=len(counts))
                for (kind, gid), counts in groups.items()
            ], key=lambda row: -row["count"]),
            "hours": [dict(weekday=weekday, hour=hour, count=count) for (weekday, hour), count in hours.items()],
            "days": [dict(day=day, count=count) for day, count in sorted(days_usage.items())],
            "models": [
                dict(metrics, provider=provider, model=model, currency=currency,
                     amount=str(metrics["amount"]) if metrics["priced"] else None)
                for (provider, model, currency), metrics in models.items()
            ],
            "local_wins": local_wins, "active_groups": len(groups),
            "coverage_start": self.db.execute(
                "SELECT min(timestamp) FROM (SELECT min(timestamp) AS timestamp FROM commands "
                "UNION ALL SELECT min(timestamp) FROM judgments "
                "UNION ALL SELECT min(timestamp) FROM judgment_history)"
            ).fetchone()[0],
        }
