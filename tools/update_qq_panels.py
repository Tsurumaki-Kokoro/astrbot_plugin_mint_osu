"""Create or update Mint command panels for QQ private and group chats."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlencode, quote

from update_qq_menu import request_json, menu_matches

PAYLOAD_PATH = Path(__file__).resolve().parents[1] / "qq_panel.json"
BASE = "https://api.sgroup.qq.com/v2/panels"


def validate_panel(panel):
    if not 1 <= len(panel["items"]) <= 20:
        raise ValueError("面板指令数量必须为 1～20。")
    for item in panel["items"]:
        for key, limit in [("name", 14), ("desc", 30)]:
            value = item[key]
            if not value or sum(1 if ord(c) < 128 else 2 for c in value) > limit:
                raise ValueError(f"面板 {key} 长度超过 QQ 限制。")
        if item["type"] != "command" or item.get("only_admin") is not False:
            raise ValueError("Mint 指令应允许所有用户使用。")


def panel_matches(actual, expected):
    # QQ strips the command slash and omits false only_admin values on reads.
    if not isinstance(actual, dict):
        return False
    actual = json.loads(json.dumps(actual))
    expected = json.loads(json.dumps(expected))
    for panel in (actual, expected):
        for item in panel.get("items", []):
            if item.get("type") == "command":
                item["name"] = item["name"].lstrip("/")
            item.setdefault("only_admin", False)
    return menu_matches(actual, expected)


def list_panels(scope, headers):
    records, cursor, seen = [], "", set()
    while True:
        query = {"scope": scope, "limit": 50}
        if cursor:
            query["cursor"] = cursor
        result = request_json("GET", BASE + "?" + urlencode(query), headers=headers)
        records.extend(result.get("records", []))
        cursor = result.get("next_cursor", "")
        if result.get("is_end") or not cursor:
            return records
        if cursor in seen:
            raise RuntimeError("QQ 分页游标重复，停止更新。")
        seen.add(cursor)


def publish(config_path, platform_id, panel):
    validate_panel(panel)
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    platforms = [p for p in config.get("platform", []) if p.get("enable")
                 and p.get("type") == "qq_official"
                 and (platform_id is None or p.get("id") == platform_id)]
    if len(platforms) != 1:
        raise ValueError("请通过 --platform-id 选择唯一启用的 QQ 官方机器人。")
    platform = platforms[0]
    appid = str(platform["appid"])
    token = request_json("POST", "https://bots.qq.com/app/getAppAccessToken",
                         {"appId": appid, "clientSecret": platform["secret"]})
    headers = {"Authorization": "QQBot " + token["access_token"], "X-Union-Appid": appid}
    previous = {scope: list_panels(scope, headers) for scope in ("c2c", "group")}
    # Stop before writes if the intended global panel is ambiguous.
    targets = {}
    for scope, records in previous.items():
        matches = [r for r in records if r.get("target_type") == "all"]
        if len(matches) > 1:
            matches = [r for r in matches if r.get("panel", {}).get("remark") == panel["remark"]]
            if len(matches) != 1:
                raise ValueError(f"{scope} 存在多个全局面板，无法确定更新对象。")
        targets[scope] = matches[0] if matches else None
    backup_dir = Path(config_path).resolve().parent / "temp"
    backup_dir.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="qq-panels-backup-", suffix=".json", dir=backup_dir)
    with os.fdopen(fd, "w") as stream:
        json.dump(previous, stream, ensure_ascii=False, indent=2)
    print(f"旧面板已备份：{name}")
    for scope, target in targets.items():
        if target:
            panel_id = target["panel_id"]
            request_json("PUT", BASE + "/" + quote(panel_id, safe=""), {"panel": panel}, headers)
        else:
            result = request_json("POST", BASE, {"scope": scope, "target_type": "all", "panel": panel}, headers)
            panel_id = result["panel_id"]
        # Report successful writes before verification so partial success is visible.
        print(f"{scope} 面板已提交：{panel_id}")
        records = list_panels(scope, headers)
        current = next((r for r in records if r["panel_id"] == panel_id), None)
        if current is None or not panel_matches(current.get("panel"), panel):
            raise RuntimeError(f"{scope} 面板读取核验失败；请检查已提交面板。")
        print(f"{scope} 面板核验通过，版本 {current.get('version', '未知')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--platform-id")
    args = parser.parse_args()
    try:
        publish(args.config, args.platform_id, json.loads(PAYLOAD_PATH.read_text()))
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
