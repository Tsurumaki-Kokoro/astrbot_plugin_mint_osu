"""AstrBot message entry point for MintAPI."""
import asyncio
import re

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, AtAll, Plain, Image
from astrbot.api.star import Context, Star, register

from .arguments import COMMAND_PATTERN, parse_command
from .identity import resolve_identity
from .mint_client import MintAPIError, MintClient
from .service import build_request, error_message

HELP = """Mint osu! 命令：
/stat 用户名 或 /stat @用户：资料卡
/statme：自己的资料卡
/pr [@用户]：最近一条成绩，不含失败
/recent [@用户]：最近一条成绩，包含失败
/bp [@用户] [序号或区间]：BP，默认第 1 条
/beatmap 谱面ID：谱面信息
/bind 用户名、/unbind：绑定与解绑
/mode 0～3：默认模式
资料卡和成绩命令末尾可加 :0～:3。
0 osu! · 1 taiko · 2 catch · 3 mania
例如 /statme:3、/bp 1-10:3"""


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
        """Mint osu!：stat、statme、pr、recent、bp、beatmap、bind、unbind、mode、minthelp。"""
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
            result = await self._client.request(build_request(command, caller, theme))
            if isinstance(result, bytes):
                yield event.chain_result([Image.fromBytes(result)])
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
