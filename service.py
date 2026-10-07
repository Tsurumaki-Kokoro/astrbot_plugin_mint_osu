"""Translate parsed commands into the existing MintAPI contract."""
from dataclasses import dataclass
from .arguments import Command
from .identity import Identity


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    params: dict
    body: dict | None = None
    image: bool = True


def build_request(command: Command, caller: Identity, theme: str) -> Request:
    name = command.name
    identity = {"platform": caller.platform, "platform_uid": command.target_uid or caller.uid}
    params = dict(identity)
    if command.mode is not None:
        params["game_mode"] = command.mode
    if name in {"stat", "statme"}:
        params["theme"] = theme
        if command.username:
            params["user_name"] = command.username
        return Request("GET", "/user_info", params)
    if name in {"pr", "recent"}:
        params.update(include_fails=name == "recent", recent_index=1, theme=theme)
        return Request("GET", "/score/recent_play", params)
    if name == "bp":
        params["best_index"] = command.first
        if command.last is not None:
            params["best_end"] = command.last
            return Request("GET", "/score/best_plays", params)
        params["theme"] = theme
        return Request("GET", "/score/best_play", params)
    if name == "beatmap":
        return Request("GET", "/beatmap/beatmap", {"beatmap_id": command.beatmap_id, "theme": "default"})
    body = {"platform": caller.platform, "platformUid": caller.uid}
    if name == "bind":
        body["osuUsername"] = command.username
    elif name == "mode":
        body["gameMode"] = command.mode
    path = {"bind": "/users/bind", "unbind": "/users/unbind", "mode": "/users/update_mode"}[name]
    return Request("POST", path, {}, body, image=False)


def error_message(command: Command, status: int, detail: str, retry_after: str | None) -> str:
    if status == 403:
        return "MintAPI 鉴权或访问失败，请管理员检查接口密钥。"
    if status == 409 and command.name == "bind":
        return "你已经绑定过账号，请先使用 /unbind 解绑。"
    if status == 404:
        if "osu! user not found" in detail:
            return "找不到这个 osu! 玩家，请检查用户名。"
        if "User not found" in detail or "binding not found" in detail:
            return "对方尚未绑定 osu! 账号。" if command.target_uid else "你尚未绑定 osu! 账号，请使用 /bind 用户名。"
        if command.name in {"pr", "recent", "bp"}:
            return "没有符合条件的成绩。"
        return "没有找到对应玩家或谱面。"
    if status == 400 and command.name == "bind":
        return "绑定失败，请检查 osu! 用户名。"
    if status == 400:
        return "请求参数无效或成绩查询失败，请检查命令后重试。"
    if status in {429, 503}:
        seconds = retry_after if retry_after and retry_after.isdigit() else "几"
        return f"服务暂时繁忙，请在 {seconds} 秒后重试。"
    return "MintAPI 暂时无法完成请求，请稍后重试。"
