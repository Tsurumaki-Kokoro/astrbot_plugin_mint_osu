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
    def test_match_links_options_and_contract(self):
        for source in ["123456", "https://osu.ppy.sh/community/matches/123456", "https://osu.ppy.sh/mp/123456?x=1#game"]:
            command = arguments.parse_command(f"/mp {source} --page 0 --team-type tag-coop", [])
            request = service.build_request(command, identity.Identity("qq", "100"), "yaowan")
            self.assertEqual(request.path, "/multiplayer/history")
            self.assertEqual(request.params, {"mp_id": 123456, "page": 0, "theme": "default", "team_type": "tag-coop"})
        for algorithm in ["osuplus", "bathbot", "flashlight"]:
            command = arguments.parse_command(f"/rating 123 --algorithm {algorithm} --page 2 --team-type team-vs", [])
            request = service.build_request(command, identity.Identity("qq", "100"), "default")
            self.assertEqual(request.path, "/multiplayer/rating")
            self.assertEqual(request.params["algorithm"], algorithm)
            self.assertEqual(request.params["page"], 2)
        command = arguments.parse_command("/rating 123", [])
        self.assertEqual((command.page, command.algorithm, command.team_type), (1, "osuplus", None))

    def test_invalid_match_arguments(self):
        for text in ["/mp", "/mp 0", "/mp 2147483648", "/mp https://evil.test/mp/123", "/mp https://osu.ppy.sh/beatmaps/123",
                     "/mp https://osu.ppy.sh@evil.test/mp/123", "/mp 123 --algorithm bathbot", "/mp 123 --page -1",
                     "/mp 123 --page 1 --page 2", "/rating 123 --page 0", "/rating 123 --algorithm unknown",
                     "/rating 123 --team-type tag-coop", "/rating 123 --algorithm", "/rating 123:3"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                arguments.parse_command(text, [])
        with self.assertRaises(ValueError):
            arguments.parse_command("/mp 123", ["200"])

    def test_search_keyword_mode_and_cursor_contract(self):
        command = arguments.parse_command('/search artist:"Blue Zenith" stars>5 --page 2 --cursor abc+/=:3', [])
        request = service.build_request(command, identity.Identity("qq", "100"), "default")
        self.assertEqual(request.path, "/beatmap/search/image")
        self.assertEqual(request.params, {"query": 'artist:"Blue Zenith" stars>5', "page": 2, "mode": "mania", "cursor_string": "abc+/="})
        request = service.build_request(arguments.parse_command("/search Blue Zenith", []), identity.Identity("qq", "100"), "default")
        self.assertEqual(request.params["mode"], "any")
        self.assertNotIn("platform", request.params)

    def test_new_map_commands_and_preview_options(self):
        for text, path, key in [("/beatmapset 123", "/beatmap/beatmapset", "beatmapset_id"),
                                ("/cover 123", "/beatmap/cover", "beatmap_id"), ("/bpm 123", "/beatmap/bpm", "beatmap_id")]:
            with self.subTest(text=text):
                request = service.build_request(arguments.parse_command(text, []), identity.Identity("qq", "100"), "yaowan")
                self.assertEqual((request.path, request.params[key]), (path, 123))
                self.assertNotIn("platform", request.params)
        request = service.build_request(arguments.parse_command("/preview 123 --mods hd,dt --format png", []), identity.Identity("qq", "100"), "default")
        self.assertEqual(request.params, {"beatmap_id": 123, "format": "png", "mods": ["HD", "DT"], "selection": "auto"})
        self.assertEqual(request.image_types, ("png",))
        self.assertEqual(arguments.parse_command("/preview 123", []).format, "gif")
        self.assertNotIn("mods", service.build_request(arguments.parse_command("/preview 123 --mods NM", []), identity.Identity("qq", "100"), "default").params)

    def test_new_commands_reject_bad_arguments_and_mentions(self):
        for text in ["/search", "/search x --page 0", "/search x --cursor", "/search x --page 2 --page 3", "/search x --unknown 2",
                     "/preview 0", "/preview 123 --format mp4", "/preview 123 --mods NM,HD", "/preview 123 --mods", "/preview 123:3",
                     "/cover -1", "/beatmapset 2147483648", "/bpm 123 extra"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                arguments.parse_command(text, [])
        for text in ["/search x", "/preview 123", "/bpm 123", "/cover 123", "/beatmapset 123"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                arguments.parse_command(text, ["200"])

    def test_structured_api_errors(self):
        command = arguments.parse_command("/cover 123", [])
        self.assertIn("谱面", service.error_message(command, 404, '{"code":"BEATMAP_NOT_FOUND"}', None))
        command = arguments.parse_command("/stat", ["200"])
        self.assertIn("对方", service.error_message(command, 404, '{"code":"USER_NOT_BOUND"}', None))

    def test_history_days_use_hash_and_preserve_mode(self):
        for text, name, days, mode in [("/nb", "nb", 1, None), ("/nb#7:3", "nb", 7, 3),
                                      ("/history", "history", 30, None), ("/history #90:1", "history", 90, 1)]:
            with self.subTest(text=text):
                command = arguments.parse_command(text, ["200"])
                self.assertEqual((command.name, command.days, command.mode, command.target_uid), (name, days, mode, "200"))

    def test_extended_query_contracts(self):
        cases = [("/nb #7:3", "/score/new_best_plays", {"days": 7}),
                 ("/fix:3", "/score/fix", {}),
                 ("/analyze:3", "/user_info/extra/performance_analyze", {"theme": "default"}),
                 ("/history #90:3", "/user_info/history", {"days": 90, "format": "png"}),
                 ("/score 123:3", "/score/user_score", {"beatmap_id": 123, "theme": "yaowan"}),
                 ("/scorehistory 123 --mods hd,hr --page 2:3", "/score/history", {"beatmap_id": 123, "mods": "HD,HR", "page": 2, "format": "png"})]
        for text, path, expected in cases:
            with self.subTest(text=text):
                command = arguments.parse_command(text, ["200"])
                request = service.build_request(command, identity.Identity("qq", "100"), "yaowan")
                self.assertEqual((request.method, request.path, request.image), ("GET", path, True))
                self.assertEqual(request.params["platform_uid"], "200")
                self.assertEqual(request.params["game_mode"], 3)
                for key, value in expected.items():
                    self.assertEqual(request.params[key], value)
                self.assertNotIn("legacy_only", request.params)

    def test_extended_invalid_arguments(self):
        for text in ["/nb 7", "/history 30", "/nb #0", "/nb #366", "/nb #7 #8", "/history #3651",
                     "/nb #abc", "/history #7x", "/fix #7", "/analyze 3", "/score", "/scorehistory -1",
                     "/score 123 --page 2", "/scorehistory 123 --page 0", "/scorehistory 123 --page",
                     "/scorehistory 123 --mods NM,HD", "/scorehistory 123 --mods HD,", "/scorehistory 123 --page 2 --page 3",
                     "/history:4", "/scorehistory 123 #7"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                arguments.parse_command(text, [])

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
    async def test_match_queries_and_page_headers_use_image_chain(self):
        plugin = main.MintOsuPlugin(SimpleNamespace(), {})
        plugin._client = self.client
        self.extra_headers = {"X-Page": "2", "X-Page-Count": "3"}
        for text, path in [("/mp 123 --page 2", "/multiplayer/history"),
                           ("/rating https://osu.ppy.sh/mp/123 --algorithm bathbot --page 2", "/multiplayer/rating")]:
            event = event_for([Plain(text)])
            self.assertTrue(main.MintCommandFilter().filter(event, {}))
            results = [result async for result in plugin.handle_command(event)]
            self.assertIsInstance(results[0].chain[0], Image)
            self.assertIn("2/3", results[0].chain[1].text)
            self.assertEqual(self.requests[-1][1], path)
            self.assertEqual(self.requests[-1][2]["mp_id"], "123")
            self.assertNotIn("platform_uid", self.requests[-1][2])
        self.assertEqual(self.requests[-1][2]["algorithm"], "bathbot")
        results = [result async for result in plugin.handle_command(event_for([Plain("/mp 123 --page 0")]))]
        self.assertIn("全部", results[0].chain[1].text)

    async def test_all_extended_commands_send_images_for_mentioned_user(self):
        plugin = main.MintOsuPlugin(SimpleNamespace(), {"theme": "yaowan"})
        plugin._client = self.client
        for text in ["/nb #7:3", "/fix:3", "/analyze:3", "/history #90:3", "/score 123:3", "/scorehistory 123 --mods NM --page 2:3"]:
            with self.subTest(text=text):
                event = event_for([Plain(text), At(qq="200")])
                self.assertTrue(main.MintCommandFilter().filter(event, {}))
                results = [result async for result in plugin.handle_command(event)]
                self.assertIsInstance(results[0].chain[0], Image)
                self.assertEqual(self.requests[-1][2]["platform_uid"], "200")
                self.assertEqual(self.requests[-1][2]["game_mode"], "3")
        self.assertEqual(self.requests[3][2]["format"], "png")
        self.assertEqual(self.requests[5][2]["format"], "png")
        self.assertEqual(self.requests[5][2]["mods"], "NM")

    async def asyncSetUp(self):
        self.requests = []
        self.status = 200
        self.reply = PNG
        self.content_type = "image/png"
        self.extra_headers = {}
        self.multi_params = []
        async def handler(request):
            self.requests.append((request.method, request.path, dict(request.query), request.headers.get("access_token"),
                                  await request.json() if request.method == "POST" else None))
            self.multi_params.append(request.query.getall("mods", []))
            return web.Response(status=self.status, body=self.reply, content_type=self.content_type, headers={"Retry-After": "5", **self.extra_headers})
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

    async def test_preview_gif_repeated_mods_and_cover_jpeg(self):
        plugin = main.MintOsuPlugin(SimpleNamespace(), {})
        plugin._client = self.client
        self.reply, self.content_type = b"GIF89a" + b"fixture", "image/gif"
        results = [result async for result in plugin.handle_command(event_for([Plain("/preview 123 --mods HD,DT")]))]
        self.assertIsInstance(results[0].chain[0], Image)
        self.assertEqual(self.multi_params[-1], ["HD", "DT"])
        self.assertEqual(self.requests[-1][2]["selection"], "auto")
        self.reply, self.content_type = b"\xff\xd8\xfffixture", "image/jpeg"
        results = [result async for result in plugin.handle_command(event_for([Plain("/cover 123")]))]
        self.assertIsInstance(results[0].chain[0], Image)
        self.reply, self.content_type = b"GIF89afixture", "image/gif"
        request = service.build_request(arguments.parse_command("/preview 123 --format png", []), identity.Identity("qq", "100"), "default")
        with self.assertRaises(client_module.MintAPIError):
            await self.client.request(request)

    async def test_search_image_preserves_pagination_metadata(self):
        self.extra_headers = {"X-Page": "2", "X-Page-Count": "10", "X-Total": "120", "X-Next-Cursor": "abc+/="}
        plugin = main.MintOsuPlugin(SimpleNamespace(), {})
        plugin._client = self.client
        results = [result async for result in plugin.handle_command(event_for([Plain("/search Blue Zenith --page 2:0")]))]
        self.assertIsInstance(results[0].chain[0], Image)
        self.assertIn("2/10", results[0].chain[1].text)
        self.assertIn("--cursor abc+/=", results[0].chain[1].text)
        self.assertEqual(self.requests[-1][2]["mode"], "osu")

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
