import asyncio
import base64
from dataclasses import replace
import importlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import wave

from test_plugin import event_for, main, package, Plain
from astrbot.api.message_components import Record
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

guess = importlib.import_module(package + ".song_guess")


def wave_audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 8000, 80, "NONE", "not compressed"))
        audio.writeframes(bytes(160))
    return output.getvalue()


class SongMatchTests(unittest.TestCase):
    def test_local_title_matching(self):
        cases = [
            ("Bad Apple!!", "ＢＡＤ　 apple。", True),
            ("Bad Apple!!", "Bad Aplpe", True),
            ("Bad Apple!!", "Apple", False),
            ("Bad Apple!!", "Bad Appel?", True),
            ("Bad Apple!!", "Bad Appla", False),
            ("Bad Apple!!", "Bad Aplpel", False),
            ("Bad Apple!!", "Bad Apple 2", False),
            ("Bad Apple!!", "Bad Apple (Remix)", False),
            ("Bad Apple!!", "Bad Apelp", False),
            ("Apple", "Aplpe", False),
            ("Bad Apple IV", "Bad Apple VI", False),
            ("Bad Apple (Remix)", "Bad Apple (Remxi)", False),
            ("Bad Apple (Remix)", "Bad Apple", False),
            ("Bad Apple 12", "Bad Apple 21", False),
            ("Bad Apple+", "Bad Apple", False),
            ("Bad Apple#", "Bad Apple", False),
            ("A—B ‘Song’", "a-b 'song'", True),
            ("青い空。", "青い空", True),
            ("青い空。", "青空い", False),
            ("星 Bad Apple", "星 Bad Aplpe", False),
            ("Bad Apple", "Ba dApple", False),
            ("Café Sunrise", "Cfaé Sunrise", True),
            ("!!!", "!!!", True),
            ("!!!", "", False),
        ]
        for title, answer, expected in cases:
            with self.subTest(title=title, answer=answer):
                self.assertEqual(guess.Song(1, title, "", "", "").matches(answer), expected)

    def test_either_official_title_can_match(self):
        song = guess.Song(1, "Hoshizora Memories", "星空の思い出", "", "")
        self.assertTrue(song.matches("Hoshizroa Memories"))
        self.assertTrue(song.matches("星空の思い出！"))
        self.assertFalse(song.matches("星空の思出い"))


class SongGuessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = SimpleNamespace(
            send_message=AsyncMock(return_value=True),
            get_current_chat_provider_id=AsyncMock(return_value="chat"),
            llm_generate=AsyncMock(return_value=SimpleNamespace(completion_text="SAME")),
        )
        self.plugin = main.MintOsuPlugin(self.context, {})
        self.game = self.plugin._song_guess
        self.event = event_for([Plain("/猜歌 :3")])
        self.event.message_obj.group_id = "123"
        self.event.get_group = AsyncMock(return_value=SimpleNamespace(
            member_count=2, members=[SimpleNamespace(user_id="100"), SimpleNamespace(user_id="200")]
        ))
        self.session = guess.group_session(self.event)
        self.song = guess.Song(42, "Bad Apple!!", "Ｂａｄ　Ａｐｐｌｅ!!", "Artist", "")
        self.audio = wave_audio()
        self.client = SimpleNamespace(request=AsyncMock(side_effect=[
            {"platform_uids": ["200"]},
            {"userId": 2000, "username": "Player", "gameMode": 3,
             "beatmapsets": [{"id": 42, "title": self.song.title, "titleUnicode": self.song.title_unicode,
                              "artist": self.song.artist, "artistUnicode": ""}]},
        ]), close=AsyncMock())
        self.plugin._client = self.client
        self.addAsyncCleanup(self.plugin.terminate)

    async def open_round(self):
        with patch.object(guess, "download_preview", AsyncMock(return_value=self.audio)) as download:
            results = [result async for result in self.plugin.handle_command(self.event)]
            download.assert_awaited_once()
        return results

    def answer_event(self, text, group="123"):
        event = event_for([Plain(text)])
        event.message_obj.group_id = group
        return event

    async def test_group_bp_to_audio_and_normalized_plain_answer(self):
        results = await self.open_round()
        self.assertIn("用 作答 歌名", results[0].chain[0].text)
        self.assertIn("发 猜歌提示", results[0].chain[0].text)
        self.assertNotIn("Player", results[0].chain[0].text)
        self.assertIsInstance(self.event.sent.chain[0], Record)
        payload = await AiocqhttpMessageEvent._from_segment_to_dict(self.event.sent.chain[0])
        encoded = base64.b64encode(self.audio).decode("ascii")
        self.assertEqual(payload, {"type": "record", "data": {"file": f"base64://{encoded}"}})
        bindings, bp = [call.args[0] for call in self.client.request.await_args_list]
        self.assertEqual(bindings.body["platformUids"], ["100", "200"])
        self.assertEqual(bp.params, {"platform": "qq", "platform_uid": "200", "game_mode": 3})
        self.assertEqual(self.game.seen(self.session), {42})

        event = self.answer_event(" bad   aplpe ")
        with patch.dict(main.star_map, {main.__name__: SimpleNamespace(star_cls=self.plugin)}):
            answer_filter = main.SongAnswerFilter()
            self.assertFalse(answer_filter.filter(self.answer_event("坏苹果"), {}))
            self.assertFalse(answer_filter.filter(self.answer_event("Apple"), {}))
            self.assertFalse(answer_filter.filter(self.answer_event("Bad Apple!!", group="999"), {}))
            self.assertFalse(answer_filter.filter(self.answer_event("/作答 Bad Apple!!"), {}))
            self.assertTrue(answer_filter.filter(event, {}))
        result = [item async for item in self.plugin.handle_song_answer(event)]
        self.assertIn("Caller 答对了", result[0].chain[0].text)
        self.assertIn("Player", result[0].chain[0].text)
        self.assertNotIn(self.session, self.game.rounds)
        self.context.llm_generate.assert_not_awaited()

    async def test_explicit_alias_uses_only_answer_and_song_metadata(self):
        await self.open_round()
        event = self.answer_event("/作答 坏苹果")
        results = [result async for result in self.plugin.handle_command(event)]
        self.assertIn("Caller 答对了", results[0].chain[0].text)
        request = self.context.llm_generate.await_args.kwargs
        self.assertEqual(request["chat_provider_id"], "chat")
        self.assertEqual(json.loads(request["prompt"]), {
            "answer": "坏苹果", "title": self.song.title,
            "title_unicode": self.song.title_unicode, "artist": "Artist",
        })
        self.assertNotIn("contexts", request)

    async def test_model_rate_limit_is_per_user_and_expires(self):
        self.plugin.config.update(
            song_guess_model_rate_limit_enabled=True,
            song_guess_model_rate_limit_per_minute=2,
        )
        self.context.llm_generate.return_value.completion_text = "DIFFERENT"
        self.plugin.config["command_prefixes"] = ["/", "!"]
        await self.open_round()
        other_room = self.answer_event("!作答 第三个别名", group="999")
        other_session = guess.group_session(other_room)
        self.game.rounds[other_session] = replace(
            self.game.rounds[self.session], judged=set(), attempts=[], timer=None, submissions={},
        )

        async def submit(event):
            results = [item async for item in self.plugin.handle_command(event)]
            return results[0].chain[0].text

        with patch.object(guess, "monotonic", return_value=100) as clock:
            for alias in ("第一个别名", "第二个别名"):
                self.assertEqual(await submit(self.answer_event(f"!作答 {alias}")),
                                 "这次没猜中，可以继续答题。")
            self.assertIn("请在 60 秒后再试", await submit(other_room))
            self.assertEqual(self.context.llm_generate.await_count, 2)

            other_user = self.answer_event("!作答 其他人的别名")
            other_user.message_obj.sender.user_id = "200"
            self.assertIn("没猜中", await submit(other_user))

            local = self.answer_event(f"!作答 {self.song.title}")
            self.assertIn("答对了", await submit(local))
            self.assertEqual(self.context.llm_generate.await_count, 3)

            clock.return_value = 160
            self.assertIn("没猜中", await submit(other_room))
            self.assertEqual(self.context.llm_generate.await_count, 4)

    async def submit_answer(self, answer, group="123"):
        event = self.answer_event(f"!作答 {answer}", group=group)
        return [item async for item in self.plugin.handle_command(event)][0].chain[0].text

    async def open_cooldown_round(self, **settings):
        self.plugin.config.update(
            command_prefixes=["/", "!"],
            song_guess_model_rate_limit_mode="按判错次数",
            **settings,
        )
        await self.open_round()

    async def test_wrong_answer_cooldown_excludes_unsure_and_replaces_legacy_limit(self):
        await self.open_cooldown_round(
            song_guess_model_rate_limit_enabled=True,
            song_guess_model_rate_limit_per_minute=1,
            song_guess_model_cooldown_seconds=30,
        )
        with patch.object(guess, "monotonic", return_value=100) as clock:
            for i, verdict in enumerate(("DIFFERENT", "UNSURE", "DIFFERENT", "DIFFERENT")):
                self.context.llm_generate.return_value.completion_text = verdict
                response = await self.submit_answer(f"别名{i}")
                if i < 3:
                    self.assertNotIn("冷却", response)
            self.assertIn("冷却 30 秒", response)
            self.assertIn("30 秒后再试", await self.submit_answer("下一个别名"))
            self.assertEqual(self.context.llm_generate.await_count, 4)
            clock.return_value = 130
            self.assertNotIn("冷却", await self.submit_answer("下一个别名"))
            self.assertEqual(self.context.llm_generate.await_count, 5)

    async def test_repeated_answer_cooldown_crosses_groups_and_local_win_clears_it(self):
        await self.open_cooldown_round()
        self.context.llm_generate.return_value.completion_text = "UNSURE"
        other_session = guess.group_session(self.answer_event("", group="999"))
        self.game.rounds[other_session] = replace(
            self.game.rounds[self.session], judged=set(), attempts=[], timer=None, submissions={},
        )
        with patch.object(guess, "monotonic", return_value=100):
            self.assertIn("无法确认", await self.submit_answer("Example Name"))
            self.assertIn("已经判定", await self.submit_answer("ＥＸＡＭＰＬＥ  NAME"))
            self.assertIn("重复提交", await self.submit_answer("example name"))
            self.assertIn("60 秒后再试", await self.submit_answer("另一个别名", group="999"))
            self.assertEqual(self.context.llm_generate.await_count, 1)

            event = self.answer_event(self.song.title, group="999")
            results = [item async for item in self.plugin.handle_song_answer(event)]
            self.assertIn("答对了", results[0].chain[0].text)
            self.assertIn("无法确认", await self.submit_answer("另一个别名"))
            self.assertEqual(self.context.llm_generate.await_count, 2)

    async def test_repeated_submissions_outside_window_expire(self):
        await self.open_cooldown_round()
        self.context.llm_generate.return_value.completion_text = "UNSURE"
        with patch.object(guess, "monotonic", return_value=100) as clock:
            self.assertIn("无法确认", await self.submit_answer("同一个别名"))
            self.assertIn("已经判定", await self.submit_answer("同一个别名"))

            clock.return_value = 160
            self.assertIn("已经判定", await self.submit_answer("同一个别名"))
            self.assertIn("已经判定", await self.submit_answer("同一个别名"))
            self.assertIn("重复提交", await self.submit_answer("同一个别名"))
            self.assertEqual(self.context.llm_generate.await_count, 1)

    async def test_cooldown_mode_allows_only_one_pending_model_call_per_user(self):
        await self.open_cooldown_round()
        started, release = asyncio.Event(), asyncio.Event()

        async def judge(**kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(completion_text="DIFFERENT")

        self.context.llm_generate.side_effect = judge
        pending = asyncio.create_task(self.submit_answer("第一个别名"))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertIn("正在判定", await asyncio.wait_for(self.submit_answer("第二个别名"), timeout=1))
            self.assertEqual(self.context.llm_generate.await_count, 1)
        finally:
            release.set()
            await pending
        self.assertIn("没猜中", await self.submit_answer("第二个别名"))

    async def test_explicit_alias_uses_configured_song_guess_provider(self):
        self.plugin.config["song_guess_model_provider_id"] = "song-judge"
        await self.open_round()
        event = self.answer_event("/作答 坏苹果")
        results = [result async for result in self.plugin.handle_command(event)]
        self.assertIn("Caller 答对了", results[0].chain[0].text)
        self.assertEqual(self.context.llm_generate.await_args.kwargs["chat_provider_id"], "song-judge")
        self.context.get_current_chat_provider_id.assert_not_awaited()

    async def test_chart_round_sends_only_one_unlabelled_gif_for_converted_bp(self):
        event = self.answer_event("/谱面猜歌 :3")
        event.get_group = self.event.get_group
        self.client.request.side_effect = [
            {"platform_uids": ["200"]},
            {"userId": 2000, "username": "Player", "gameMode": 3,
             "beatmapsets": [{"id": 42, "title": "Bad Apple!!", "titleUnicode": "",
                              "artist": "Artist", "artistUnicode": "", "beatmapId": 84, "beatmapMode": 0}]},
            b"GIF89a",
        ]
        with patch.object(guess, "download_preview", AsyncMock()) as download:
            self.assertEqual([result async for result in self.plugin.handle_command(event)], [])
            download.assert_not_awaited()
        request = self.client.request.await_args.args[0]
        self.assertEqual(request.path, "/beatmap/preview/image")
        self.assertEqual(request.params, {"beatmap_id": 84, "format": "gif", "show_time_labels": False,
                                          "convert": "mania"})
        self.assertEqual(request.image_types, ("gif",))
        self.assertEqual(len(event.sent.chain), 1)
        self.assertIsInstance(event.sent.chain[0], guess.Image)
        self.assertIn("已有一局", await self.game.start(self.client, None, event, self.session, None, True))
        self.assertIn("答对了", self.game.accept_local_answer(self.session, event, "Bad Apple"))

    async def test_catch_preview_uses_bp_mode_and_skips_an_unconvertible_map(self):
        event = self.answer_event("/谱面猜歌 :2")
        event.get_group = self.event.get_group
        maps = [
            {"id": item, "title": title, "titleUnicode": "", "artist": "", "artistUnicode": "",
             "beatmapId": item + 10, **metadata}
            for item, title, metadata in (
                (40, "Unsupported", {"beatmapMode": 1}),
                (42, "Missing source", {}),
            )
        ]
        rejected = main.MintAPIError(400, json.dumps({
            "code": "INVALID_ARGUMENT", "message": "Only Standard beatmaps can be converted to another mode."
        }))
        self.client.request.side_effect = [
            {"platform_uids": ["200"]},
            {"userId": 2000, "username": "Player", "gameMode": 2, "beatmapsets": maps},
            rejected, b"GIF89a",
        ]
        with patch.object(guess.random, "shuffle"):
            self.assertEqual([item async for item in self.plugin.handle_command(event)], [])
        requests = [call.args[0] for call in self.client.request.await_args_list[2:]]
        self.assertEqual([(req.params["beatmap_id"], req.params.get("convert")) for req in requests],
                         [(50, "ctb"), (52, "ctb")])
        self.assertIn("Catch", self.game.active(self.session).source)

    async def test_catch_preview_propagates_renderer_failure_for_native_map(self):
        event = self.answer_event("/谱面猜歌 :2")
        event.get_group = self.event.get_group
        unavailable = main.MintAPIError(502, '{"code":"PREVIEW_UNAVAILABLE"}')
        self.client.request.side_effect = [
            {"platform_uids": ["200"]},
            {"userId": 2000, "username": "Player", "gameMode": 2,
             "beatmapsets": [{"id": 42, "title": "Native Catch", "titleUnicode": "",
                              "artist": "", "artistUnicode": "", "beatmapId": 52, "beatmapMode": 2}]},
            unavailable,
        ]
        with self.assertRaises(main.MintAPIError) as failure:
            await self.game.pick(self.client, main.resolve_identity("aiocqhttp", "bot", "1"),
                                 event, self.session, 2, chart=True)
        self.assertIs(failure.exception, unavailable)
        self.assertEqual(self.client.request.await_args.args[0].params["convert"], "ctb")

    async def test_explicit_answer_accepts_local_typo_without_model(self):
        await self.open_round()
        event = self.answer_event("/作答 Bad Aplpe")
        results = [result async for result in self.plugin.handle_command(event)]
        self.assertIn("Caller 答对了", results[0].chain[0].text)
        self.context.llm_generate.assert_not_awaited()

    async def test_song_board_command_reports_a_settled_local_answer(self):
        self.plugin._song_board = main.SongLeaderboard(":memory:")
        await self.open_round()
        event = self.answer_event("/作答 " + self.song.title)
        self.assertIn("答对了", [item async for item in self.plugin.handle_command(event)][0].chain[0].text)
        query = self.answer_event("/猜歌榜")
        board = [item async for item in self.plugin.handle_command(query)][0].chain[0].text
        self.assertIn("Caller · 1 局", board)
        self.assertIn("报起来吧！", board)
        self.assertNotIn("最佳搜狗", board)
        self.context.llm_generate.assert_not_awaited()

    async def test_exact_answer_wins_while_model_is_pending(self):
        self.plugin._stats = main.UsageStats(":memory:")
        await self.open_round()
        started, release = asyncio.Event(), asyncio.Event()

        async def judge(**kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(completion_text="SAME")

        self.context.llm_generate.side_effect = judge
        pending = asyncio.create_task(self.game.answer(self.session, self.event, "坏苹果", True))
        await started.wait()
        self.assertIn("答对了", self.game.accept_local_answer(self.session, self.event, self.song.title))
        release.set()
        self.assertIsNone(await pending)
        self.context.send_message.assert_not_awaited()
        rows = self.plugin._stats.judgments(7)["items"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["answer"], rows[0]["title"]), ("坏苹果", self.song.name))
        self.assertEqual((rows[0]["result"], rows[0]["settled"]), ("same", 0))

    async def test_five_model_judgments_share_capacity_and_only_one_wins(self):
        await self.open_round()
        release = asyncio.Event()

        async def judge(**kwargs):
            await release.wait()
            return SimpleNamespace(completion_text="SAME")

        self.context.llm_generate.side_effect = judge
        pending = [
            asyncio.create_task(self.game.answer(self.session, self.event, f"别名{i}", True))
            for i in range(5)
        ]
        try:
            await asyncio.sleep(0)
            self.assertEqual(self.context.llm_generate.await_count, 5)
            other_session = "other-group"
            self.game.rounds[other_session] = guess.Round(
                owner="100", song=self.song, source="Player",
                deadline=self.game.rounds[self.session].deadline,
            )
            busy = await self.game.answer(other_session, self.event, "另一个别名", True)
            self.assertIn("稍后再试", busy)
            self.assertEqual(self.context.llm_generate.await_count, 5)
        finally:
            release.set()
            results = await asyncio.gather(*pending)
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertIn("答对了", winners[0])
        self.assertIn("答对了", await self.game.answer(other_session, self.event, "另一个别名", True))

    async def test_audio_failure_releases_group_without_consuming_song(self):
        self.event.send = AsyncMock(side_effect=RuntimeError("send failed"))
        results = await self.open_round()
        self.assertIn("发送失败", results[0].chain[0].text)
        self.assertNotIn(self.session, self.game.rounds)
        self.assertEqual(self.game.seen(self.session), set())

    async def test_expiry_reveals_once_and_clears_round(self):
        with patch.object(guess, "ROUND_SECONDS", 0):
            await self.open_round()
        game = self.game.rounds[self.session]
        await game.timer
        self.context.send_message.assert_awaited_once()
        session, message = self.context.send_message.await_args.args
        self.assertEqual(session, self.session)
        self.assertIn("猜歌超时", message.chain[0].text)
        self.assertNotIn(self.session, self.game.rounds)
