import importlib
import atexit
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

_runtime = tempfile.TemporaryDirectory(prefix="mint-astrbot-tests-")
atexit.register(_runtime.cleanup)
os.environ["ASTRBOT_ROOT"] = _runtime.name

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
package = "data.plugins.astrbot_plugin_mint_osu"
arguments = importlib.import_module(package + ".arguments")
identity = importlib.import_module(package + ".identity")
service = importlib.import_module(package + ".service")
main = importlib.import_module(package + ".main")
client_module = importlib.import_module(package + ".mint_client")

from aiohttp import web
from aiohttp.test_utils import TestServer
from astrbot.api.message_components import Plain, At, AtAll, Image
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.star.star import star_map

PNG = b"\x89PNG\r\n\x1a\nfixture"


class Event(AstrMessageEvent):
    async def send(self, message):
        self.sent = message


def event_for(parts, adapter="aiocqhttp", raw=None, wake=False, group=True):
    message = AstrBotMessage()
    message.type = MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE
    message.sender = MessageMember("100", "Caller")
    message.self_id = "999"
    message.message = parts
    message.message_str = "".join(part.text for part in parts if isinstance(part, Plain))
    message.raw_message = raw
    event = Event(message.message_str, message, PlatformMetadata(adapter, "test", "adapter-1"), "group-1")
    event.is_at_or_wake_command = wake
    return event


class ParsingTests(unittest.TestCase):
    def test_mode_suffix_and_username_spaces(self):
        command = arguments.parse_command("/stat Player Name:3", [])
        self.assertEqual((command.name, command.username, command.mode), ("stat", "Player Name", 3))
        self.assertEqual(arguments.parse_command("/statme:0", []).mode, 0)
        self.assertEqual(arguments.parse_command("/bp 1-10:3", []).last, 10)

    def test_mention_and_default_mode(self):
        command = arguments.parse_command("/pr :3", ["200"])
        request = service.build_request(command, identity.Identity("qq", "100"), "default")
        self.assertEqual(request.params["platform_uid"], "200")
        self.assertEqual(request.params["game_mode"], 3)
        self.assertFalse(request.params["include_fails"])
        request = service.build_request(arguments.parse_command("/recent", []), identity.Identity("qq", "100"), "default")
        self.assertTrue(request.params["include_fails"])
        self.assertNotIn("game_mode", request.params)
        self.assertNotIn("recent_end", request.params)
        self.assertNotIn("legacy_only", request.params)

    def test_bp_single_range_and_mutation_contract(self):
        caller = identity.Identity("qq", "100")
        request = service.build_request(arguments.parse_command("/bp 3", []), caller, "yaowan")
        self.assertEqual(request.path, "/score/best_play")
        self.assertEqual(request.params["theme"], "yaowan")
        request = service.build_request(arguments.parse_command("/bp 1-10", ["200"]), caller, "yaowan")
        self.assertEqual(request.path, "/score/best_plays")
        self.assertNotIn("theme", request.params)
        request = service.build_request(arguments.parse_command("/bind Player Name", []), caller, "default")
        self.assertEqual(request.body, {"platform": "qq", "platformUid": "100", "osuUsername": "Player Name"})
        self.assertEqual(service.build_request(arguments.parse_command("/mode mania", []), caller, "default").body["gameMode"], 3)
        self.assertEqual(service.build_request(arguments.parse_command("/beatmap 123", []), caller, "yaowan").params, {"beatmap_id": 123, "theme": "default"})

    def test_invalid_arguments(self):
        cases = [("/pr 2", []), ("/recent 1-5", []), ("/statme:4", []), ("/statme:abc", []),
                 ("/bp 0", []), ("/bp 1-21", []), ("/bp 10-1", []), ("/bp 101", []),
                 ("/stat", []), ("/bind", []), ("/mode 4", []), ("/beatmap -1", []),
                 ("/unbind", ["200"]), ("/statme", ["200"]), ("/stat Player", ["200"]),
                 ("/pr", ["200", "300"])]
        for text, mentions in cases:
            with self.subTest(text=text, mentions=mentions), self.assertRaises(ValueError):
                arguments.parse_command(text, mentions)

    def test_platform_identity_is_not_session_id(self):
        self.assertEqual(identity.resolve_identity("aiocqhttp", "bot1", "100"), identity.Identity("qq", "100"))
        self.assertEqual(identity.resolve_identity("qq_official", "bot1", "100").platform, "qq_official:bot1")
        self.assertEqual(identity.resolve_identity("discord", "bot1", "100").platform, "discord")
        self.assertNotEqual(identity.resolve_identity("custom", "bot1", "100").platform,
                            identity.resolve_identity("custom", "bot2", "100").platform)

    def test_real_components_ignore_bot_and_keep_target(self):
        event = event_for([At(qq="999"), Plain("/bp "), At(qq="200"), Plain(" 1-10:3")])
        self.assertEqual(main.mentioned_users(event), ["200"])
        command = arguments.parse_command(main.command_text(event), main.mentioned_users(event))
        self.assertEqual((command.target_uid, command.first, command.last, command.mode), ("200", 1, 10, 3))

    def test_discord_structured_mentions_and_telegram_unsupported(self):
        event = event_for([Plain("/pr <@200>:3")], "discord", SimpleNamespace(mentions=[SimpleNamespace(id=200)]))
        self.assertEqual(arguments.parse_command(main.command_text(event), main.mentioned_users(event)).target_uid, "200")
        event = event_for([At(qq="player", name="player"), Plain("/pr @player")], "telegram")
        with self.assertRaises(ValueError):
            main.mentioned_users(event)

    def test_filter_does_not_capture_ordinary_chat(self):
        command_filter = main.MintCommandFilter()
        for text in ["/statme:3", "/pr", "/recent :1", "/bp 1-10", "/minthelp"]:
            self.assertTrue(command_filter.filter(event_for([Plain(text)]), {}))
        for text in ["statme", "recent news", "/statme_extra", "hello /pr", "/osu stat"]:
            self.assertFalse(command_filter.filter(event_for([Plain(text)]), {}))
        self.assertTrue(command_filter.filter(event_for([Plain("statme:3")], wake=True), {}))
        self.assertEqual(star_map[main.MintOsuPlugin.__module__].name, "astrbot_plugin_mint_osu")

    def test_official_qq_mentions_use_member_openid(self):
        raw = SimpleNamespace(group_openid="group", mentions=[SimpleNamespace(id="mention-id", member_openid="member-id")])
        event = event_for([At(qq="999"), Plain("/stat <@mention-id>:3")], "qq_official", raw)
        command = arguments.parse_command(main.command_text(event), main.mentioned_users(event))
        self.assertEqual((command.target_uid, command.mode), ("member-id", 3))
        raw.mentions = [SimpleNamespace(id="mention-id")]
        with self.assertRaises(ValueError):
            main.mentioned_users(event)
        with self.assertRaises(ValueError):
            main.mentioned_users(event_for([Plain("/pr "), AtAll()]))

    def test_slack_and_telegram_bot_mentions(self):
        event = event_for([At(qq="200"), Plain("/bp 2:1")], "slack")
        command = arguments.parse_command(main.command_text(event), main.mentioned_users(event))
        self.assertEqual(command.target_uid, "200")
        event = event_for([At(qq="MintBot", name="MintBot"), Plain("/statme")], "telegram")
        event.message_obj.self_id = "MintBot"
        self.assertEqual(main.mentioned_users(event), [])

    def test_bind_conflict_and_target_unbound_messages(self):
        command = arguments.parse_command("/bind Player", [])
        self.assertIn("先使用 /unbind", service.error_message(command, 409, "User already bound", None))
        command = arguments.parse_command("/stat", ["200"])
        self.assertIn("对方", service.error_message(command, 404, "User not found", None))
        self.assertIn("5 秒", service.error_message(command, 503, "", "5"))


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.status = 200
        self.reply = PNG
        self.content_type = "image/png"
        async def handler(request):
            self.requests.append((request.method, request.path, dict(request.query), request.headers.get("access_token"),
                                  await request.json() if request.method == "POST" else None))
            return web.Response(status=self.status, body=self.reply, content_type=self.content_type, headers={"Retry-After": "5"})
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = client_module.MintClient(str(self.server.make_url("")), "test-secret")

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_auth_query_and_binary_image(self):
        command = arguments.parse_command("/pr:3", [])
        result = await self.client.request(service.build_request(command, identity.Identity("qq", "100"), "default"))
        self.assertEqual(result, PNG)
        method, path, params, token, _ = self.requests[0]
        self.assertEqual((method, path, token), ("GET", "/score/recent_play", "test-secret"))
        self.assertEqual(params["include_fails"], "false")
        self.assertEqual(params["game_mode"], "3")

    async def test_post_json_and_no_automatic_retry(self):
        command = arguments.parse_command("/bind Player Name", [])
        self.reply, self.content_type = b'{"message":"ok"}', "application/json"
        await self.client.request(service.build_request(command, identity.Identity("qq", "100"), "default"))
        self.assertEqual(self.requests[0][4]["osuUsername"], "Player Name")
        self.status, self.reply = 503, b'{"error":"busy"}'
        with self.assertRaises(client_module.MintAPIError) as caught:
            await self.client.request(service.build_request(command, identity.Identity("qq", "100"), "default"))
        self.assertEqual(caught.exception.retry_after, "5")
        self.assertEqual(len(self.requests), 2)

    async def test_plugin_handler_uses_actual_astrbot_image_component(self):
        plugin = main.MintOsuPlugin(SimpleNamespace(), {"theme": "default"})
        plugin._client = self.client
        event = event_for([Plain("/stat "), At(qq="200"), Plain(":3")], group=False)
        results = [result async for result in plugin.handle_command(event)]
        self.assertIsInstance(results[0].chain[0], Image)
        self.assertEqual(await results[0].chain[0].convert_to_base64(), "iVBORw0KGgpmaXh0dXJl")
        self.assertEqual(self.requests[0][2]["platform_uid"], "200")
        self.assertTrue(event.is_stopped())
        await plugin.terminate()
        self.assertTrue(self.client._session.closed)

    async def test_statme_unbound_and_bp_empty_are_distinct(self):
        plugin = main.MintOsuPlugin(SimpleNamespace(), {})
        plugin._client = self.client
        self.status, self.reply, self.content_type = 404, b"User not found", "text/plain"
        results = [result async for result in plugin.handle_command(event_for([Plain("/statme")]))]
        self.assertIn("/bind", results[0].chain[0].text)
        self.reply = b"No best play record found"
        results = [result async for result in plugin.handle_command(event_for([Plain("/bp")]))]
        self.assertIn("没有符合条件", results[0].chain[0].text)

    async def test_invalid_image_and_plaintext_auth_error(self):
        request = service.build_request(arguments.parse_command("/statme", []), identity.Identity("qq", "100"), "default")
        self.reply = b"not a png"
        with self.assertRaises(client_module.MintAPIError):
            await self.client.request(request)
        self.status, self.reply, self.content_type = 403, b"Access Token required", "text/plain"
        with self.assertRaises(client_module.MintAPIError) as caught:
            await self.client.request(request)
        self.assertEqual(caught.exception.status, 403)

    async def test_help_and_validation_do_not_require_api(self):
        plugin = main.MintOsuPlugin(SimpleNamespace(), {})
        event = event_for([Plain("/minthelp")])
        results = [result async for result in plugin.handle_command(event)]
        self.assertIn("/statme", results[0].chain[0].text)
        results = [result async for result in plugin.handle_command(event_for([Plain("/recent 2")]))]
        self.assertIn("只查询最近一条", results[0].chain[0].text)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
