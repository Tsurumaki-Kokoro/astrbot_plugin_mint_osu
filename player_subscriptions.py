"""Group player alerts with durable delivery cursors and server-side group management."""
import asyncio
import re
import sqlite3
from pathlib import Path
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.message_session import MessageSession
from .identity import resolve_identity
from .mint_client import MintAPIError
from .player_features import bound_player
from .service import Request
from .subscriptions import require_permission


class PlayerSubscriptions:
    def __init__(self, path, client, send, poll_interval=30, max_per_group=10):
        if type(poll_interval) is not int or not 10 <= poll_interval <= 3600:
            raise ValueError('玩家订阅检查间隔必须为 10～3600 秒。')
        if type(max_per_group) is not int or not 1 <= max_per_group <= 100:
            raise ValueError('每群玩家订阅上限必须为 1～100 条。')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS players (session TEXT, platform TEXT, group_id TEXT, user_id INTEGER, mode INTEGER, sid TEXT, cursor INTEGER, title TEXT, PRIMARY KEY(session,user_id,mode))')
        self.db.commit()
        self.client, self.send = client, send
        self.poll_interval, self.max_per_group = poll_interval, max_per_group
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
                logger.warning(f'Mint player polling deferred: {type(exc).__name__}')
            await asyncio.sleep(self.poll_interval)

    @staticmethod
    def group(event):
        if event.is_private_chat() or not event.get_group_id():
            raise ValueError('玩家动态订阅只能在群聊中管理。')
        caller = resolve_identity(event.get_platform_name(), event.get_platform_id(), event.get_sender_id())
        if ':' in caller.platform:
            raise ValueError('当前适配器不支持群玩家订阅。QQ 官方适配器不支持主动群推送，QQ OneBot 可使用。')
        group_id = str(event.get_group_id())
        if len(group_id) > 80 or any(x.isspace() or ord(x) < 32 for x in group_id):
            raise ValueError('平台提供的群 ID 不符合 MintAPI 要求。')
        session = str(MessageSession(event.get_platform_id(), event.session.message_type, group_id))
        return caller, group_id, session

    async def page(self, platform, group_id, page=1):
        result = await self.client.request(Request('GET', '/players/watch/subscriptions',
            {'platform': platform, 'group_id': group_id, 'page': page, 'page_size': 20}, image=False, json_limit=1024 * 1024))
        items = result.get('items')
        if (not isinstance(items, list) or type(result.get('total')) is not int or result['total'] < 0
                or any(not isinstance(x, dict) or x.get('platform') != platform or str(x.get('groupId')) != group_id
                    or type(x.get('userId')) is not int or x['userId'] <= 0 or type(x.get('gameMode')) is not int
                    or x['gameMode'] not in range(4) for x in items)):
            raise ValueError('群订阅查询返回无效数据，请更新 MintAPI。')
        return result

    async def target(self, command, caller):
        return command.username or await bound_player(self.client, caller, command.target_uid or caller.uid, command.mode or 0)

    async def command(self, command, event):
        caller, group_id, session = self.group(event)
        if command.action != 'list':
            try:
                await require_permission(event)
            except ValueError:
                raise ValueError('只有群管理员或机器人管理员可以修改玩家订阅。')
        async with self.lock:
            if command.action == 'list':
                data = await self.page(caller.platform, group_id, command.page)
                if not data['items']:
                    return '当前群没有玩家动态订阅。' if data['total'] == 0 else '这一页没有订阅，请调整页码。'
                return f"当前群玩家订阅 · 第 {command.page}/{max(1, (data['total'] + 19) // 20)} 页 · 共 {data['total']} 条：\n" + '\n'.join(
                    f"{str(x.get('username') or x['userId']).replace(chr(10), ' ').replace(chr(13), ' ')[:64]}（{x['userId']}）· 模式 {x['gameMode']}" for x in data['items'])
            if command.action in {'stop', 'stopall'}:
                params = {'platform': caller.platform, 'group_id': group_id}
                if command.action == 'stop':
                    target = await self.target(command, caller)
                    if not target.isascii() or not target.isdigit():
                        found, page = set(), 1
                        while True:
                            data = await self.page(caller.platform, group_id, page)
                            found.update(x['userId'] for x in data['items'] if str(x.get('username', '')).casefold() == target.casefold())
                            if page * 20 >= data['total']:
                                break
                            if not data['items'] or page >= 500:
                                raise ValueError('群订阅列表不完整，未执行取消；请使用 osu! ID。')
                            page += 1
                        if not found:
                            return '当前群没有匹配的玩家订阅。'
                        if len(found) != 1:
                            raise ValueError('用户名匹配多个 ID，请使用 osu! 数字 ID。')
                        target = str(found.pop())
                    params['user_id'] = int(target)
                    if command.mode is not None:
                        params['game_mode'] = command.mode
                result = await self.client.request(Request('DELETE', '/players/watch/subscriptions', params, image=False))
                if type(result.get('removed')) is not int or result['removed'] < 0:
                    raise ValueError('取消接口返回无效结果，已保留本地投递记录。')
                sql, args = 'DELETE FROM players WHERE platform=? AND group_id=?', [caller.platform, group_id]
                if 'user_id' in params:
                    sql += ' AND user_id=?'; args.append(params['user_id'])
                if 'game_mode' in params:
                    sql += ' AND mode=?'; args.append(params['game_mode'])
                self.db.execute(sql, args); self.db.commit()
                return f"已取消当前群 {result['removed']} 条玩家订阅。"
            target = await self.target(command, caller)
            mode = command.mode or 0
            rows = self.db.execute('SELECT user_id,mode,title FROM players WHERE session=?', (session,)).fetchall()
            if len(rows) >= self.max_per_group and not any(m == mode and (str(uid) == target or title.casefold() == target.casefold()) for uid, m, title in rows):
                raise ValueError(f'每群最多订阅 {self.max_per_group} 条玩家动态，请先取消已有订阅。')
            result = await self.client.request(Request('POST', '/players/watch/subscriptions', {},
                {'user': target, 'platform': caller.platform, 'groupId': group_id, 'gameMode': mode}, image=False))
            sid, cursor, uid = result.get('id'), result.get('cursor'), result.get('userId')
            if (not isinstance(sid, str) or not re.fullmatch(r'[a-fA-F0-9]{32}', sid)
                    or type(cursor) is not int or not 0 <= cursor <= 9223372036854775807 or type(uid) is not int or not 1 <= uid <= 2147483647
                    or type(result.get('gameMode')) is not int or result['gameMode'] != mode):
                raise ValueError('玩家订阅接口返回无效数据。')
            existing = self.db.execute('SELECT sid,cursor FROM players WHERE session=? AND user_id=? AND mode=?', (session, uid, mode)).fetchone()
            if existing and existing[0] == sid:
                cursor = existing[1]  # Renewal must not rewind delivery progress to startCursor.
            self.db.execute('INSERT OR REPLACE INTO players VALUES (?,?,?,?,?,?,?,?)',
                (session, caller.platform, group_id, uid, mode, sid, cursor, target))
            self.db.commit()
            return f'已订阅 {target}（osu! {uid}）· 模式 {mode} 的新 BP 和里程碑提醒。仅通知后续变化，MintAPI 默认约五分钟采集一次。'

    async def tick(self):
        async with self.lock:
            rows = self.db.execute('SELECT session,platform,group_id,user_id,mode,sid,cursor,title FROM players').fetchall()
            for session, platform, group_id, uid, mode, sid, cursor, title in rows:
                try:
                    data = await self.client.request(Request('GET', f'/players/watch/subscriptions/{sid}/updates', {'after': cursor}, image=False, json_limit=1024 * 1024))
                    updates, end = data.get('updates'), data.get('cursor')
                    if not isinstance(updates, list) or type(end) is not int or not cursor <= end <= 9223372036854775807 or len(updates) > 100:
                        raise ValueError('Invalid player updates')
                    previous = cursor
                    for item in updates:
                        if (not isinstance(item, dict) or type(item.get('cursor')) is not int
                                or not previous < item['cursor'] <= end or not isinstance(item.get('text'), str)
                                or not item['text'].strip() or len(item['text']) > 50000):
                            raise ValueError('Invalid player update event')
                        previous = item['cursor']
                    for item in updates:
                        await self.deliver(session, item['text'])
                        self.checkpoint(session, uid, mode, item['cursor'])
                    self.checkpoint(session, uid, mode, end)
                except MintAPIError as exc:
                    if exc.status == 410:
                        try:
                            await self.deliver(session, f'{title}（osu! {uid}）· 模式 {mode} 的订阅已取消、过期或游标失效，已停止推送。管理员可先 /bpwatch stop {uid}:{mode}，再重新订阅。')
                            self.db.execute('DELETE FROM players WHERE session=? AND user_id=? AND mode=?', (session, uid, mode)); self.db.commit()
                        except asyncio.CancelledError:
                            raise
                        except Exception as failure:
                            logger.warning(f'Mint player expiry notification deferred: {type(failure).__name__}')
                    else:
                        logger.warning(f'Mint player updates deferred: HTTP {exc.status}')
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(f'Mint player delivery deferred: {type(exc).__name__}')

    def checkpoint(self, session, uid, mode, cursor):
        self.db.execute('UPDATE players SET cursor=? WHERE session=? AND user_id=? AND mode=?', (cursor, session, uid, mode))
        self.db.commit()

    async def deliver(self, session, text):
        # Bound platform message size while retaining progress only after every part succeeds.
        for start in range(0, len(text), 1800):
            result = await asyncio.wait_for(self.send(session, MessageChain(chain=[Plain(text[start:start+1800])])), timeout=60)
            if result is not True:
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
