"""Publish Mint's C2C menu using an existing AstrBot QQ official configuration."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PAYLOAD_PATH = Path(__file__).resolve().parents[1] / "qq_menu.json"


def validate_menu(payload):
    items = payload["menu"]["items"]
    if not 1 <= len(items) <= 10:
        raise ValueError("一级菜单数量必须为 1～10。")
    for item in items:
        validate_item(item, 10, child=False)


def validate_item(item, limit, child):
    # QQ counts a Chinese character as two characters.
    if not item.get("name") or sum(1 if ord(c) < 128 else 2 for c in item["name"]) > limit:
        raise ValueError("菜单名称超过 QQ 长度限制。")
    kind = item.get("type")
    if kind == "menu" and not child:
        children = item.get("sub_menu_items", [])
        if not 1 <= len(children) <= 5:
            raise ValueError("子菜单数量必须为 1～5。")
        for entry in children:
            validate_item(entry, 14, child=True)
    elif kind == "send_message" and item.get("send_message"):
        return
    else:
        raise ValueError("Mint 菜单仅支持折叠菜单和发送指令。")


def menu_matches(actual, expected):
    """Compare configured fields while allowing QQ-generated icons and metadata."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and menu_matches(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            menu_matches(a, e) for a, e in zip(actual, expected))
    return actual == expected


def request_json(method, url, payload=None, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = Request(url, data=body, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        # Never expose headers, credentials or upstream response bodies.
        raise RuntimeError(f"QQ 接口请求失败：HTTP {exc.code}。") from None
    except URLError:
        raise RuntimeError("无法连接 QQ 接口。") from None


def publish(config_path, platform_id, payload):
    validate_menu(payload)
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    platforms = [p for p in config.get("platform", [])
                 if p.get("type") in {"qq_official", "qq_official_webhook"}
                 and p.get("enable") and (platform_id is None or p.get("id") == platform_id)]
    if len(platforms) != 1:
        raise ValueError("请通过 --platform-id 选择唯一启用的 QQ 官方机器人。")
    platform = platforms[0]
    appid, secret = str(platform["appid"]), platform["secret"]
    token = request_json("POST", "https://bots.qq.com/app/getAppAccessToken",
                         {"appId": appid, "clientSecret": secret})
    access_token = token.get("access_token")
    if not access_token:
        raise RuntimeError("QQ 未返回访问凭证。")
    headers = {"Authorization": "QQBot " + access_token, "X-Union-Appid": appid}
    endpoint = "https://api.sgroup.qq.com/v2/menu"
    previous = request_json("GET", endpoint, headers=headers)
    # Create a private backup outside the plugin repository before replacing the menu.
    backup_dir = Path(config_path).resolve().parent / "temp"
    backup_dir.mkdir(exist_ok=True)
    fd, backup_name = tempfile.mkstemp(prefix="qq-menu-backup-", suffix=".json", dir=backup_dir)
    with os.fdopen(fd, "w") as stream:
        json.dump(previous, stream, ensure_ascii=False, indent=2)
    print(f"旧菜单已备份：{backup_name}")
    result = request_json("PUT", endpoint, payload, headers)
    print(f"QQ 已接受菜单更新，版本：{result.get('version', '未知')}")
    current = request_json("GET", endpoint, headers=headers)
    if not menu_matches(current.get("menu"), payload["menu"]):
        raise RuntimeError("更新后的菜单与提交内容不一致，请检查 QQ 菜单；旧配置已备份。")
    print("已读取并核验线上菜单。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="AstrBot data/cmd_config.json")
    parser.add_argument("--platform-id")
    args = parser.parse_args()
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    try:
        publish(args.config, args.platform_id, payload)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
