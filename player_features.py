"""Player identity resolution and same-map comparisons."""
import json
from .service import Request
from .mint_client import MintAPIError


async def bound_player(client, caller, uid, mode=0):
    try:
        value = await client.request(Request('POST', '/users/ranking', {'format': 'json', 'game_mode': mode},
            {'platform': caller.platform, 'platformUids': [str(uid)]}, image=False))
    except MintAPIError as exc:
        try:
            error = json.loads(exc.detail)
        except (ValueError, TypeError):
            error = {}
        if isinstance(error, dict) and error.get('code') == 'USER_NOT_BOUND':
            raise ValueError('你尚未绑定 osu! 账号，请使用 /bind 用户名。' if str(uid) == caller.uid else '对方尚未绑定 osu! 账号。') from exc
        raise
    users = value.get('users')
    if not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict) or str(users[0].get('platformUid')) != str(uid):
        raise ValueError('绑定查询返回无效玩家信息，请更新 MintAPI。')
    user = users[0]
    osu_id = str(user.get('osuUid', ''))
    if not osu_id.isascii() or not osu_id.isdigit() or not 1 <= int(osu_id) <= 2147483647:
        raise ValueError('绑定查询返回无效 osu! ID。')
    return osu_id


async def compare_scores(client, command, caller):
    if len(command.usernames) == 2:
        left, right = command.usernames
    else:
        left = await bound_player(client, caller, caller.uid, command.mode or 0)
        right = await bound_player(client, caller, command.target_uid, command.mode or 0) if command.target_uid else command.usernames[0]
    params = {'left_user': left, 'right_user': right, 'beatmap_id': command.beatmap_id, 'game_mode': command.mode or 0}
    if command.mods is not None:
        params['mods'] = command.mods
    if command.legacy_only is not None:
        params['legacy_only'] = command.legacy_only
    return await client.request(Request('GET', '/score/compare', params))
