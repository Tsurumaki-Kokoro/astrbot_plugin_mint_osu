"""Parse Mint commands independently of AstrBot and preserve usernames with spaces."""
import re
import math
import shlex
from urllib.parse import urlsplit
from dataclasses import dataclass

COMMAND_PATTERN = re.compile(r"^/?(statme|stat|pr|recent|bp|beatmapset|beatmap|bind|unbind|mode|minthelp|nb|fix|analyze|history|scorehistory|score|search|preview|bpm|cover|mp|rating|oa|pp|previewv|rank|top5|mpwatch|weekly|compare|bpwatch|mintmenu|mintpanel)(?=\s|:|#|$)", re.I)
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
    action: str = "subscribe"
    week_start: str | None = None
    legacy_only: bool | None = None


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
    if target and name not in {"stat", "pr", "recent", "bp", "nb", "fix", "analyze", "history", "score", "scorehistory", "oa", "pp", "weekly", "compare", "bpwatch"}:
        raise ValueError("这个命令不支持 @用户。")
    if name in {"mintmenu", "mintpanel"}:
        if tail:
            raise ValueError("管理指令不接受参数。")
        return Command(name)
    if name == "mpwatch":
        tokens = shlex.split(tail)
        if tokens == ["list"] or tokens == ["stopall"]:
            return Command(name, action=tokens[0])
        action = "subscribe"
        if tokens and tokens[0] == "stop":
            action = tokens.pop(0)
        if len(tokens) != 1:
            raise ValueError("使用 /mpwatch 比赛ID或链接、list、stop 比赛ID或链接、stopall。")
        match_command = parse_command("/mp " + shlex.quote(tokens[0]), [])
        return Command(name, match_id=match_command.match_id, action=action)
    if name in {"weekly", "compare", "bpwatch"}:
        mode = None
        suffix = re.search(r":\s*([+-]?\d+)\s*$", tail)
        if suffix:
            mode = int(suffix[1])
            if mode not in range(4):
                raise ValueError("模式必须是 :0～:3。")
            tail = tail[:suffix.start()].strip()
        tokens = shlex.split(tail)
        if name == "weekly":
            date = None
            if tokens:
                from datetime import date as Date
                if len(tokens) != 2 or tokens[0] != "-w":
                    raise ValueError("使用 /weekly [@用户] [-w 周一日期][:模式]。")
                try:
                    value = Date.fromisoformat(tokens[1])
                except ValueError:
                    raise ValueError("周报日期使用 YYYY-MM-DD 格式的周一。")
                if value.weekday() != 0 or value.year < 2000 or value.isoformat() != tokens[1]:
                    raise ValueError("周报日期必须是 2000 年之后的周一，格式 YYYY-MM-DD。")
                date = value.isoformat()
            return Command(name, mode, target_uid=target, week_start=date)
        if name == "bpwatch":
            action, page = "subscribe", 1
            if tokens and tokens[0].lower() in {"list", "stop", "stopall"}:
                action = tokens.pop(0).lower()
            if action == "list":
                if target or mode is not None:
                    raise ValueError("使用 /bpwatch list [-p 页码] 查看当前群的全部模式订阅。")
                if tokens:
                    if len(tokens) != 2 or tokens[0] != "-p" or not tokens[1].isascii() or not tokens[1].isdigit() or not 1 <= int(tokens[1]) <= 1000000:
                        raise ValueError("使用 /bpwatch list [-p 页码]。")
                    page = int(tokens[1])
                return Command(name, action=action, page=page)
            if action == "stopall":
                if tokens or target or mode is not None:
                    raise ValueError("/bpwatch stopall 不接受额外参数。")
                return Command(name, action=action)
            if len(tokens) > 1 or target and tokens or any(len(x) > 128 for x in tokens):
                raise ValueError("使用 /bpwatch [用户名或@用户][:模式]，空格用户名加引号；stop 取消订阅。")
            return Command(name, mode, username=tokens[0] if tokens else None, target_uid=target, action=action)
        if not tokens or not tokens[0].isascii() or not tokens[0].isdigit() or not 1 <= int(tokens[0]) <= 2147483647:
            raise ValueError("使用 /compare [@用户] 谱面ID，或 /compare 谱面ID 用户A 用户B。")
        map_id = int(tokens.pop(0))
        names, mods, legacy, seen = [], None, None, set()
        while tokens:
            token = tokens.pop(0)
            if token in {"-m", "-l"}:
                if token in seen or not tokens:
                    raise ValueError("对比支持 -m HD,HR 和 -l stable或lazer，不能重复。")
                seen.add(token)
                value = tokens.pop(0)
                if token == "-l":
                    if value.lower() not in {"stable", "lazer"}:
                        raise ValueError("客户端使用 -l stable 或 -l lazer。")
                    legacy = value.lower() == "stable"
                else:
                    items = value.upper().split(',')
                    if any(not re.fullmatch(r"[A-Z0-9]{2,4}", x) for x in items) or "NM" in items and len(items) != 1:
                        raise ValueError("Mods 使用逗号分隔缩写，NM 必须单独使用。")
                    mods = ','.join(dict.fromkeys(items))
            elif token.startswith('-'):
                raise ValueError("对比只支持 -m 和 -l。")
            else:
                names.append(token)
        if (target and names) or (not target and not 1 <= len(names) <= 2) or any(not x.strip() or len(x) > 128 for x in names):
            raise ValueError("使用 /compare @用户 谱面ID，或 /compare 谱面ID 用户名 [另一用户名]；空格用户名加引号。")
        return Command(name, mode, beatmap_id=map_id, target_uid=target, usernames=tuple(names), mods=mods, legacy_only=legacy)
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
            allowed = {"-p", "-t"} | ({"-a"} if name == "rating" else set())
            if flag not in allowed or flag in seen or not tokens:
                raise ValueError("使用 -p 页码、-t 队伍类型；rating 还支持 -a 算法。")
            seen.add(flag)
            value = tokens.pop(0).lower()
            if flag == "-p":
                minimum = 0 if name == "mp" else 1
                if not re.fullmatch(r"[0-9]+", value) or not minimum <= int(value) <= 1000000:
                    raise ValueError(f"页码必须为 {minimum}～1000000。")
                page = int(value)
            elif flag == "-a":
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
            if token in {"-p", "-c"}:
                if token in seen or not tokens:
                    raise ValueError("搜索参数使用 -p 2 或 -c 游标，不能重复。")
                seen.add(token)
                value = shlex.split(tokens.pop(0))[0]
                if token == "-p":
                    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 100:
                        raise ValueError("搜索图片页码必须为 1～100。")
                    page = int(value)
                else:
                    if not value.strip() or len(value) > 4096:
                        raise ValueError("搜索游标必须为 1～4096 字符。")
                    cursor = value
            elif token.startswith("-"):
                raise ValueError("搜索只支持 -p 和 -c。")
            else:
                words.append(token)
        query = ' '.join(words)
        if not 1 <= len(query) <= 500:
            raise ValueError("请使用 /search 关键词，关键词长度为 1～500 字符。")
        return Command(name, mode, query=query, page=page, cursor=cursor)
    if name in {"preview", "previewv"}:
        tokens = shlex.split(tail)
        if not tokens or not re.fullmatch(r"[0-9]+", tokens[0]) or not 0 < int(tokens[0]) <= 2147483647:
            raise ValueError("请使用 /preview 谱面ID [-m HD,DT] [-f gif或png]。")
        map_id = int(tokens.pop(0))
        mods, format, seen, start, duration = None, "gif", set(), "preview", 30.0
        while tokens:
            flag = tokens.pop(0)
            allowed = {"-m", "-s", "-d"} if name == "previewv" else {"-m", "-f"}
            if flag not in allowed or flag in seen or not tokens:
                raise ValueError("预览支持 -m HD,DT 和 -f gif或png。")
            seen.add(flag)
            value = tokens.pop(0).upper()
            if flag in {"-s", "-d"}:
                if flag == "-s" and value == "PREVIEW":
                    start = "preview"
                    continue
                try:
                    number = float(value)
                except ValueError:
                    raise ValueError("视频起点为 preview 或非负秒数，时长为 0～60 秒。")
                if not math.isfinite(number) or (flag == "-s" and number < 0) or (flag == "-d" and not 0 < number <= 60):
                    raise ValueError("视频起点必须非负，时长必须大于 0 且不超过 60 秒。")
                if flag == "-s":
                    start = str(number)
                else:
                    duration = number
            elif flag == "-f":
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
            if name != "scorehistory" or flag not in {"-m", "-p"} or flag in seen or not options:
                raise ValueError("scorehistory 支持 -m HD,HR 和 -p 2；score 只接受谱面ID。")
            seen.add(flag)
            value = options.pop(0)
            if flag == "-p":
                if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 1000000:
                    raise ValueError("页码必须为 1～1000000。")
                page = int(value)
            else:
                items = value.upper().split(',')
                if any(not re.fullmatch(r"[A-Z0-9]{2,4}", item) for item in items) or ("NM" in items and len(items) != 1):
                    raise ValueError("Mods 使用逗号分隔的缩写，例如 HD,HR；NM 必须单独使用。")
                mods = ','.join(dict.fromkeys(items))
        return Command(name, mode, beatmap_id=int(tokens[0]), target_uid=target, mods=mods, page=page)
    if name in {"stat", "statme"}:
        days = None
        comparison = re.search(r"(?:^|\s)#\s*([0-9]+)$", tail)
        if comparison:
            digits = comparison[1].lstrip("0") or "0"
            days = min(int(digits), 2147483647) if len(digits) <= 10 else 2147483647
            tail = tail[:comparison.start()].strip()
        if "#" in tail:
            raise ValueError("对比天数请放在末尾，使用 #非负整数，例如 /statme #7:3。")
        if name == "statme":
            if tail:
                raise ValueError("请使用 /statme [#天数][:模式] 查询自己。")
            return Command(name, mode, days=days)
        if target and tail:
            raise ValueError("用户名和 @用户只能选择一个。")
        if not target and not tail:
            raise ValueError("请使用 /stat 用户名、/stat @用户，或 /statme 查询自己。")
        return Command(name, mode, username=tail or None, target_uid=target, days=days)
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
