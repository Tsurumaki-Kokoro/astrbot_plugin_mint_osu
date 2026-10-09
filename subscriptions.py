"""Persistent per-session subscriptions, shared polling and delivery checkpoints."""
import asyncio
import json
from itertools import groupby
import sqlite3
import uuid
from pathlib import Path
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain, Image
from .service import Request
from .mint_client import MintAPIError
from astrbot.core.platform.message_session import MessageSession


def validate_state(value, match_id):
    snapshot = value.get('snapshot') if isinstance(value, dict) else None
    if (not isinstance(snapshot, dict) or snapshot.get('matchId') != match_id
            or not isinstance(snapshot.get('name'), str) or snapshot.get('status') not in {'waiting', 'playing', 'closed'}
            or not isinstance(snapshot.get('games'), list) or type(value.get('cursor')) is not int or value['cursor'] < 0):
        raise ValueError('比赛订阅接口返回无效数据，请更新 MintAPI。')
    ids, games = set(), []
    for game in snapshot['games']:
        if (not isinstance(game, dict) or type(game.get('gameId')) is not int
                or game['gameId'] <= 0 or not isinstance(game.get('ready'), bool)
                or game['gameId'] in ids):
            raise ValueError('比赛订阅接口返回无效单局数据。')
        ids.add(game['gameId'])
        games.append({'game_id': game['gameId'], 'ready': game['ready']})
    return {'match_id': match_id, 'name': snapshot['name'], 'closed': snapshot['status'] == 'closed',
            'games': games, 'cursor': value['cursor']}


async def require_permission(event):
    if event.is_private_chat() or event.is_admin():
        return
    group = await event.get_group()
    uid = str(event.get_sender_id())
    if group is not None and (uid == str(group.group_owner) or uid in {str(x) for x in group.group_admins or []}):
        return
    raise ValueError('只有群管理员或机器人管理员可以修改比赛订阅。')


class Subscriptions:
    def __init__(self, path, client, send):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS subscriptions (session TEXT, match_id INTEGER, title TEXT, seen TEXT, PRIMARY KEY(session,match_id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS remotes (match_id INTEGER PRIMARY KEY, subscription_id TEXT, cursor INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
        self.db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('instance', uuid.uuid4().hex))
        self.instance = self.db.execute('SELECT value FROM metadata WHERE key=?', ('instance',)).fetchone()[0]
        self.db.commit()
        self.client, self.send = client, send
        self.lock = asyncio.Lock()
        self.task = None

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run())

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f'Mint subscription polling failed: {type(exc).__name__}')
            await asyncio.sleep(30)

    async def state(self, match_id):
        remote = self.db.execute('SELECT subscription_id,cursor FROM remotes WHERE match_id=?', (match_id,)).fetchone()
        if remote:
            try:
                result = await self.client.request(Request('GET', f'/multiplayer/live/subscriptions/{remote[0]}/updates', {'after': remote[1]}, image=False, json_limit=8 * 1024 * 1024))
            except MintAPIError as exc:
                if exc.status != 410:
                    raise
                remote = None
        if not remote:
            result = await self.client.request(Request('POST', '/multiplayer/live/subscriptions', {},
                {'matchId': match_id, 'scope': f'mint:{self.instance}:{match_id}'}, image=False, json_limit=8 * 1024 * 1024))
            sid = result.get('subscriptionId')
            if not isinstance(sid, str) or not sid.isalnum() or len(sid) > 128:
                raise ValueError('比赛订阅接口返回无效订阅 ID。')
        else:
            sid = remote[0]
        state = validate_state(result, match_id)
        self.db.execute('INSERT OR REPLACE INTO remotes VALUES (?,?,?)', (match_id, sid, state['cursor']))
        self.db.commit()
        return state

    async def cleanup_remotes(self):
        orphans = self.db.execute('SELECT match_id,subscription_id FROM remotes WHERE match_id NOT IN (SELECT match_id FROM subscriptions)').fetchall()
        for mid, sid in orphans:
            try:
                await self.client.request(Request('DELETE', f'/multiplayer/live/subscriptions/{sid}', {}, image=False))
            except MintAPIError as exc:
                if exc.status != 410:
                    continue
            except Exception as exc:
                logger.warning(f'Mint remote subscription cleanup deferred: {type(exc).__name__}')
                continue
            self.db.execute('DELETE FROM remotes WHERE match_id=?', (mid,))
            self.db.commit()

    async def command(self, command, event):
        if event.is_private_chat():
            session = event.unified_msg_origin
        else:
            if not event.get_group_id():
                raise ValueError('当前平台未提供群会话 ID，无法管理比赛订阅。')
            session = str(MessageSession(event.get_platform_id(), event.session.message_type, str(event.get_group_id())))
        if command.action != 'list':
            await require_permission(event)
        async with self.lock:
            rows = self.db.execute('SELECT match_id,title FROM subscriptions WHERE session=? ORDER BY match_id', (session,)).fetchall()
            if command.action == 'list':
                return '当前会话没有比赛订阅。' if not rows else '当前会话的比赛订阅：\n' + '\n'.join(f'{mid} · {title}' for mid, title in rows)
            if command.action in {'stop', 'stopall'}:
                if command.action == 'stopall':
                    self.db.execute('DELETE FROM subscriptions WHERE session=?', (session,))
                else:
                    self.db.execute('DELETE FROM subscriptions WHERE session=? AND match_id=?', (session, command.match_id))
                count = self.db.execute('SELECT changes()').fetchone()[0]
                self.db.commit()
                if self.client is not None:
                    await self.cleanup_remotes()
                return f'已停止 {count} 个比赛订阅。' if count else '没有匹配的比赛订阅。'
            if event.get_platform_name().lower() == 'qq_official':
                raise ValueError('当前 AstrBot QQ 官方适配器不支持会话主动推送，暂不支持比赛订阅。QQ OneBot 可使用此功能。')
            if any(mid == command.match_id for mid, _ in rows):
                return '当前会话已经订阅这场比赛。'
            if len(rows) >= 3:
                raise ValueError('每个会话最多订阅 3 场比赛，请先停止已有订阅。')
            state = await self.state(command.match_id)
            if state['closed']:
                await self.cleanup_remotes()
                raise ValueError('这场比赛已经结束，无需订阅；使用 /mp 或 /rating 查询。')
            seen = [game['game_id'] for game in state['games']]
            self.db.execute('INSERT INTO subscriptions VALUES (?,?,?,?)', (session, command.match_id, state['name'], json.dumps(seen)))
            self.db.commit()
            return f"已订阅 {state['name']}（{command.match_id}），比赛进行中。每 30 秒检查，仅通知后续单局成绩和比赛结束。"

    async def tick(self):
        async with self.lock:
            await self.cleanup_remotes()
            rows = self.db.execute('SELECT session,match_id,title,seen FROM subscriptions ORDER BY match_id,session').fetchall()
            for mid, group in groupby(rows, key=lambda row: row[1]):
                targets = {row[0]: set(json.loads(row[3])) for row in group}
                blocked = set()
                try:
                    state = await self.state(mid)
                except Exception as exc:
                    logger.warning(f'Mint subscription {mid} retained after lookup failure: {type(exc).__name__}')
                    continue
                for game in state['games']:
                    gid = game['game_id']
                    pending = [session for session, seen in targets.items() if session not in blocked and gid not in seen and game['ready']]
                    if not pending:
                        continue
                    try:
                        # One image at a time, shared across every eligible destination.
                        image = await self.client.request(Request('GET', f'/multiplayer/live/{mid}/games/{gid}/image', {}))
                    except Exception as exc:
                        blocked.update(pending)
                        logger.warning(f'Mint subscription {mid} retained after image failure: {type(exc).__name__}')
                        continue
                    for session in pending:
                        try:
                            await self.deliver(session, [Plain(f"{state['name']}（{mid}）· 单局 {gid} 已结束"), Image.fromBytes(image)])
                            targets[session].add(gid)
                            self.db.execute('UPDATE subscriptions SET title=?,seen=? WHERE session=? AND match_id=?',
                                (state['name'], json.dumps(sorted(targets[session])), session, mid))
                            self.db.commit()
                        except Exception as exc:
                            blocked.add(session)
                            logger.warning(f'Mint subscription {mid} retained after delivery failure: {type(exc).__name__}')
                    del image
                if state['closed']:
                    for session in targets:
                        if session in blocked:
                            continue
                        try:
                            await self.deliver(session, [Plain(f"比赛 {state['name']}（{mid}）已结束，订阅已停止。使用 /rating {mid} 查看评分。")])
                            self.db.execute('DELETE FROM subscriptions WHERE session=? AND match_id=?', (session, mid))
                            self.db.commit()
                        except Exception as exc:
                            logger.warning(f'Mint subscription {mid} closure deferred: {type(exc).__name__}')
            await self.cleanup_remotes()

    async def deliver(self, session, components):
        if await asyncio.wait_for(self.send(session, MessageChain(chain=components)), timeout=60) is not True:
            raise RuntimeError('Platform unavailable')

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        self.db.close()
