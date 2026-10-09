from test_plugin import arguments, identity, service, package, client_module, event_for, PNG, Plain, MessageMember
import importlib
import unittest
import os
from types import SimpleNamespace
import io
import zipfile
extras = importlib.import_module(package + '.extras')

class ExtrasTests(unittest.IsolatedAsyncioTestCase):
    async def test_avatar_archive_partial_failure_and_filename_safety(self):
        calls = []
        class Client:
            async def request(self, request):
                calls.append(request)
                if request.params['user'] == 'missing':
                    raise client_module.MintAPIError(404, {'code': 'OSU_USER_NOT_FOUND'})
                return PNG
        event = event_for([Plain('/oa')])
        command = arguments.parse_command('/oa "../Player One" missing', [])
        attachment = await extras.avatar_archive(Client(), command, event)
        try:
            with zipfile.ZipFile(attachment.file) as archive:
                self.assertEqual(archive.namelist(), ['01-_Player_One.png', '失败清单.txt'])
                self.assertEqual(archive.read(archive.namelist()[0]), PNG)
            self.assertEqual(calls[0].params, {'user': '../Player One'})
        finally:
            os.unlink(attachment.file)

    async def test_group_discovers_bindings_in_batches_before_ranking(self):
        calls = []
        class Client:
            async def request(self, request):
                calls.append(request)
                if request.path == '/users/bindings':
                    return {'platform_uids': [request.body['platformUids'][0]]}
                return PNG
        event = event_for([Plain('/rank:3')])
        event.message_obj.group_id = 'g'
        async def group():
            return SimpleNamespace(members=[MessageMember(str(i), str(i)) for i in range(1, 202)], member_count=201)
        event.get_group = group
        result = await extras.group_ranking(Client(), arguments.parse_command('/rank:3', []), identity.resolve_identity('aiocqhttp', 'adapter-1', '100'), event)
        self.assertEqual(result, PNG)
        self.assertEqual([len(x.body['platformUids']) for x in calls[:3]], [100,100,1])
        self.assertEqual(calls[-1].body['platformUids'], ['1','101','201'])
        self.assertEqual(calls[-1].params['game_mode'], 3)

    async def test_group_incomplete_and_private_fail_before_query(self):
        event = event_for([Plain('/top5')])
        event.message_obj.group_id = 'g'
        async def group():
            return SimpleNamespace(members=[], member_count=2)
        event.get_group = group
        with self.assertRaisesRegex(ValueError, '不完整'):
            await extras.group_ranking(None, arguments.parse_command('/top5', []), None, event)
        event = event_for([Plain('/top5')], group=False)
        with self.assertRaisesRegex(ValueError, '群聊'):
            await extras.group_ranking(None, arguments.parse_command('/top5', []), None, event)

class NewCommandTests(unittest.TestCase):
    def test_oa_default_mention_and_list(self):
        caller = identity.resolve_identity('aiocqhttp', 'adapter-1', '100')
        self.assertEqual(service.build_request(arguments.parse_command('/oa', []), caller, 'default').params['platform_uid'], '100')
        self.assertEqual(service.build_request(arguments.parse_command('/oa', ['200']), caller, 'default').params['platform_uid'], '200')
        self.assertEqual(arguments.parse_command('/oa peppy "Player One"', []).usernames, ('peppy','Player One'))
        for text, mentions in [('/oa', ['1','2']), ('/oa peppy', ['1'])]:
            with self.assertRaises(ValueError): arguments.parse_command(text, mentions)

    def test_pp_video_and_rank_validation(self):
        caller = identity.resolve_identity('aiocqhttp', 'adapter-1', '100')
        request = service.build_request(arguments.parse_command('/pp 100', ['200']), caller, 'default')
        self.assertEqual(request.params['pp'], 100)
        self.assertFalse(request.image)
        request = service.build_request(arguments.parse_command('/previewvideo 123 --mods HD,DT --start 12 --duration 20', []), caller, 'default')
        self.assertTrue(request.video)
        self.assertEqual(request.params['duration'], 20)
        self.assertEqual(arguments.parse_command('/rank', []).mode, 0)
        for text in ['/pp nan','/pp 0','/previewvideo 123 --duration 61','/rank peppy','/top5:3']:
            with self.assertRaises(ValueError): arguments.parse_command(text, [])
