"""AstrBot message entry point for MintAPI."""
import asyncio
import re
import json
from .tools import update_qq_menu, update_qq_panels

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, AtAll, Plain, Image, Video
from astrbot.api.star import Context, Star, StarTools, register

from .arguments import COMMAND_PATTERN, parse_command
from .identity import resolve_identity
from .mint_client import MintAPIError, MintClient
from .service import Request, build_request, error_message
from .extras import avatar_archive, group_ranking, save_attachment
from .subscriptions import Subscriptions
from .player_subscriptions import PlayerSubscriptions
from .player_features import compare_scores

HELP = """Mint osu! 命令：
/oa：自己的名片；/oa @用户：单人名片；/oa 用户名列表：ZIP，空格用户名加引号
/pp 增加PP [@用户]：增加 PP 所需成绩与 BP 位置
/previewv 谱面ID [-m HD,DT] [-s preview] [-d 30]：视频
/rank:3、/top5：当前群已绑定成员的排行榜
/stat 用户名 [#天数] 或 /stat @用户 [#天数]：资料卡
/statme [#天数]：自己的资料卡，默认对比当日凌晨
对比天数超出历史范围时使用最早可用快照
/pr [@用户]：最近一条成绩，不含失败
/recent [@用户]：最近一条成绩，包含失败
/bp [@用户] [序号或区间]：BP，默认第 1 条
/nb [@用户] [#天数]：新增 BP，默认 1 天
/weekly [@用户] [-w YYYY-MM-DD][:模式]：个人周报，默认上一完整周
/compare [@用户] 谱面ID [-m HD,HR] [-l stable]：与自己对比
/compare 谱面ID 用户A 用户B：两名 osu! 玩家的同图成绩，空格名字加引号
/bpwatch [用户名或@用户][:模式]：订阅本群玩家动态，省略查询自己
/bpwatch list [-p 2]、stop [用户名或@用户][:模式]、stopall：群内查询和取消
玩家订阅增删需要群管理员；省略模式时订阅 Standard，stop 默认取消玩家全部模式
/fix [@用户]：BP 补 FC 分析
/analyze [@用户]：BP 成绩分析
/history [@用户] [#天数]：PP/排名趋势，默认 30 天
/score [@用户] 谱面ID：个人谱面成绩
/scorehistory [@用户] 谱面ID [-m HD,HR] [-p 2]：谱面成绩历史
/beatmap 谱面ID：谱面信息
/search 关键词 [-p 2] [-c 游标]：谱面搜索，末尾可加 :模式
/preview 谱面ID [-m HD,DT] [-f png]：默认 GIF 预览
/bpm 谱面ID：BPM 时间轴
/cover 谱面ID：谱面封面
/beatmapset 谱面集ID：谱面集信息
/mp 比赛ID或链接 [-p 2] [-t team-vs]：比赛历史
/rating 比赛ID或链接 [-a bathbot] [-p 2]：比赛评分
/mpwatch 比赛ID或链接：订阅比赛；list：列表；stop 比赛ID或链接、stopall：停止
订阅上限与检查间隔由插件配置决定；群内修改需要管理员权限
评分算法：osuplus（默认）、bathbot、flashlight；支持 -t
/bind 用户名、/unbind：绑定与解绑
/mode 0～3：默认模式
资料卡和成绩命令末尾可加 :0～:3。
0 osu! · 1 taiko · 2 catch · 3 mania
例如 /statme:3、/bp 1-10:3、/nb #7:3"""


def command_text(event: AstrMessageEvent) -> str:
    # message_str may contain adapter-generated @ placeholders. Plain segments
    # preserve usernames and remain unchanged when AstrBot strips a wake prefix.
    parts = []
    for component in event.get_messages():
        if isinstance(component, Plain):
            parts.append(component.text)
        elif isinstance(component, At):
            parts.append(" ")
    text = "".join(parts).strip() or event.message_str.strip()
    adapter = event.get_platform_name().lower()
    if adapter in {"discord", "qq_official"}:
        raw = getattr(event.message_obj, "raw_message", None)
        # Remove only mentions confirmed by structured platform metadata.
        for mention in getattr(raw, "mentions", None) or []:
            uid = str(getattr(mention, "id", None) or "")
            if uid:
                text = text.replace(f"<@{uid}>", " ").replace(f"<@!{uid}>", " ")
    if adapter == "telegram":
        for component in event.get_messages():
            if isinstance(component, At) and component.name:
                text = re.sub(r"@" + re.escape(component.name) + r"(?!\w)", " ", text)
    return text.strip()


def mentioned_users(event: AstrMessageEvent) -> list[str]:
    self_id = str(event.get_self_id())
    ids = []
    for component in event.get_messages():
        if isinstance(component, AtAll):
            raise ValueError("请 @一位具体用户。")
        if isinstance(component, At):
            uid = str(component.qq)
            if uid not in {self_id, "qq_official"}:
                if uid in {"all", "0", "", "None"}:
                    raise ValueError("请 @一位具体用户。")
                ids.append(uid)
    adapter = event.get_platform_name().lower()
    if adapter in {"discord", "qq_official"}:
        raw = getattr(event.message_obj, "raw_message", None)
        for mention in getattr(raw, "mentions", None) or []:
            uid = str(getattr(mention, "id", None) or "")
            if uid and uid != self_id and not getattr(mention, "is_you", False):
                if adapter == "qq_official" and getattr(raw, "group_openid", None):
                    # Group mention IDs differ from sender member_openid.
                    uid = str(getattr(mention, "member_openid", None) or "")
                    if not uid:
                        raise ValueError("当前 QQ 官方消息没有提供被提及用户的绑定 ID。")
                ids.append(uid)
    if adapter == "telegram" and any(not uid.isdigit() for uid in ids):
        raise ValueError("当前 Telegram 适配器仅提供提及用户名，无法确认绑定用户 ID；请使用 /stat osu!用户名。")
    return list(dict.fromkeys(ids))


class MintCommandFilter(filter.CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        text = command_text(event)
        # Explicit slash commands work in groups; bare commands require AstrBot
        # to have woken the event, so ordinary conversation is left untouched.
        return bool(COMMAND_PATTERN.match(text)) and (text.startswith("/") or event.is_at_or_wake_command)


@register("astrbot_plugin_mint_osu", "TRANCE", "通过 MintAPI 查询 osu! 资料、成绩与谱面", "1.0.0")
class MintOsuPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._client: MintClient | None = None
        self._watch: Subscriptions | None = None
        self._player_watch: PlayerSubscriptions | None = None
        self._qq_publish_lock = asyncio.Lock()

    async def initialize(self):
        # Leave help usable when an administrator has not configured the API yet.
        try:
            self._client = self._create_client()
            self._subscriptions().start()
            self._player_subscriptions().start()
        except ValueError as exc:
            logger.warning(str(exc))

    def _subscriptions(self):
        if self._watch is None:
            path = StarTools.get_data_dir("astrbot_plugin_mint_osu") / "subscriptions.sqlite3"
            self._watch = Subscriptions(path, self._client, self.context.send_message,
                self.config.get("subscription_poll_interval", 30),
                self.config.get("subscription_max_per_session", 3))
        self._watch.client = self._client
        return self._watch

    def _player_subscriptions(self):
        if self._player_watch is None:
            path = StarTools.get_data_dir("astrbot_plugin_mint_osu") / "player_subscriptions.sqlite3"
            self._player_watch = PlayerSubscriptions(path, self._client, self.context.send_message,
                self.config.get("player_subscription_poll_interval", 30),
                self.config.get("player_subscription_max_per_group", 10))
        self._player_watch.client = self._client
        return self._player_watch

    def _create_client(self) -> MintClient:
        return MintClient(str(self.config.get("api_base_url", "")), str(self.config.get("api_token", "")),
                          int(self.config.get("request_timeout", 90)), int(self.config.get("max_concurrency", 2)))

    @filter.custom_filter(MintCommandFilter)
    async def handle_command(self, event: AstrMessageEvent):
        """Mint osu!：资料、成绩、BP 分析、历史、谱面与绑定命令；/minthelp 查看用法。"""
        command = None
        try:
            command = parse_command(command_text(event), mentioned_users(event))
            if command.name in {"mintmenu", "mintpanel"}:
                yield event.plain_result(await self._publish_qq(command.name, event))
                return
            if command.name == "minthelp":
                try:
                    if self._client is None:
                        self._client = self._create_client()
                    poster = await self._client.request(Request("GET", "/help/image", {}))
                    chain = [Image.fromBytes(poster)]
                except (ValueError, MintAPIError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(f"Mint help poster unavailable; using text help: {type(exc).__name__}")
                    chain = [Plain(HELP)]
                if event.get_platform_name().lower() == "qq_official" and event.is_private_chat() and event.is_admin():
                    chain.append(Plain("管理员：/mintmenu 同步私聊菜单；/mintpanel 同步私聊和群聊指令面板。"))
                yield event.chain_result(chain)
                return
            if command.name == "mpwatch":
                if command.action == "subscribe" and self._client is None:
                    self._client = self._create_client()
                watch = self._subscriptions()
                yield event.plain_result(await watch.command(command, event))
                if self._client is not None:
                    watch.start()
                return
            if command.name == "bpwatch":
                if self._client is None:
                    self._client = self._create_client()
                watch = self._player_subscriptions()
                yield event.plain_result(await watch.command(command, event))
                watch.start()
                return
            caller = resolve_identity(event.get_platform_name(), event.get_platform_id(), event.get_sender_id())
            theme = str(self.config.get("theme", "default"))
            if theme not in {"default", "yaowan"}:
                raise ValueError("资料卡与成绩主题只能选择 default 或 yaowan。")
            if self._client is None:
                self._client = self._create_client()
            if command.name == "oa" and command.usernames:
                attachment = await avatar_archive(self._client, command, event)
                yield event.chain_result([attachment])
                return
            if command.name == "compare":
                result = await compare_scores(self._client, command, caller)
            elif command.name in {"rank", "top5"}:
                result = await group_ranking(self._client, command, caller, event)
            else:
                result = await self._client.request(build_request(command, caller, theme))
            if command.name == "previewv":
                path = save_attachment(event, result, ".mp4")
                yield event.chain_result([Video.fromFileSystem(path)])
                return
            if command.name == "pp":
                required, position = result.get("required_pp"), result.get("position")
                import math
                if not isinstance(required, (int, float)) or not math.isfinite(required) or not isinstance(position, int):
                    raise ValueError("增加 PP 计算返回无效数据。")
                yield event.plain_result(f"增加 {command.pp:g} PP：需要约 {required:.2f} PP 的新成绩，预计位于 BP #{position}。")
                return
            if isinstance(result, bytes):
                chain = [Image.fromBytes(result)]
                if command.name in {"mp", "rating"}:
                    headers = getattr(result, "headers", {})
                    if command.page == 0:
                        notice = "全部已结束对局。"
                    else:
                        notice = f"第 {headers.get('X-Page', str(command.page))}/{headers.get('X-Page-Count', '?')} 页；使用 -p 翻页，保留比赛及筛选条件。"
                    chain.append(Plain(notice))
                if command.name == "search":
                    headers = getattr(result, "headers", {})
                    page, pages = headers.get("X-Page", str(command.page)), headers.get("X-Page-Count", "?")
                    notice = f"搜索本批第 {page}/{pages} 页，共 {headers.get('X-Total', '?')} 个谱面集。使用 -p 翻本批图片页。"
                    cursor = headers.get("X-Next-Cursor")
                    if cursor:
                        notice += f"\n下一批保留关键词与模式，使用 -p 1 -c {cursor}"
                    chain.append(Plain(notice))
                yield event.chain_result(chain)
            else:
                message = {"bind": "绑定成功。可使用 /statme 查询资料卡。", "unbind": "已解除绑定。", "mode": "默认模式已更新。"}[command.name]
                yield event.plain_result(message)
        except ValueError as exc:
            yield event.plain_result(str(exc))
        except MintAPIError as exc:
            logger.warning(f"MintAPI request failed: HTTP {exc.status}")
            yield event.plain_result(error_message(command, exc.status, exc.detail, exc.retry_after))
        except (aiohttp.ClientError, asyncio.TimeoutError):
            yield event.plain_result("无法连接 MintAPI 或请求超时，请稍后重试。")
        except Exception as exc:
            # Do not log request URLs, payloads or exception text that may include secrets.
            logger.error(f"Mint osu! command failed: {type(exc).__name__}")
            yield event.plain_result("命令处理失败，请管理员检查插件日志。")
        finally:
            event.stop_event()

    async def _publish_qq(self, name, event):
        if event.get_platform_name().lower() != "qq_official" or not event.is_private_chat():
            raise ValueError("此指令仅限 QQ 官方机器人私聊使用。")
        if not event.is_admin():
            raise ValueError("只有 AstrBot 机器人管理员可以更新 QQ 菜单和指令面板。")
        if self._qq_publish_lock.locked():
            raise ValueError("QQ 菜单或面板正在更新，请等待完成。")
        platform_id = event.get_platform_id()
        platform = self.context.get_platform_inst(platform_id)
        if platform is None:
            raise ValueError("无法找到当前 QQ 机器人，请检查适配器状态。")
        config = {"platform": [dict(platform.config)]}
        publisher = update_qq_menu if name == "mintmenu" else update_qq_panels
        payload = json.loads(publisher.PAYLOAD_PATH.read_text(encoding="utf-8"))
        backup_dir = StarTools.get_data_dir("astrbot_plugin_mint_osu") / "qq_backups"
        reports = []
        async with self._qq_publish_lock:
            # Keep synchronous QQ requests off the message/event loop.
            worker = asyncio.create_task(asyncio.to_thread(publisher.publish, None, platform_id, payload,
                config=config, backup_dir=backup_dir, report=reports.append))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # A cancelled handler must not unlock while its worker is still writing.
                try:
                    await worker
                finally:
                    raise
            except Exception as exc:
                logger.error(f"Mint QQ publish failed: {type(exc).__name__}")
                detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "更新失败，请检查插件日志。"
                return "\n".join(reports + [detail])
        return "\n".join(reports)

    async def terminate(self):
        if self._player_watch is not None:
            await self._player_watch.close()
            self._player_watch = None
        if self._watch is not None:
            await self._watch.close()
            self._watch = None
        if self._client is not None:
            await self._client.close()
            self._client = None
