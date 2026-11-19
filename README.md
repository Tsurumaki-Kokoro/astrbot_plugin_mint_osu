![AstrBot osu! 小薄绿](banner.png)

# osu! 小薄绿

AstrBot 的 osu! 查询插件，提供玩家资料、成绩、谱面预览、比赛查询与群订阅。需要可访问的 [MintAPI](https://github.com/Tsurumaki-Kokoro/MintAPI) 服务。

## 安装与配置

需要 AstrBot **4.28.0 或更高版本**。声明支持 LLBot（通过 OneBot v11 / `aiocqhttp` 接入）、QQ 官方机器人（`qq_official`）和 Discord（`discord`）。

在 AstrBot 插件管理中使用仓库地址安装：

```text
https://github.com/Tsurumaki-Kokoro/astrbot_plugin_mint_osu
```

也可将仓库放入 `data/plugins/astrbot_plugin_mint_osu`，在 AstrBot 的 Python 环境安装 `requirements.txt` 后重载插件。

先按照 [MintAPI 部署与配置文档](https://github.com/Tsurumaki-Kokoro/MintAPI#readme) 部署服务，再在插件配置中填写服务地址和密钥，保存后重载插件：

| 配置 | 默认值 | 用途与范围 |
| --- | --- | --- |
| `api_base_url` | `http://127.0.0.1:5251` | AstrBot 可访问的 MintAPI 地址；容器内 localhost 指向容器自身 |
| `api_token` | 空 | 填写 MintAPI 的 `ApiKey` |
| `command_prefixes` | `["/"]` | 命令前缀列表，例如 `["/", "!", "！"]`；全角和半角分别配置，不允许空前缀 |
| `follow_astrbot_wake` | `true` | 经 AstrBot 唤醒后允许裸命令；私聊是否需要唤醒由 AstrBot 控制 |
| `theme` | `default` | 资料卡与单条成绩主题，可选 `yaowan`；BP 列表、谱面与分析图使用默认主题 |
| `request_timeout` | 90 | 请求超时，1～300 秒 |
| `max_concurrency` | 2 | 同时请求上限，1～10 |
| `subscription_poll_interval` | 30 | 每轮比赛检查结束后的等待时间，10～3600 秒 |
| `subscription_max_per_session` | 3 | 每会话比赛订阅上限，1～20 场 |
| `player_subscription_poll_interval` | 30 | 玩家动态检查间隔，10～3600 秒 |
| `player_subscription_max_per_group` | 10 | 本插件每群玩家动态订阅上限，1～100 条；不同模式分别计数 |

降低订阅上限不会取消已有订阅。玩家动态采集频率由 MintAPI 决定，缩短插件检查间隔不会提高采集频率。

MintAPI 需支持以下接口或参数；升级插件时请同时核对服务端：

- 用户名资料卡：`/user_info` 直接用户名查询；分析模式：`/user_info/extra/performance_analyze?game_mode=`。
- 群排行榜：`POST /users/bindings`。
- 比赛订阅：`/multiplayer/live/subscriptions`、增量更新、单局图片及 `snapshot.games`。
- 周报、同图对比、玩家动态：对应查询接口及 `/players/watch/subscriptions` 群查询、取消接口。
- 帮助海报：`GET /help/image`；不可用时 `/minthelp` 自动返回文字帮助。

## 命令指南

**快速开始** · `/bind 用户名` → `/statme` → `/bp`

发送 `/minthelp` 查看帮助海报。配置其他前缀后，海报会附一行说明，列出当前可用的命令前缀。海报不可用时，回复完整的文字帮助。

以下示例使用默认 `/` 前缀，方括号表示可选参数，实际输入时省略方括号。把 `command_prefixes` 设为 `["!", "！"]` 后，可直接发送 `!statme`、`！statme` 或 `!bp 1-10:3`。多个前缀优先匹配最长项，QQ 官方原生命令菜单和指令面板仍使用 `/`。

默认开启 `follow_astrbot_wake`。例如 AstrBot 唤醒词为“小薄绿”时，可发送“小薄绿 bp 1-10:3”或“小薄绿 /bp 1-10:3”，也可 @机器人后发送裸命令。普通群聊中的裸命令不会被接管，私聊遵循 AstrBot 的唤醒设置。关闭此选项后，请使用配置的命令前缀或 QQ 官方原生入口。

### 01 玩家与账号

| 命令 | 说明 |
| --- | --- |
| `/bind 用户名` · `/unbind` | 绑定或解绑自己的 osu! 账号。换绑前需先解绑 |
| `/mode 0～3` | 设置自己的默认模式，也支持 osu、taiko、catch、mania |
| `/stat 用户名 [#天数]` · `/stat @用户 [#天数]` | 查看指定玩家资料卡。直接输入用户名无需绑定，用户名可含空格 |
| `/statme [#天数]` | 查看自己的资料卡 |
| `/oa` · `/oa @用户` | 查看自己或被提及用户的名片 |
| `/oa 用户名 [更多用户名]` | 按用户名导出名片 ZIP，无需绑定，最多 20 人。例如 `/oa peppy "Player One"`。单个显式用户名也返回 ZIP，部分查询失败时附失败清单 |

资料卡默认对比当日凌晨快照。`#7` 指定历史天数，`#0` 等同默认。超出历史范围时使用最早可用快照并显示实际天数，没有快照时省略对比。

### 02 周报与对比

| 命令 | 说明 |
| --- | --- |
| `/weekly [@用户] [-w YYYY-MM-DD][:模式]` | 个人周报，默认上一完整周。指定日期须为已结束周的周一，例如 `/weekly @用户 -w 2026-10-12:3`。历史快照不足时显示未知 |
| `/compare @用户 谱面ID` · `/compare 谱面ID 用户名` | 与自己绑定的账号比较同一谱面的成绩 |
| `/compare 谱面ID 用户A 用户B` | 比较两名 osu! 玩家在同一谱面的成绩，无需绑定 |
| `/rank[:模式]` · `/top5` | 查询本群已绑定成员的单模式榜单或四模式各前五。例如 `/rank:3` 查询 mania 榜单 |

同图对比支持 `-m HD,HR`、`-l stable` 或 `-l lazer`，模式写在命令末尾。例如 `/compare @用户 657917 -m HD,HR:0` 或 `/compare 657917 "Player One" peppy -l stable`。Mods 或客户端不一致时，图片会标注差异并停用优胜高亮。

群排行榜需要平台提供完整成员名单。当前群已绑定成员超过 100 人时无法生成榜单。

### 03 成绩与 BP

| 命令 | 说明 |
| --- | --- |
| `/pr [@用户]` · `/recent [@用户]` | 各查最近一条成绩，不接受序号。`pr` 不含失败，`recent` 包含失败 |
| `/bp [@用户] [序号或区间]` | 查看 BP，默认第 1 条。序号为 1～100，区间最多 20 条，例如 `/bp 3` 或 `/bp @用户 1-10` |
| `/nb [@用户] [#天数]` | 查看新增 BP，默认 1 天，支持 1～365 天，例如 `/nb #7:3` |
| `/fix [@用户]` · `/analyze [@用户]` | 查看 BP 补 FC 分析图或 BP 成绩分析图 |
| `/pp 增加PP [@用户]` | 按目标玩家的绑定模式，计算所需的单曲 PP 和预计 BP 位置，例如 `/pp 100` |
| `/history [@用户] [#天数]` | 查看 PP 和排名趋势，默认 30 天，支持 1～3650 天，例如 `/history #90:3` |
| `/score [@用户] 谱面ID` | 查看指定谱面的个人成绩 |
| `/scorehistory [@用户] 谱面ID [-m HD,HR] [-p 2]` | 查看谱面成绩历史，默认每页 20 条 |

缺失的历史数据表示未知。

### 04 谱面工具

| 命令 | 说明 |
| --- | --- |
| `/beatmap 谱面ID` | 查看谱面信息 |
| `/beatmapset 谱面集ID` | 查看谱面集信息 |
| `/search 关键词 [-p 2] [-c 游标]` | 搜索谱面，每张图最多 5 个谱面集。支持 `artist:...` 等搜索语法，末尾加 `:0`～`:3` 筛选模式，省略时搜索全部模式 |
| `/preview 谱面ID [-m HD,DT] [-f png]` | 默认自动选取片段生成 GIF，使用 `-f png` 生成静态图 |
| `/previewv 谱面ID [-m HD,DT] [-s preview] [-d 30]` | 生成 MP4，起点为 `preview` 或非负秒数，时长大于 0 且不超过 60 秒，文件上限 80 MiB |
| `/bpm 谱面ID` · `/cover 谱面ID` | 查看 BPM 时间轴或谱面封面 |

`/search Blue Zenith -p 2:0` 查看当前批次的第二张图。翻到下一批时使用回复提供的游标，例如 `/search Blue Zenith -p 1 -c 游标:0`，并保留原关键词与模式。

谱面工具无需绑定。生成预览较慢时可提高请求超时，动图和视频的发送能力取决于平台。

### 05 比赛工具

| 命令 | 说明 |
| --- | --- |
| `/mp 比赛ID或链接 [-p 2] [-t team-vs] [--trim 2,1]` | 查看比赛历史，默认在一张图中展示查询范围内的全部对局 |
| `/rating 比赛ID或链接 [-a bathbot] [-p 2] [-t team-vs] [--trim 2,1]` | 查看比赛评分，默认 osuplus，可选 bathbot、flashlight。默认在一张图中展示全部有效玩家的评分 |
| `/mpwatch 比赛ID或链接` | 为当前会话订阅比赛动态 |
| `/mpwatch list` | 查看当前会话的比赛订阅 |
| `/mpwatch stop 比赛ID或链接` · `/mpwatch stopall` | 停止指定比赛或当前会话的全部比赛订阅 |

- 省略 `-p` 或传入 `-p 0` 时输出完整长图，使用 `-p 1`、`-p 2` 等正数查询指定页。
- `/mp` 和 `/rating` 接受 osu! 比赛链接，无需绑定，也不接受 @用户或模式后缀。混合比赛需用 `-t` 指定队伍类型，两者均支持 `head-to-head`、`team-vs`，`/mp` 另支持 `tag-coop`、`tag-team-vs`。翻页时保留比赛 ID、算法、队伍类型和裁剪参数。
- `--trim 2,1` 跳过开头两局和结尾一局，`2,0` 或 `0,1` 只裁一端。先应用队伍类型筛选，再按已结束且含成绩的对局计数。总比分、评分和分页按保留的对局重新计算，至少保留一局。
- 群内增删比赛订阅需要群主、群管理员或 AstrBot 管理员权限。私聊可管理自己的订阅，查看列表无需管理员权限。订阅上限与检查间隔见插件配置。
- 订阅后会推送已结束且有成绩的单局，以及比赛关闭通知。比赛结束后自动停止订阅，比赛评分可用 `/rating` 查询。
- 重载或重启后恢复订阅，服务暂时不可用时保留订阅并重试。异常退出后可能重复一条已送达通知。

### 06 玩家动态订阅

| 命令 | 说明 |
| --- | --- |
| `/bpwatch [用户名或@用户][:模式]` | 订阅本群玩家的新 BP、排名及总 PP 里程碑。省略玩家时使用自己的绑定，省略模式时订阅 Standard，例如 `/bpwatch peppy:0` |
| `/bpwatch list [-p 2]` | 查看本群的玩家动态订阅 |
| `/bpwatch stop [用户名、osu!ID 或 @用户][:模式]` | 取消指定玩家的订阅，省略玩家时使用自己的绑定，省略模式时取消该玩家的全部模式 |
| `/bpwatch stopall` | 取消本群的全部玩家动态订阅 |

- 玩家动态仅支持群聊，各群独立。增删订阅需要群管理员或 AstrBot 管理员权限，查看列表无需管理员权限。
- 新订阅从当前状态开始，重载后保留投递进度。插件只推送由本插件在该群创建的订阅，其他调用方创建的订阅仍可查询和取消。
- 发送失败后会重试，长消息部分发送成功时可能重复已发送部分。订阅取消、过期或失效时停止推送并通知群。需要恢复时先用 `/bpwatch stop osu!ID:模式` 清理原订阅，再重新订阅。

### 07 群内猜歌

发送 `/谱面猜歌` 观看谱面 GIF 并猜曲名，也可用 `/谱面猜歌 :3` 等写法指定模式。四种模式均发送隐藏时间段标签的 GIF，使用原速、无 Mods。两种玩法共用答题指令、5 分钟时限和当日去重，每群同时一局。

在 QQ OneBot 群发送 `/猜歌`。机器人从本群已绑定成员中随机选一人，再从其前 100 条 BP 中随机选一个谱面集。默认使用被抽中玩家的绑定模式，可用 `/猜歌 :3` 指定 Mania，或用 `:0`～`:2` 指定 Standard、Taiko、Catch。

MintAPI 需支持 `/score/best_play_beatmapsets`。谱面猜歌还需在 MintAPI 启用谱面预览引擎。音频猜歌需让 AstrBot 访问 `b.ppy.sh`，并在其 `PATH` 上提供 `ffmpeg` 供 OneBot 适配器转换语音。

- 音频发出后有 5 分钟作答。直接发原文或罗马字曲名即可抢答，首位确认答对的人获胜。答题无需绑定。
- 曲名匹配忽略大小写、全半角、多余空白和首尾装饰标点，并统一常见连字符和引号。拉丁字母标题至少含 8 个字母时，允许同一词内有一对相邻字母打反。数字、罗马数字、版本词和括号内的文字会参与比对。
- 使用 `/作答` 加曲名提交译名、简称或别名。答案未直接匹配时，模型可根据答案、官方曲名和曲师辅助判定。两种玩法都可在 AstrBot 的小薄绿插件配置中通过「猜歌判定模型」从已配置的聊天模型里选择，留空时使用当前会话的聊天模型。可关闭「猜歌模型辅助判定」。所有群共用 5 个模型判定名额，满载时可稍后重试，本地匹配仍会立即判定。
- `/猜歌提示` 依次给出曲师和曲名首字符。`/取消猜歌` 由开局者或 AstrBot 管理员使用。
- `/猜歌榜` 查看本群本周胜场和称号，`/猜歌榜 上周` 查看上一周。音频与谱面猜歌合榜，按北京时间周一零点分周，每局按结算时间归属。手动取消的局不参与排名。
- 「最佳搜狗」至少需要 3 局本地判对，按平均曲名匹配度排名。完整匹配任一官方曲名得满分，允许的相邻字母颠倒按曲名长度扣分。
- 正向称号包括「报起来吧！」「爽！这才叫音乐！」「直接王朝」「再来亿局」和「这也行！但确实准啊！」。反向称号包括「这也能空啊！」「先报了再说」「哦？哦？哦？」和「玩大哥，这个歌叫什么名字？」。错答相关称号只采用本局结束前有明确模型判定的显式作答。
- 每群同时一局。同一谱面集当天只出一次，以 AstrBot 所在环境的日期为准。插件重载会清空当前局和出题记录。

### 模式与参数速查

- 模式后缀为 `:0` osu!、`:1` taiko、`:2` catch、`:3` mania，例如 `/statme:3`、`/bp 1-10:3`、`/nb @用户 #7:3`。
- 支持模式后缀的资料、成绩、分析、历史和周报命令默认使用查询对象的绑定模式。`/stat 用户名` 使用调用者的默认模式，调用者未绑定时为 osu!。`/compare`、`/rank` 和新建玩家订阅默认使用 osu!。
- 个人查询省略 `@用户` 时默认查自己，显式指定用户名的用法见各命令。请使用平台的提及功能选择用户。`/compare`、`/oa` 和 `/bpwatch` 中含空格的用户名需加引号。
- 短参数包括 `-p` 页码、`-c` 游标、`-m` Mods、`-f` 图片格式、`-s` 视频起点、`-d` 视频时长、`-a` 评分算法、`-t` 队伍类型、`-w` 周报起始日期和 `-l` 成绩客户端。

## 平台支持与数据

QQ OneBot 使用 QQ 号码绑定；QQ 官方机器人绑定与 QQ 号码分开，适配器 ID 应保持稳定。Discord、Telegram、Slack 及其他适配器分别绑定，不能直接复用 QQ 绑定。

@查询需要平台提供真实用户 ID。Telegram 普通提及仅提供用户名时，请改用 `/stat osu!用户名`。QQ 官方机器人提及和群成员查询取决于适配器能力。

QQ 官方适配器当前不支持 AstrBot 主动推送，无法新建比赛或玩家动态订阅；周报与成绩对比可正常查询。QQ OneBot 可使用订阅，其他平台需支持主动消息接口与群管理员查询。跨平台图片、文件、视频和主动推送请在目标平台验证。

订阅数据保存在 AstrBot 插件数据目录的 `subscriptions.sqlite3` 和 `player_subscriptions.sqlite3`。迁移 AstrBot 时需一并备份并迁移该目录。

## QQ 官方机器人菜单与指令面板

AstrBot 管理员在目标 QQ 官方机器人的私聊中发送：

- `/mintmenu`：更新私聊底部菜单，仅适用于 C2C 私聊。
- `/mintpanel`：更新私聊和群聊指令面板。

菜单配置在 `qq_menu.json`，指令面板配置在 `qq_panel.json`。面板最多 20 条，完整命令使用 `/minthelp` 查看；有参数的指令需补全参数后发送。修改本地配置后需重新同步。

以下命令未放入面板，可手动输入：`/stat`、`/unbind`、`/beatmapset`、`/search`、`/preview`、`/bpm`、`/cover`、`/mp`、`/rating`、`/mode`、`/oa`、`/scorehistory`；管理命令 `/mintmenu`、`/mintpanel` 也需手动输入。

同步会覆盖该机器人的全局配置，影响所有对应用户。更新前备份至插件数据目录的 `qq_backups/`，更新后核验并报告结果；部分成功会列出已完成操作。管理命令仅支持 QQ 官方适配器私聊，无需重启 AstrBot。

也可在 AstrBot 所在机器通过命令行同步：

```sh
python3 tools/update_qq_menu.py --config /path/to/AstrBot/data/cmd_config.json
python3 tools/update_qq_panels.py --config /path/to/AstrBot/data/cmd_config.json
```

多个 QQ 官方适配器同时启用时加 `--platform-id 适配器ID`。命令行备份位于 AstrBot 的 `data/temp/qq-menu-backup-*.json` 或 `qq-panels-backup-*.json`。面板不存在时创建；无法确定目标全局面板时停止更新，已有指定用户、指定群面板的关联关系保留。菜单更新接口每分钟最多 5 次，写入失败不自动重试。

## 开发与发布检查

在 AstrBot 的 Python 环境中安装 `requirements.txt`，运行：

```sh
python -m unittest discover -s tests -v
```

测试覆盖命令解析、身份、HTTP 契约、订阅与 AstrBot 消息组件。发布前还需在连接 MintAPI 的目标平台检查私聊、群聊、@查询、媒体发送与主动推送；自动化测试不能代替这些平台检查。

修改命令时同步检查 `main.py` 的文字帮助、README、`qq_menu.json`、`qq_panel.json` 和相关测试；修改配置时同步 `_conf_schema.json`。发布版本应保持 `metadata.yaml` 与 `main.py` 注册版本一致，并确认包内不包含密钥、数据库、日志或本地备份。

开发参考：[AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)。

## 许可证

[GNU AGPL v3](LICENSE)。

![Counter](https://count.getloli.com/@mintosu?theme=original-new&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

## 调用统计与模型判定

重载插件后，在 AstrBot 4.29 管理面板左侧的「扩展功能」打开「小薄绿调用统计」。AstrBot 4.28 的入口位于侧栏的插件 WebUI 分组。

看板以北京时间展示指令排行、群调用占比、小时热力图、活跃群、P95 耗时和技术失败率。群调用占比以当前筛选范围内的群聊指令为分母。点击群排行中的群 ID 可查看单群，清空群 ID 可恢复全群范围。统计数据从功能启用时开始采集。

调用总览的「查询模型判定记录」会打开独立查询页，可查询最近 7 天已发起的猜歌模型请求，包括提交答案、标准曲名、判定结果、是否结算为答对、耗时、用量和估算费用。过期后清理逐条记录，保留按小时汇总所需的用量和结果。插件数据目录中的 `usage_stats.sqlite3` 保存这些统计。

费用按照内置的官方 API 单价估算，页面显示计价覆盖率。使用代理或自定义计费时，在插件配置的「模型用量估算自定义单价」里按 AstrBot 的供应商实例 ID 填写每百万 Token 的费率，例如：

```json
{
  "my-provider": {
    "currency": "CNY",
    "input": 1,
    "cached_input": 0.1,
    "output": 2
  }
}
```
