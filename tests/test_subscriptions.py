import importlib
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from test_plugin import arguments, package, event_for, PNG, Plain
watch = importlib.import_module(package + '.subscriptions')

class Client:
    def __init__(self):
        self.states = {i: {'match_id': i, 'name': f'Match {i}', 'closed': False, 'games': [{'game_id': 10, 'ready': True}]} for i in range(1, 5)}
        self.calls = []
        self.fail = False
    async def request(self, request):
        self.calls.append(request)
        if self.fail: raise TimeoutError()
        if request.method == 'DELETE': return {}
        if request.path.endswith('/image'): return PNG
        mid = request.body['matchId'] if request.method == 'POST' else int(request.path.split('/')[-2][3:])
        state = self.states[mid]
        return {'subscriptionId': f'sub{mid}', 'cursor': len(state['games']), 'snapshot': {
            'matchId': mid, 'name': state['name'], 'status': 'closed' if state['closed'] else 'waiting',
            'games': [{'gameId': g['game_id'], 'ready': g['ready']} for g in state['games']]}}

class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = Client()
        self.sent = []
        self.fail_send = False
        async def send(session, chain):
            if self.fail_send: return False
            self.sent.append((session, chain))
            return True
        self.send = send
        self.manager = watch.Subscriptions(Path(self.temp.name) / 'state.sqlite', self.client, send)
        self.event = event_for([Plain('/mpwatch 1')], group=False)
    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()
    async def command(self, text, event=None):
        return await self.manager.command(arguments.parse_command(text, []), event or self.event)

    async def test_baseline_shared_polling_and_normal_deduplication(self):
        await self.command('/mpwatch 1')
        second = event_for([Plain('/mpwatch 1')], group=False)
        second.unified_msg_origin = 'adapter-1:FriendMessage:second'
        await self.command('/mpwatch 1', second)
        self.client.calls.clear()
        self.client.states[1]['games'].append({'game_id': 11, 'ready': True})
        await self.manager.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(self.client.calls), 2)  # One snapshot and one image shared by both sessions.
        await self.manager.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertIn('单局 11', self.sent[0][1].chain[0].text)

    async def test_restart_failure_recovery_and_closure_order(self):
        await self.command('/mpwatch 1')
        await self.manager.close()
        self.manager = watch.Subscriptions(Path(self.temp.name) / 'state.sqlite', self.client, self.send)
        self.client.states[1]['games'] += [{'game_id': 11, 'ready': True}, {'game_id': 12, 'ready': True}]
        self.client.states[1]['closed'] = True
        self.client.fail = True
        await self.manager.tick()
        self.assertEqual(len(self.sent), 0)
        self.assertIn('Match 1', await self.command('/mpwatch list'))
        self.client.fail = False
        await self.manager.tick()
        self.assertEqual(len(self.sent), 3)
        self.assertIn('单局 11', self.sent[0][1].chain[0].text)
        self.assertIn('单局 12', self.sent[1][1].chain[0].text)
        self.assertIn('已结束', self.sent[2][1].chain[0].text)
        self.assertIn('没有', await self.command('/mpwatch list'))

    async def test_send_failure_does_not_advance_checkpoint(self):
        await self.command('/mpwatch 1')
        self.client.states[1]['games'].append({'game_id': 11, 'ready': True})
        self.fail_send = True
        await self.manager.tick()
        self.fail_send = False
        await self.manager.tick()
        await self.manager.tick()
        self.assertEqual(len(self.sent), 1)

    async def test_delayed_scores_and_old_games_remain_baseline(self):
        self.client.states[1]['games'][0]['ready'] = False
        await self.command('/mpwatch 1')
        self.client.states[1]['games'][0]['ready'] = True
        self.client.states[1]['games'].append({'game_id': 11, 'ready': False})
        await self.manager.tick()
        self.assertEqual(len(self.sent), 0)
        self.client.states[1]['closed'] = True
        self.client.states[1]['games'][1]['ready'] = True
        await self.manager.tick()
        self.assertEqual(len(self.sent), 2)

    async def test_cap_duplicate_closed_and_stops(self):
        await self.command('/mpwatch 1')
        self.assertIn('已经订阅', await self.command('/mpwatch 1'))
        await self.command('/mpwatch 2')
        await self.command('/mpwatch 3')
        with self.assertRaisesRegex(ValueError, '最多'): await self.command('/mpwatch 4')
        self.assertIn('1 个', await self.command('/mpwatch stop https://osu.ppy.sh/mp/1'))
        self.assertIn('2 个', await self.command('/mpwatch stopall'))
        self.client.states[4]['closed'] = True
        with self.assertRaisesRegex(ValueError, '已经结束'): await self.command('/mpwatch 4')

    async def test_permissions_and_session_isolation(self):
        group_event = event_for([Plain('/mpwatch 1')])
        group_event.message_obj.group_id = 'g'
        async def group(): return SimpleNamespace(group_owner='200', group_admins=['300'])
        group_event.get_group = group
        with self.assertRaisesRegex(ValueError, '管理员'): await self.command('/mpwatch 1', group_event)
        self.assertEqual(len(self.client.calls), 0)
        group_event.role = 'admin'
        await self.command('/mpwatch 1', group_event)
        self.assertIn('没有', await self.command('/mpwatch list'))
        group_event.role = 'member'
        async def own_group(): return SimpleNamespace(group_owner='100', group_admins=[])
        group_event.get_group = own_group
        self.assertIn('1 个', await self.command('/mpwatch stopall', group_event))

    async def test_group_session_is_shared_across_members_and_isolated_across_bots(self):
        first = event_for([Plain('/mpwatch 1')])
        first.message_obj.group_id = 'g'
        first.role = 'admin'
        first.unified_msg_origin = 'adapter-1:GroupMessage:100_g'
        await self.command('/mpwatch 1', first)
        second = event_for([Plain('/mpwatch list')])
        second.message_obj.group_id = 'g'
        second.unified_msg_origin = 'adapter-1:GroupMessage:200_g'
        self.assertIn('Match 1', await self.command('/mpwatch list', second))
        second.platform_meta.id = 'adapter-2'
        self.assertIn('没有', await self.command('/mpwatch list', second))

    async def test_remote_cleanup_retries_after_local_stop(self):
        await self.command('/mpwatch 1')
        original = self.client.request
        async def request(req):
            if req.method == 'DELETE': raise TimeoutError()
            return await original(req)
        self.client.request = request
        self.assertIn('1 个', await self.command('/mpwatch stopall'))
        self.assertEqual(self.manager.db.execute('SELECT COUNT(*) FROM remotes').fetchone()[0], 1)
        self.client.request = original
        await self.manager.tick()
        self.assertEqual(self.manager.db.execute('SELECT COUNT(*) FROM remotes').fetchone()[0], 0)

    async def test_partial_delivery_failure_retries_only_unsent_rounds(self):
        await self.command('/mpwatch 1')
        self.client.states[1]['games'] += [{'game_id': 11, 'ready': True}, {'game_id': 12, 'ready': True}]
        send = self.send
        async def fail_second(session, chain):
            if '单局 12' in chain.chain[0].text: return False
            return await send(session, chain)
        self.manager.send = fail_second
        await self.manager.tick()
        self.assertEqual(len(self.sent), 1)
        self.manager.send = send
        await self.manager.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertIn('单局 12', self.sent[-1][1].chain[0].text)

    async def test_plugin_entry_point_starts_and_stops_subscription_task(self):
        from test_plugin import main
        plugin = main.MintOsuPlugin(SimpleNamespace(send_message=self.send), {})
        plugin._client = self.client
        plugin._watch = self.manager
        results = [r async for r in plugin.handle_command(self.event)]
        self.assertIn('已订阅', results[0].chain[0].text)
        self.assertIsNotNone(self.manager.task)
        event = event_for([Plain('/mpwatch stopall')], group=False)
        results = [r async for r in plugin.handle_command(event)]
        self.assertIn('已停止', results[0].chain[0].text)
        plugin._client = None  # Fake HTTP client has no close hook.
        await plugin.terminate()
        self.assertIsNone(plugin._watch)
        self.manager = watch.Subscriptions(Path(self.temp.name) / 'state.sqlite', self.client, self.send)

    async def test_official_qq_and_malformed_state_are_rejected(self):
        official = event_for([Plain('/mpwatch 1')], adapter='qq_official', group=False)
        with self.assertRaisesRegex(ValueError, '不支持'): await self.command('/mpwatch 1', official)
        self.client.states[1]['games'] = [{'game_id': 0, 'ready': True}]
        with self.assertRaises(ValueError): await self.command('/mpwatch 1')
        self.assertIn('没有', await self.command('/mpwatch list'))

    async def test_expired_remote_rebuilds_without_losing_missed_games(self):
        await self.command('/mpwatch 1')
        self.client.states[1]['games'].append({'game_id': 11, 'ready': True})
        original = self.client.request
        from test_plugin import client_module
        once = True
        async def request(req):
            nonlocal once
            if req.path.endswith('/updates') and once:
                once = False
                raise client_module.MintAPIError(410, 'expired')
            return await original(req)
        self.client.request = request
        await self.manager.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(sum(r.method == 'POST' for r in self.client.calls), 2)

    async def test_background_task_cancels_cleanly(self):
        self.manager.start()
        task = self.manager.task
        await asyncio.sleep(0)
        await self.manager.close()
        self.assertTrue(task.cancelled())
        # Replace the closed instance for teardown.
        self.manager = watch.Subscriptions(Path(self.temp.name) / 'state.sqlite', self.client, self.send)

class WatchParsingTests(unittest.TestCase):
    def test_watch_commands_and_rejected_options(self):
        self.assertEqual(arguments.parse_command('/mpwatch https://osu.ppy.sh/community/matches/123', []).match_id, 123)
        for action in ['list', 'stopall']:
            self.assertEqual(arguments.parse_command('/mpwatch ' + action, []).action, action)
        self.assertEqual(arguments.parse_command('/mpwatch stop 123', []).action, 'stop')
        for text in ['/mpwatch','/mpwatch stop','/mpwatch 123 -p 2','/mpwatch list 1','/mpwatch 0','/mpwatch https://evil.test/mp/1']:
            with self.assertRaises(ValueError): arguments.parse_command(text, [])
