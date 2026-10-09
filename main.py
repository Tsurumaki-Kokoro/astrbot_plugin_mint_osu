"""AstrBot message entry point for MintAPI."""
import asyncio
import re

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, AtAll, Plain, Image, Video
from astrbot.api.star import Context, Star, register

from .arguments import COMMAND_PATTERN, parse_command
from .identity import resolve_identity
from .mint_client import MintAPIError, MintClient
from .service import build_request, error_message
from .extras import avatar_archive, group_ranking, save_attachment

HELP = """Mint osu! 命令：
/oa：自己的名片；/oa @用户：单人名片；/oa 用户名列表：ZIP，空格用户名加引号
/pp 增加PP [@用户]：增加 PP 所需成绩与 BP 位置
/previewvideo 谱面ID [--mods HD,DT] [--start preview] [--duration 30]：视频
/rank:3、/top5：当前群已绑定成员的排行榜
/stat 用户名 或 /stat @用户：资料卡
/statme：自己的资料卡
/pr [@用户]：最近一条成绩，不含失败
/recent [@用户]：最近一条成绩，包含失败
/bp [@用户] [序号或区间]：BP，默认第 1 条
/nb [@用户] [#天数]：新增 BP，默认 1 天
/fix [@用户]：BP 补 FC 分析
/analyze [@用户]：BP 成绩分析
/history [@用户] [#天数]：PP/排名趋势，默认 30 天
/score [@用户] 谱面ID：个人谱面成绩
/scorehistory [@用户] 谱面ID [--mods HD,HR] [--page 2]：谱面成绩历史
/beatmap 谱面ID：谱面信息
/search 关键词 [--page 2] [--cursor 游标]：谱面搜索，末尾可加 :模式
/preview 谱面ID [--mods HD,DT] [--format png]：默认 GIF 预览
/bpm 谱面ID：BPM 时间轴
/cover 谱面ID：谱面封面
/beatmapset 谱面集ID：谱面集信息
/mp 比赛ID或链接 [--page 2] [--team-type team-vs]：比赛历史
/rating 比赛ID或链接 [--algorithm bathbot] [--page 2]：比赛评分
评分算法：osuplus（默认）、bathbot、flashlight；支持 --team-type
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

    async def initialize(self):
        # Leave help usable when an administrator has not configured the API yet.
        try:
            self._client = self._create_client()
        except ValueError as exc:
            logger.warning(str(exc))

    def _create_client(self) -> MintClient:
        return MintClient(str(self.config.get("api_base_url", "")), str(self.config.get("api_token", "")),
                          int(self.config.get("request_timeout", 90)), int(self.config.get("max_concurrency", 2)))

    @filter.custom_filter(MintCommandFilter)
    async def handle_command(self, event: AstrMessageEvent):
        """Mint osu!：资料、成绩、BP 分析、历史、谱面与绑定命令；/minthelp 查看用法。"""
        command = None
        try:
            command = parse_command(command_text(event), mentioned_users(event))
            if command.name == "minthelp":
                yield event.plain_result(HELP)
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
            if command.name in {"rank", "top5"}:
                result = await group_ranking(self._client, command, caller, event)
            else:
                result = await self._client.request(build_request(command, caller, theme))
            if command.name == "previewvideo":
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
                        notice = f"第 {headers.get('X-Page', str(command.page))}/{headers.get('X-Page-Count', '?')} 页；使用 --page 翻页，保留比赛及筛选条件。"
                    chain.append(Plain(notice))
                if command.name == "search":
                    headers = getattr(result, "headers", {})
                    page, pages = headers.get("X-Page", str(command.page)), headers.get("X-Page-Count", "?")
                    notice = f"搜索本批第 {page}/{pages} 页，共 {headers.get('X-Total', '?')} 个谱面集。使用 --page 翻本批图片页。"
                    cursor = headers.get("X-Next-Cursor")
                    if cursor:
                        notice += f"\n下一批保留关键词与模式，使用 --page 1 --cursor {cursor}"
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

    async def terminate(self):
        if self._client is not None:
            await self._client.close()
            self._client = None
