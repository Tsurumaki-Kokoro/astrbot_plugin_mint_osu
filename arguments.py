"""Parse Mint commands independently of AstrBot and preserve usernames with spaces."""
import re
import math
import shlex
from urllib.parse import urlsplit
from dataclasses import dataclass

COMMAND_PATTERN = re.compile(r"^/?(statme|stat|pr|recent|bp|beatmapset|beatmap|bind|unbind|mode|minthelp|nb|fix|analyze|history|scorehistory|score|search|preview|bpm|cover|mp|rating|oa|pp|previewvideo|rank|top5)(?=\s|:|#|$)", re.I)
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
    query: str | None = None
    cursor: str | None = None
    format: str = "gif"
    match_id: int | None = None
    algorithm: str = "osuplus"
    team_type: str | None = None
    usernames: tuple[str, ...] = ()
    pp: float | None = None
    start: str = "preview"
    duration: float = 30


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
    if target and name not in {"stat", "pr", "recent", "bp", "nb", "fix", "analyze", "history", "score", "scorehistory", "oa", "pp"}:
        raise ValueError("这个命令不支持 @用户。")
    if name == "oa":
        names = shlex.split(tail)
        if target and names:
            raise ValueError("oa 不能混用 @用户 和用户名列表。")
        if len(names) > 20 or any(not item.strip() or len(item) > 100 for item in names):
            raise ValueError("oa 每次最多 20 个用户名；含空格的用户名使用引号。")
        return Command(name, target_uid=target, usernames=tuple(dict.fromkeys(names)))
    if name == "pp":
        try:
            value = float(tail)
        except ValueError:
            raise ValueError("请使用 /pp 增加PP值 [@用户]。")
        if not math.isfinite(value) or value <= 0:
            raise ValueError("增加 PP 必须是有限的正数。")
        return Command(name, target_uid=target, pp=value)
    if name == "top5":
        if tail:
            raise ValueError("top5 自动查询当前群的已绑定成员，不接受用户列表或模式。")
        return Command(name)
    if name in {"mp", "rating"}:
        tokens = shlex.split(tail)
        if not tokens:
            raise ValueError(f"请使用 /{name} 比赛ID或osu!比赛链接。")
        value = tokens.pop(0)
        if not re.fullmatch(r"[0-9]+", value):
            url = urlsplit(value)
            path = re.fullmatch(r"/(?:community/matches|mp)/([0-9]+)/?", url.path)
            if url.scheme not in {"http", "https"} or url.netloc.lower() != "osu.ppy.sh" or not path:
                raise ValueError("请提供比赛 ID 或 https://osu.ppy.sh/community/matches/比赛ID 链接。")
            value = path[1]
        match_id = int(value)
        if not 1 <= match_id <= 2147483647:
            raise ValueError("比赛 ID 必须为正整数且不超过 2147483647。")
        page, algorithm, team_type, seen = 1, "osuplus", None, set()
        while tokens:
            flag = tokens.pop(0)
            allowed = {"--page", "--team-type"} | ({"--algorithm"} if name == "rating" else set())
            if flag not in allowed or flag in seen or not tokens:
                raise ValueError("使用 --page 页码、--team-type 队伍类型；rating 还支持 --algorithm 算法。")
            seen.add(flag)
            value = tokens.pop(0).lower()
            if flag == "--page":
                minimum = 0 if name == "mp" else 1
                if not re.fullmatch(r"[0-9]+", value) or not minimum <= int(value) <= 1000000:
                    raise ValueError(f"页码必须为 {minimum}～1000000。")
                page = int(value)
            elif flag == "--algorithm":
                if value not in {"osuplus", "bathbot", "flashlight"}:
                    raise ValueError("评分算法必须为 osuplus、bathbot 或 flashlight。")
                algorithm = value
            else:
                types = {"head-to-head", "team-vs"} | ({"tag-coop", "tag-team-vs"} if name == "mp" else set())
                if value not in types:
                    raise ValueError("评分仅支持 head-to-head、team-vs；比赛历史还支持 tag-coop、tag-team-vs。")
                team_type = value
        return Command(name, match_id=match_id, page=page, algorithm=algorithm, team_type=team_type)

    mode = None
    if name in {"stat", "statme", "pr", "recent", "bp", "nb", "fix", "analyze", "history", "score", "scorehistory", "search", "rank"}:
        suffix = re.search(r":\s*([+-]?\d+)\s*$", tail)
        if suffix:
            mode = int(suffix[1])
            if mode not in range(4):
                raise ValueError("模式必须是 :0、:1、:2 或 :3。")
            tail = tail[:suffix.start()].strip()
        elif ":" in tail and name != "search":
            raise ValueError("模式请放在末尾，使用 :0～:3。")
    if name == "rank":
        if tail:
            raise ValueError("请使用 /rank 或 /rank:0～:3。")
        return Command(name, mode=mode if mode is not None else 0)
    if name == "search":
        shlex.split(tail)  # Reject unmatched quotes, preserve official query syntax below.
        tokens = re.findall(r"""(?:[^\s"']+|"[^"]*"|'[^']*')+""", tail)
        words, seen, page, cursor = [], set(), 1, None
        while tokens:
            token = tokens.pop(0)
            if token in {"--page", "--cursor"}:
                if token in seen or not tokens:
                    raise ValueError("搜索参数使用 --page 2 或 --cursor 游标，不能重复。")
                seen.add(token)
                value = shlex.split(tokens.pop(0))[0]
                if token == "--page":
                    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 100:
                        raise ValueError("搜索图片页码必须为 1～100。")
                    page = int(value)
                else:
                    if not value.strip() or len(value) > 4096:
                        raise ValueError("搜索游标必须为 1～4096 字符。")
                    cursor = value
            elif token.startswith("--"):
                raise ValueError("搜索只支持 --page 和 --cursor。")
            else:
                words.append(token)
        query = ' '.join(words)
        if not 1 <= len(query) <= 500:
            raise ValueError("请使用 /search 关键词，关键词长度为 1～500 字符。")
        return Command(name, mode, query=query, page=page, cursor=cursor)
    if name in {"preview", "previewvideo"}:
        tokens = shlex.split(tail)
        if not tokens or not re.fullmatch(r"[0-9]+", tokens[0]) or not 0 < int(tokens[0]) <= 2147483647:
            raise ValueError("请使用 /preview 谱面ID [--mods HD,DT] [--format gif或png]。")
        map_id = int(tokens.pop(0))
        mods, format, seen, start, duration = None, "gif", set(), "preview", 30.0
        while tokens:
            flag = tokens.pop(0)
            allowed = {"--mods", "--start", "--duration"} if name == "previewvideo" else {"--mods", "--format"}
            if flag not in allowed or flag in seen or not tokens:
                raise ValueError("预览支持 --mods HD,DT 和 --format gif或png。")
            seen.add(flag)
            value = tokens.pop(0).upper()
            if flag in {"--start", "--duration"}:
                if flag == "--start" and value == "PREVIEW":
                    start = "preview"
                    continue
                try:
                    number = float(value)
                except ValueError:
                    raise ValueError("视频起点为 preview 或非负秒数，时长为 0～60 秒。")
                if not math.isfinite(number) or (flag == "--start" and number < 0) or (flag == "--duration" and not 0 < number <= 60):
                    raise ValueError("视频起点必须非负，时长必须大于 0 且不超过 60 秒。")
                if flag == "--start":
                    start = str(number)
                else:
                    duration = number
            elif flag == "--format":
                if value not in {"GIF", "PNG"}:
                    raise ValueError("预览格式必须为 gif 或 png。")
                format = value.lower()
            else:
                items = value.split(',')
                if any(not re.fullmatch(r"[A-Z0-9]{2,4}", item) for item in items) or ("NM" in items and len(items) != 1):
                    raise ValueError("Mods 使用逗号分隔的缩写；NM 必须单独使用。")
                mods = ','.join(dict.fromkeys(items))
        return Command(name, beatmap_id=map_id, mods=mods, format=format, start=start, duration=duration)
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
    if name in {"beatmap", "beatmapset", "bpm", "cover"}:
        if not re.fullmatch(r"[0-9]+", tail) or not 0 < int(tail) <= 2147483647:
            raise ValueError(f"请使用 /{name} {'谱面集ID' if name == 'beatmapset' else '谱面ID'}，ID 必须为正整数。")
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
