"""Translate parsed commands into the existing MintAPI contract."""
from dataclasses import dataclass
import json
from .arguments import Command
from .identity import Identity


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    params: dict
    body: dict | None = None
    image: bool = True
    image_types: tuple[str, ...] = ("png",)
    video: bool = False


def build_request(command: Command, caller: Identity, theme: str) -> Request:
    name = command.name
    if name == "oa":
        return Request("GET", "/user_info/avatar_card", {"platform": caller.platform, "platform_uid": command.target_uid or caller.uid})
    if name == "pp":
        return Request("GET", "/user_info/extra/performance_control", {"platform": caller.platform, "platform_uid": command.target_uid or caller.uid, "pp": command.pp}, image=False)
    if name == "previewvideo":
        params = {"beatmap_id": command.beatmap_id, "start": command.start, "duration": command.duration}
        if command.mods and command.mods != "NM":
            params["mods"] = command.mods.split(',')
        return Request("GET", "/beatmap/preview/video", params, image=False, video=True)
    if name in {"mp", "rating"}:
        params = {"mp_id": command.match_id, "page": command.page, "theme": "default"}
        if command.team_type is not None:
            params["team_type"] = command.team_type
        if name == "rating":
            params["algorithm"] = command.algorithm
        return Request("GET", "/multiplayer/history" if name == "mp" else "/multiplayer/rating", params)
    if name == "search":
        params = {"query": command.query, "page": command.page, "mode": {0: "osu", 1: "taiko", 2: "catch", 3: "mania"}.get(command.mode, "any")}
        if command.cursor:
            params["cursor_string"] = command.cursor
        return Request("GET", "/beatmap/search/image", params)
    if name == "preview":
        params = {"beatmap_id": command.beatmap_id, "format": command.format, "selection": "auto"}
        if command.mods and command.mods != "NM":
            params["mods"] = command.mods.split(',')
        return Request("GET", "/beatmap/preview/image", params, image_types=(command.format,))
    if name == "bpm":
        return Request("GET", "/beatmap/bpm", {"beatmap_id": command.beatmap_id})
    if name == "cover":
        return Request("GET", "/beatmap/cover", {"beatmap_id": command.beatmap_id}, image_types=("png", "jpeg", "webp"))
    if name == "beatmapset":
        return Request("GET", "/beatmap/beatmapset", {"beatmapset_id": command.beatmap_id, "theme": "default"})
    identity = {"platform": caller.platform, "platform_uid": command.target_uid or caller.uid}
    params = dict(identity)
    if command.mode is not None:
        params["game_mode"] = command.mode
    if name == "nb":
        params["days"] = command.days
        return Request("GET", "/score/new_best_plays", params)
    if name == "fix":
        return Request("GET", "/score/fix", params)
    if name == "analyze":
        params["theme"] = "default"
        return Request("GET", "/user_info/extra/performance_analyze", params)
    if name == "history":
        params.update(days=command.days, format="png")
        return Request("GET", "/user_info/history", params)
    if name == "score":
        params.update(beatmap_id=command.beatmap_id, theme=theme)
        return Request("GET", "/score/user_score", params)
    if name == "scorehistory":
        params.update(beatmap_id=command.beatmap_id, format="png", page=command.page)
        if command.mods is not None:
            params["mods"] = command.mods
        return Request("GET", "/score/history", params)
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
    try:
        error = json.loads(detail)
    except (ValueError, TypeError):
        error = {}
    if isinstance(error, dict):
        code = error.get("code")
        if code == "USER_NOT_BOUND":
            return "对方尚未绑定 osu! 账号。" if command.target_uid else "你尚未绑定 osu! 账号，请使用 /bind 用户名。"
        messages = {
            "OSU_USER_NOT_FOUND": "找不到这个 osu! 玩家，请检查用户名。",
            "BEATMAP_NOT_FOUND": "找不到这个谱面或谱面集，请检查 ID。",
            "LOCAL_SCORE_NOT_COLLECTED": "本地暂未收录该无榜谱面的成绩，未收录不代表没有游玩过。",
            "PREVIEW_UNAVAILABLE": "预览生成服务暂时不可用，请稍后重试。",
        }
        if code in messages:
            return messages[code]
        if code == "INVALID_ARGUMENT" and isinstance(error.get("message"), str):
            return error["message"][:500]
    if status == 403:
        return "MintAPI 鉴权或访问失败，请管理员检查接口密钥。"
    if status == 409 and command.name == "bind":
        return "你已经绑定过账号，请先使用 /unbind 解绑。"
    if status == 404:
        if command.name in {"mp", "rating"}:
            return "找不到这个比赛，请检查比赛 ID 或链接。"
        if "osu! user not found" in detail:
            return "找不到这个 osu! 玩家，请检查用户名。"
        if "User not found" in detail or "binding not found" in detail:
            return "对方尚未绑定 osu! 账号。" if command.target_uid else "你尚未绑定 osu! 账号，请使用 /bind 用户名。"
        if command.name == "nb":
            return "指定天数内没有新增 BP。"
        if command.name == "fix":
            return "没有 BP 或没有符合条件的可修复成绩。"
        if command.name == "history":
            return "没有可用的 PP 或排名历史。"
        if command.name == "scorehistory":
            return "该谱面在当前筛选条件或页码下没有成绩记录。"
        if command.name in {"pr", "recent", "bp", "score", "analyze"}:
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
