import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from test_plugin import arguments, service, identity, package, event_for, Plain, At, main, PNG, Image
features = importlib.import_module(package + '.player_features')
players = importlib.import_module(package + '.player_subscriptions')


class ParsingTests(unittest.TestCase):
    def test_weekly_comparison_and_watch_commands(self):
        command = arguments.parse_command('/weekly -w 2026-10-12:3', ['200'])
        request = service.build_request(command, identity.Identity('qq', '100'), 'yaowan')
        self.assertEqual(request.path, '/user_info/weekly')
        self.assertEqual(request.params, {'platform': 'qq', 'platform_uid': '200', 'game_mode': 3, 'week_start': '2026-10-12'})
        c = arguments.parse_command('/compare 657917 "Player One" peppy -m HD,HR -l lazer:2', [])
        self.assertEqual((c.usernames, c.mode, c.mods, c.legacy_only), (('Player One', 'peppy'), 2, 'HD,HR', False))
        self.assertEqual(arguments.parse_command('/bpwatch stop "Player One":3', []).action, 'stop')
        self.assertEqual(arguments.parse_command('/bpwatch list -p 2', []).page, 2)
        self.assertEqual(arguments.parse_command('/bpwatch:3', ['200']).target_uid, '200')
        self.assertEqual(arguments.parse_command('/bpwatch stopall', []).action, 'stopall')

    def test_invalid_arguments_do_not_reach_the_api(self):
        for text, mentions in [('/weekly -w 2026-10-13', []), ('/weekly -w 20261012', []), ('/weekly User', []),
                ('/compare 0 peppy', []), ('/compare 123', []), ('/compare 123 A B C', []),
                ('/compare 123 A -l wrong', []), ('/compare 123 A -m NM,HD', []), ('/compare 123 A', ['200']),
                ('/bpwatch list:0', []), ('/bpwatch list -p 0', []), ('/bpwatch stopall:0', []),
                ('/bpwatch A B', []), ('/bpwatch A', ['200']), ('/bpwatch:4', [])]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                arguments.parse_command(text, mentions)


class Client:
    def __init__(self):
        self.calls, self.events, self.subs, self.next_id = [], {}, {}, 1
        self.failure = None
    async def request(self, r):
        self.calls.append(r)
        if self.failure: raise self.failure
        if r.path == '/users/ranking':
            return {'users': [{'platformUid': x, 'osuUid': '42' if x == '100' else '43'} for x in r.body['platformUids']]}
        if r.path == '/score/compare' or r.path == '/user_info/weekly': return PNG
        if r.method == 'POST':
            uid = int(r.body['user']) if r.body['user'].isdigit() else 42
            key = (r.body['platform'], r.body['groupId'], uid, r.body['gameMode'])
            if key not in self.subs:
                self.subs[key] = {'id': f'{self.next_id:032x}', 'cursor': 1, 'userId': uid, 'gameMode': key[3],
                    'username': 'Player One', 'platform': key[0], 'groupId': key[1]}
                self.next_id += 1
            return dict(self.subs[key])
        if r.path.endswith('/updates'):
            sid = r.path.split('/')[-2]
            if sid not in {x['id'] for x in self.subs.values()}: raise players.MintAPIError(410)
            events = [x for x in self.events.get(sid, []) if x['cursor'] > r.params['after']]
            return {'cursor': max([r.params['after']] + [x['cursor'] for x in events]), 'updates': events}
        rows = [(k, x) for k, x in self.subs.items() if k[:2] == (r.params['platform'], r.params['group_id'])]
        if r.method == 'DELETE':
            rows = [(k,x) for k,x in rows if ('user_id' not in r.params or k[2] == r.params['user_id']) and ('game_mode' not in r.params or k[3] == r.params['game_mode'])]
            for k, _ in rows: del self.subs[k]
            return {'removed': len(rows)}
        return {'total': len(rows), 'items': [dict(x) for _,x in rows][(r.params['page']-1)*20:r.params['page']*20]}


class PlayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.client = Client(); self.sent = []; self.fail_send = False
        async def send(session, chain):
            if self.fail_send: return False
            self.sent.append((session, chain)); return True
        self.send = send
        self.path = Path(self.temp.name)/'players.sqlite'
        self.manager = players.PlayerSubscriptions(self.path, self.client, send)
        self.event = event_for([Plain('/bpwatch')]); self.event.message_obj.group_id = 'group-1'
        self.event.is_admin = lambda: True
    async def asyncTearDown(self):
        await self.manager.close(); self.temp.cleanup()
    async def command(self, text, mentions=None, event=None):
        return await self.manager.command(arguments.parse_command(text, mentions or []), event or self.event)
    def sid(self): return self.manager.db.execute('SELECT sid FROM players').fetchone()[0]
    def cursor(self): return self.manager.db.execute('SELECT cursor FROM players').fetchone()[0]

    async def test_compare_identity_resolution_and_direct_names(self):
        c = arguments.parse_command('/compare 123 -m HD,HR -l stable:3', ['200'])
        await features.compare_scores(self.client, c, identity.Identity('qq','100'))
        self.assertEqual(self.client.calls[-1].params, {'left_user':'42','right_user':'43','beatmap_id':123,'game_mode':3,'mods':'HD,HR','legacy_only':True})
        self.client.calls.clear()
        await features.compare_scores(self.client, arguments.parse_command('/compare 123 "Player One" peppy', []), identity.Identity('qq','100'))
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0].params['left_user'], 'Player One')

    async def test_group_subscription_checkpoint_restart_and_failed_delivery_retry(self):
        await self.command('/bpwatch')
        self.assertEqual(self.client.calls[-1].body, {'user':'42','platform':'qq','groupId':'group-1','gameMode':0})
        sid = self.sid(); self.client.events[sid] = [{'cursor':2,'text':'【新 BP】测试'}]
        self.fail_send = True; await self.manager.tick(); self.assertEqual(self.cursor(), 1)
        self.fail_send = False; await self.manager.tick(); self.assertEqual(self.cursor(), 2)
        self.assertEqual(self.sent[0][1].chain[0].text, '【新 BP】测试')
        await self.command('/bpwatch'); self.assertEqual(self.cursor(), 2)
        await self.manager.close(); self.manager = players.PlayerSubscriptions(self.path, self.client, self.send)
        await self.manager.tick(); self.assertEqual(len(self.sent), 1)
        self.client.events[sid].append({'cursor':3,'text':'排名突破'})
        await self.manager.tick(); self.assertEqual(self.cursor(),3); self.assertEqual(len(self.sent),2)

    async def test_list_stop_player_mode_stopall_and_cross_group_isolation(self):
        await self.command('/bpwatch "Player One":0'); await self.command('/bpwatch "Player One":3')
        other = event_for([Plain('/bpwatch')]); other.message_obj.group_id = 'group-2'; other.is_admin = lambda: True
        await self.command('/bpwatch "Player One":0', event=other)
        self.assertIn('共 2 条', await self.command('/bpwatch list'))
        self.assertIn('1 条', await self.command('/bpwatch stop "Player One":3'))
        self.assertEqual(len(self.client.subs),2)
        self.assertIn('1 条', await self.command('/bpwatch stopall'))
        self.assertEqual(len(self.client.subs),1)
        row = self.manager.db.execute('SELECT group_id FROM players').fetchone(); self.assertEqual(row[0], 'group-2')

    async def test_permissions_private_and_official_push_boundaries(self):
        self.event.is_admin = lambda: False; self.event.get_group = AsyncMock(return_value=None)
        await self.command('/bpwatch list')
        with self.assertRaises(ValueError): await self.command('/bpwatch peppy')
        with self.assertRaises(ValueError): await self.command('/bpwatch stopall')
        private = event_for([Plain('/bpwatch')], group=False)
        with self.assertRaises(ValueError): await self.command('/bpwatch', event=private)
        official = event_for([Plain('/bpwatch')], adapter='qq_official'); official.message_obj.group_id='g'; official.is_admin=lambda:True
        with self.assertRaises(ValueError): await self.command('/bpwatch', event=official)
        self.assertEqual(len(self.client.subs),0)

    async def test_lookup_failure_preserves_state_and_remote_cancellation_does_not_recreate(self):
        await self.command('/bpwatch peppy'); self.client.failure = TimeoutError()
        await self.manager.tick(); self.assertEqual(self.cursor(),1)
        self.client.failure = None; self.client.subs.clear()
        await self.manager.tick()
        self.assertIsNone(self.manager.db.execute('SELECT * FROM players').fetchone())
        self.assertIn('已取消', self.sent[0][1].chain[0].text)

    async def test_invalid_events_cannot_advance_or_partially_deliver_batch(self):
        await self.command('/bpwatch peppy'); sid=self.sid()
        self.client.events[sid]=[{'cursor':2,'text':'first'},{'cursor':2,'text':'duplicate cursor'}]
        await self.manager.tick(); self.assertEqual(self.cursor(),1); self.assertFalse(self.sent)
        self.client.events[sid]=[{'cursor':2,'text':'first'},{'cursor':3,'text':'second'}]
        original=self.send
        async def fail_second(session, chain):
            return False if chain.chain[0].text=='second' else await original(session,chain)
        self.manager.send=fail_second
        await self.manager.tick(); self.assertEqual(self.cursor(),2)
        self.manager.send=original; await self.manager.tick(); self.assertEqual(self.cursor(),3)
        self.assertEqual([x[1].chain[0].text for x in self.sent], ['first','second'])

    async def test_real_plugin_entrypoints_return_images_and_manage_group_subscriptions(self):
        plugin = main.MintOsuPlugin(type('Context',(),{'send_message':self.send})(), {})
        plugin._client=self.client; plugin._player_watch=self.manager
        for command in ['/weekly', '/compare 123 peppy']:
            event=event_for([Plain(command)])
            results=[r async for r in plugin.handle_command(event)]
            self.assertIsInstance(results[0].chain[0],Image); self.assertTrue(event.is_stopped())
        with patch.object(self.manager,'start'):
            results=[r async for r in plugin.handle_command(self.event)]
        self.assertIn('已订阅',results[0].chain[0].text)
        plugin._player_watch=None; plugin._client=None

    async def test_failed_cancellation_keeps_checkpoint_and_config_limit_is_enforced(self):
        self.manager.max_per_group=1
        await self.command('/bpwatch peppy')
        with self.assertRaises(ValueError): await self.command('/bpwatch 43')
        self.client.failure=TimeoutError()
        with self.assertRaises(TimeoutError): await self.command('/bpwatch stopall')
        self.assertEqual(self.cursor(),1)
        self.client.failure=None
        self.assertIn('1 条',await self.command('/bpwatch stopall'))
        self.assertIsNone(self.manager.db.execute('SELECT * FROM players').fetchone())

    async def test_missing_bindings_identify_the_correct_side(self):
        class Unbound:
            async def request(self,r):
                raise players.MintAPIError(404,'{"code":"USER_NOT_BOUND"}')
        for uid, expected in [('100','你尚未绑定'),('200','对方尚未绑定')]:
            with self.assertRaisesRegex(ValueError,expected):
                await features.bound_player(Unbound(), identity.Identity('qq','100'), uid)

    async def test_transport_routes_and_json_contract_through_real_http_client(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        client_module=importlib.import_module(package+'.mint_client')
        calls=[]
        async def handle(r):
            body=await r.json() if r.method=='POST' else None
            calls.append((r.method,r.path,dict(r.query),body))
            self.assertEqual(r.headers.get('access_token'),'test-only-token')
            if r.path=='/users/ranking':
                return web.json_response({'users':[{'platformUid':'100','osuUid':'42'}]})
            if r.path in {'/score/compare','/user_info/weekly'}:
                return web.Response(body=PNG,content_type='image/png')
            if r.method=='POST':
                return web.json_response({'id':'a'*32,'cursor':1,'userId':42,'gameMode':0})
            if r.method=='DELETE': return web.json_response({'removed':1})
            if r.path.endswith('/updates'):
                return web.json_response({'cursor':2,'updates':[{'cursor':2,'text':'【新 BP】真实 HTTP 测试'}]})
            return web.json_response({'total':1,'items':[{'id':'a'*32,'userId':42,'gameMode':0,'username':'peppy','platform':'qq','groupId':'group-1'}]})
        app=web.Application();app.router.add_route('*','/{tail:.*}',handle)
        async with TestServer(app) as server:
            client=client_module.MintClient(str(server.make_url('')).rstrip('/'),'test-only-token')
            try:
                self.manager.client=client
                data=await features.compare_scores(client,arguments.parse_command('/compare 657917 peppy',[]),identity.Identity('qq','100'))
                self.assertEqual(data,PNG)
                data=await client.request(service.build_request(arguments.parse_command('/weekly',[]),identity.Identity('qq','100'),'default'))
                self.assertEqual(data,PNG)
                await self.command('/bpwatch peppy');await self.command('/bpwatch list')
                await self.manager.tick();self.assertEqual(self.cursor(),2)
                self.assertIn('真实 HTTP',self.sent[-1][1].chain[0].text)
                await self.command('/bpwatch stopall')
                self.assertIn(('GET','/score/compare'),[(x[0],x[1]) for x in calls])
                body=next(x[3] for x in calls if x[0]=='POST' and x[1]=='/players/watch/subscriptions')
                self.assertEqual(body,{'user':'peppy','platform':'qq','groupId':'group-1','gameMode':0})
            finally:
                await client.close()
