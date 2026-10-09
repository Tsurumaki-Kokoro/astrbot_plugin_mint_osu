"""Batch avatar archives and current-group ranking orchestration."""
import io
import os
import re
import tempfile
import zipfile
from astrbot.api.message_components import File
from .service import Request, error_message
from .mint_client import MintAPIError


def save_attachment(event, data: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(prefix="mint-osu-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        event.track_temporary_local_file(path)
        return path
    except BaseException:
        os.unlink(path)
        raise


async def avatar_archive(client, command, event):
    output, failures, successes = io.BytesIO(), [], 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, username in enumerate(command.usernames, 1):
            try:
                image = await client.request(Request("GET", "/user_info/avatar_card", {"user": username}))
            except MintAPIError as exc:
                failures.append(f"{username}: {error_message(command, exc.status, exc.detail, exc.retry_after)}")
                continue
            safe = re.sub(r'[^\w.-]', '_', username)[:60].strip('.') or "player"
            archive.writestr(f"{index:02d}-{safe}.png", image)
            successes += 1
        if failures:
            archive.writestr("失败清单.txt", '\n'.join(failures).encode("utf-8"))
    if not successes:
        raise ValueError("所有用户名查询失败：\n" + '\n'.join(failures))
    path = save_attachment(event, output.getvalue(), ".zip")
    return File(name="osu-avatar-cards.zip", file=path)


async def group_ranking(client, command, caller, event):
    if event.is_private_chat() or not event.get_group_id():
        raise ValueError("排行榜只能在群聊中使用。")
    group = await event.get_group()
    if group is None or group.members is None:
        raise ValueError("当前平台无法提供群成员列表，暂不支持群排行榜。")
    ids = list(dict.fromkeys(str(member.user_id) for member in group.members if member.user_id))
    if group.member_count is not None and len(ids) < group.member_count:
        raise ValueError("平台返回的群成员列表不完整，无法生成准确排行榜。")
    bound = []
    for index in range(0, len(ids), 100):
        result = await client.request(Request("POST", "/users/bindings", {}, {"platform": caller.platform, "platformUids": ids[index:index+100]}, image=False))
        selected = result.get("platform_uids")
        if not isinstance(selected, list) or any(uid not in ids[index:index+100] for uid in selected):
            raise ValueError("绑定查询返回无效名单，请管理员检查服务。")
        bound.extend(selected)
    bound = list(dict.fromkeys(bound))
    if not bound:
        raise ValueError("当前群没有已绑定的 osu! 用户。")
    if len(bound) > 100:
        raise ValueError("当前群已绑定用户超过 100 人，超出排行榜接口上限；未截断名单。")
    path = "/users/ranking/top5" if command.name == "top5" else "/users/ranking"
    params = {"format": "png"}
    if command.name == "rank":
        params["game_mode"] = command.mode
    return await client.request(Request("POST", path, params, {"platform": caller.platform, "platformUids": bound}))
