import asyncio
import base64
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
        self.assertIn("/作答 歌名", results[0].chain[0].text)
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

    async def test_explicit_answer_accepts_local_typo_without_model(self):
        await self.open_round()
        event = self.answer_event("/作答 Bad Aplpe")
        results = [result async for result in self.plugin.handle_command(event)]
        self.assertIn("Caller 答对了", results[0].chain[0].text)
        self.context.llm_generate.assert_not_awaited()

    async def test_exact_answer_wins_while_model_is_pending(self):
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
