"""Parse Mint commands independently of AstrBot and preserve usernames with spaces."""
import re
import shlex
from dataclasses import dataclass

COMMAND_PATTERN = re.compile(r"^/?(statme|stat|pr|recent|bp|beatmap|bind|unbind|mode|minthelp|nb|fix|analyze|history|scorehistory|score)(?=\s|:|#|$)", re.I)
MODE_NAMES = {"osu": 0, "std": 0, "standard": 0, "taiko": 1, "catch": 2, "ctb": 2, "fruits": 2, "mania": 3}


@dataclass(frozen=True)
class Command:
    name: str
    mode: int | None = None
    username: str | None = None
    first: int = 1
    last: int | None = None
    beatmap_id: int | None = None
    target_uid: str | None = None
    days: int | None = None
    mods: str | None = None
    page: int = 1


def parse_command(text: str, mentions: list[str]) -> Command:
    text = text.strip()
    match = COMMAND_PATTERN.match(text)
    if not match:
        raise ValueError("无法识别命令，请使用 /minthelp 查看帮助。")
    name = match[1].lower()
    tail = text[match.end():].strip()
    if len(set(mentions)) > 1:
        raise ValueError("一次只能查询一位 @用户。")
    target = mentions[0] if mentions else None
    if target and name not in {"stat", "pr", "recent", "bp", "nb", "fix", "analyze", "history", "score", "scorehistory"}:
        raise ValueError("这个命令不支持 @用户。")

    mode = None
    if name in {"stat", "statme", "pr", "recent", "bp", "nb", "fix", "analyze", "history", "score", "scorehistory"}:
        suffix = re.search(r":\s*([+-]?\d+)\s*$", tail)
        if suffix:
            mode = int(suffix[1])
            if mode not in range(4):
                raise ValueError("模式必须是 :0、:1、:2 或 :3。")
            tail = tail[:suffix.start()].strip()
        elif ":" in tail:
            raise ValueError("模式请放在末尾，使用 :0～:3。")
    if name in {"nb", "history"}:
        days = 1 if name == "nb" else 30
        if tail:
            if not re.fullmatch(r"#\s*[0-9]+", tail):
                raise ValueError("天数请使用 #数字，例如 /nb #7 或 /history #30。")
            days = int(tail[1:].strip())
        maximum = 365 if name == "nb" else 3650
        if not 1 <= days <= maximum:
            raise ValueError(f"天数必须为 1～{maximum}。")
        return Command(name, mode, target_uid=target, days=days)
    if name in {"score", "scorehistory"}:
        tokens = shlex.split(tail)
        if not tokens or not re.fullmatch(r"[0-9]+", tokens[0]) or not 0 < int(tokens[0]) <= 2147483647:
            raise ValueError(f"请使用 /{name} [@用户] 谱面ID，ID 必须为正整数。")
        mods, page = None, 1
        seen = set()
        options = tokens[1:]
        while options:
            flag = options.pop(0)
            if name != "scorehistory" or flag not in {"--mods", "--page"} or flag in seen or not options:
                raise ValueError("scorehistory 支持 --mods HD,HR 和 --page 2；score 只接受谱面ID。")
            seen.add(flag)
            value = options.pop(0)
            if flag == "--page":
                if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 1000000:
                    raise ValueError("页码必须为 1～1000000。")
                page = int(value)
            else:
                items = value.upper().split(',')
                if any(not re.fullmatch(r"[A-Z0-9]{2,4}", item) for item in items) or ("NM" in items and len(items) != 1):
                    raise ValueError("Mods 使用逗号分隔的缩写，例如 HD,HR；NM 必须单独使用。")
                mods = ','.join(dict.fromkeys(items))
        return Command(name, mode, beatmap_id=int(tokens[0]), target_uid=target, mods=mods, page=page)
    if name == "stat":
        if target and tail:
            raise ValueError("用户名和 @用户只能选择一个。")
        if not target and not tail:
            raise ValueError("请使用 /stat 用户名、/stat @用户，或 /statme 查询自己。")
        return Command(name, mode, username=tail or None, target_uid=target)
    if name == "bp":
        first, last = 1, None
        if tail:
            indices = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", tail)
            if not indices:
                raise ValueError("请使用 /bp 3 或 /bp @用户 1-10，末尾可加 :模式。")
            first = int(indices[1])
            last = int(indices[2]) if indices[2] else None
        if first not in range(1, 101) or (last is not None and not first <= last <= min(100, first + 19)):
            raise ValueError("BP 序号为 1～100，每次最多查询 20 条。")
        return Command(name, mode, first=first, last=last, target_uid=target)
    if name == "bind":
        if not tail:
            raise ValueError("请使用 /bind osu!用户名。")
        return Command(name, username=tail)
    if name == "beatmap":
        if not re.fullmatch(r"[0-9]+", tail) or not 0 < int(tail) <= 2147483647:
            raise ValueError("请使用 /beatmap 谱面ID，ID 必须为正整数。")
        return Command(name, beatmap_id=int(tail))
    if name == "mode":
        value = MODE_NAMES.get(tail.lower())
        if value is None and tail in {"0", "1", "2", "3"}:
            value = int(tail)
        if value is None:
            raise ValueError("请使用 /mode 0～3，或 osu、taiko、catch、mania。")
        return Command(name, mode=value)
    if tail:
        raise ValueError("pr 和 recent 只查询最近一条，不接受序号。" if name in {"pr", "recent"} else "这个命令不接受额外参数。")
    return Command(name, mode, target_uid=target)
