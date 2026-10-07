"""Keep account identity separate from conversation identity."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    platform: str
    uid: str


def resolve_identity(adapter: str, platform_id: str, sender_id: str) -> Identity:
    if not sender_id:
        raise ValueError("当前消息没有可用的用户 ID。")
    adapter = adapter.lower()
    if adapter in {"aiocqhttp", "onebot", "onebot_v11", "qq"}:
        platform = "qq"
    elif adapter == "qq_official":
        # Official QQ IDs belong to an application, not to the QQ-number namespace.
        platform = f"qq_official:{platform_id}"
    elif adapter in {"discord", "telegram", "slack"}:
        platform = adapter
    else:
        platform = f"{adapter}:{platform_id}"
    return Identity(platform, str(sender_id))
