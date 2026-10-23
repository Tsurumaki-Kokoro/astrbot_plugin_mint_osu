# Mint osu!

通过 MintAPI 查询 osu! 玩家资料卡、成绩与谱面。先验证 QQ OneBot，使用 AstrBot 消息组件兼容其他平台。

## 安装与配置

将插件安装到 AstrBot 的 `data/plugins/astrbot_plugin_mint_osu`，在插件配置中填写：

- `api_base_url`：MintAPI 地址，默认 `http://127.0.0.1:5251`。
- `api_token`：MintAPI 的 `ApiKey`；插件使用 `access_token` 请求头。
- `theme`：`default` 或 `yaowan`；BP 列表与谱面使用 `default`。
- `request_timeout`：超时秒数，默认 90。
- `max_concurrency`：同时请求上限，默认 2。
- `subscription_poll_interval`：比赛订阅检查间隔，默认 30 秒。
- `subscription_max_per_session`：每会话比赛订阅上限，默认 3 场。

保存后重载插件。容器里的 localhost 指向容器自身，请使用 AstrBot 能访问的 MintAPI 地址。
需要包含本轮 `/user_info` 直接用户名查询改动的 MintAPI；旧版本会要求调用者先绑定。

## 命令

附加参数统一使用单字母短参数：`-p` 页码、`-c` 游标、`-m` Mods、`-f` 格式、`-s` 起点、`-d` 时长、`-a` 评分算法、`-t` 队伍类型。视频预览使用 `/previewv`。

| 命令 | 说明 |
| --- | --- |
| `/stat 用户名 [#天数]` | 指定 osu! 玩家资料卡，用户名支持空格，无需调用者绑定 |
| `/stat @用户 [#天数]` | 查询被提及用户在当前平台绑定的玩家 |
| `/statme [#天数]` | 调用者自己的资料卡；未绑定时提示绑定 |
| `/pr [@用户]` | 最近一条成绩，不包含失败 |
| `/recent [@用户]` | 最近一条成绩，包含失败 |
| `/bp [@用户] [序号或区间]` | 默认 BP1；例如 `/bp 3`、`/bp @用户 1-10` |
| `/nb [@用户] [#天数]` | 新增 BP，默认 1 天，例如 `/nb #7:3` |
| `/weekly [@用户] [-w YYYY-MM-DD][:模式]` | 上一完整周周报，可指定已结束周的周一 |
| `/compare [@用户] 谱面ID [-m HD,HR] [-l stable或lazer][:模式]` | 自己与被 @ 玩家对比；也可 `/compare 谱面ID 用户名` |
| `/compare 谱面ID 用户A 用户B` | 两名 osu! 玩家的同图成绩，空格用户名加引号 |
| `/bpwatch [用户名或@用户][:模式]` | 在当前群订阅新 BP、排名/总 PP 里程碑；省略玩家为自己 |
| `/bpwatch list [-p 2]` | 查询当前群所有玩家动态订阅 |
| `/bpwatch stop [用户名或@用户][:模式]` | 取消当前群该玩家订阅，省略玩家为自己，省略模式为全部模式 |
| `/bpwatch stopall` | 取消当前群全部玩家动态订阅 |
| `/fix [@用户]` | BP 补 FC 分析图 |
| `/analyze [@用户]` | BP 成绩分析图 |
| `/history [@用户] [#天数]` | PP/排名趋势，默认 30 天，例如 `/history #90:3` |
| `/score [@用户] 谱面ID` | 指定谱面的个人成绩 |
| `/scorehistory [@用户] 谱面ID [-m HD,HR] [-p 2]` | 谱面成绩历史，默认每页 20 条 |
| `/beatmap 谱面ID` | 谱面信息 |
| `/search 关键词 [-p 2] [-c 游标]` | 谱面搜索图片，末尾 `:0～:3` 筛选模式，省略为全部模式 |
| `/preview 谱面ID [-m HD,DT] [-f png]` | 默认自动选取片段的 GIF；可选择 PNG |
| `/bpm 谱面ID` | BPM 时间轴 |
| `/cover 谱面ID` | 谱面封面 |
| `/beatmapset 谱面集ID` | 谱面集信息 |
| `/bind 用户名` | 绑定自己；已绑定需先解绑 |
| `/unbind` | 解除自己的绑定 |
| `/mode 0～3` | 修改自己的默认模式，也支持 osu、taiko、catch、mania |
| `/minthelp` | 命令帮助 |

资料卡、pr、recent、bp 的末尾可添加模式：`:0` osu!、`:1` taiko、`:2` catch、`:3` mania。
nb、fix、analyze、history、score、scorehistory 同样支持末尾模式，不写 @用户 时查询自己。
资料卡默认与当日凌晨快照对比，也可使用 `/statme #7`、`/stat Player Name #7:3`、`/stat @用户 #7:3` 指定历史对比；`#0` 等同默认。天数超出可检索范围时使用该玩家对应模式最早可用快照，图片显示实际对比天数；没有快照则不显示对比。

天数必须用 `#数字`，nb 为 1～365 天，history 为 1～3650 天，不接受裸数字天数。
例如 `/nb @用户 #7:3`、`/scorehistory @用户 123456 -m HD,HR -p 2:0`。
history 和 scorehistory 显式请求 PNG，保留服务端历史来源与提示；fix、analyze、nb 使用默认分析主题。
analyze 的临时模式需要更新包含 `performance_analyze?game_mode=` 支持的 MintAPI。
例如 `/statme:3`、`/stat Player Name:1`、`/pr @用户:3`、`/bp 1-10:3`。
周报省略模式时使用对象绑定模式；同图对比和新建玩家订阅省略模式时为 Standard（0），取消玩家订阅省略模式为该玩家所有模式。其他命令省略模式时使用查询对象绑定的默认模式；`stat 用户名` 使用调用者默认模式，未绑定则使用 0。
pr/recent 仅查询最近一条，不接受序号或区间；BP 序号为 1～100，区间最多 20 条。
`@用户` 必须使用平台真正的提及操作；文本里的昵称不会被当作平台用户 ID。

## 平台身份与媒体

- QQ OneBot 使用 `(qq, QQ号码)`，可以复用 MintAPI 已有 QQ 绑定。
- QQ 官方机器人使用 `(qq_official:适配器ID, 平台用户ID)`，与 QQ 号码绑定分开。保持适配器 ID 稳定。
- Discord、Telegram、Slack 使用平台名称和发送者 ID；其他适配器采用带适配器 ID 的独立命名空间。
- 当前 Telegram 适配器的普通提及只提供用户名，无法可靠对应数字用户 ID，会提示改用 `/stat osu!用户名`。
- 其他平台的 @查询需要适配器提供真实用户 ID；QQ 官方机器人以实际消息载荷提供的提及信息为准。

图片先由插件携带密钥下载，再发送为 AstrBot 图片组件；不会把需要鉴权的接口 URL 交给消息平台。
插件不重复保存绑定，不自动重试写操作；接口繁忙时提示等待时间。

## 开发验证

在已安装 AstrBot 和 aiohttp 的 Python 环境运行：

```sh
python -m unittest discover -s tests -v
```

测试覆盖解析、身份、HTTP 契约和实际 AstrBot 消息组件。真实平台验证仍需启动 MintAPI，并在 QQ 私聊、群聊发送命令。
实时比赛订阅见下方 `/mpwatch` 用法。

### 搜索与预览

例如 `/search Blue Zenith -p 2:0`、`/preview 123456 -m HD,DT -f png`。
搜索每张图片最多显示 5 个谱面集。`-p` 为当前官方批次内的图片页，不是官方搜索游标。
回复附带本批页数、总数和下一批游标；读取下一批时保持关键词与模式，使用 `-p 1 -c 游标`。
搜索表达式支持空格及 `artist:...` 等官方语法，末尾 `:0～:3` 保留为插件模式后缀。
这些指令无需绑定账号，谱面 ID 与谱面集 ID 分别用于 `/beatmap` 和 `/beatmapset`。
GIF 生成可能较慢，可在配置中增加请求超时。平台能否显示动图取决于其图片消息支持。

## 参考

- [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)

## QQ 官方机器人私聊菜单

`qq_menu.json` 定义帮助、资料、成绩、分析、账号五个入口，只保留点击后参数完整且可用于私聊的命令。移除必须手动填写用户名、谱面 ID、PP、模式或比赛 ID 的入口，也移除群排名入口。前十 BP 按钮自带 `1-10`，可直接使用。账号绑定和其他参数命令通过 `/minthelp` 查看后手动输入。菜单仅用于 QQ 官方机器人 C2C 私聊，不适用于 OneBot 或群聊。

在 AstrBot 所在机器运行以下命令更新线上菜单（无需重启插件）：

```sh
python3 tools/update_qq_menu.py --config /path/to/AstrBot/data/cmd_config.json
```

存在多个启用的 QQ 官方适配器时，使用 `--platform-id` 指定目标。工具从 AstrBot 配置读取凭证，不在输出或菜单文件保存凭证；先读取并备份现有菜单到 AstrBot 的 `data/temp/qq-menu-backup-*.json`，再提交完整菜单并读取核验。QQ 返回的默认图标等附加字段不影响核验。更新会覆盖该机器人的全局菜单，影响所有私聊用户；接口限制为每分钟 5 次，不自动重试写操作。

协议参考：[修改全局自定义菜单](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_menu.put.html)。

## QQ 官方机器人指令面板

由于 QQ 面板上限为 20 条，`/stat`、`/unbind`、`/beatmapset`、`/search`、`/preview`、`/bpm`、`/cover`、`/mp`、`/rating`、`/mode`、`/oa`、`/scorehistory` 可手动输入或通过 `/minthelp` 查看；管理员指令 `/mintmenu`、`/mintpanel` 也不占面板位置。面板优先展示新增的 `/weekly`、`/compare`、`/bpwatch`。

`qq_panel.json` 包含 20 条常用指令；QQ 面板上限为 20 条，完整命令见 /minthelp。面板的 `name` 就是点击后填入输入框的指令，`desc` 展示参数提示；无需参数的指令可直接发送，其他指令需补全用户名、谱面 ID 或模式。

```sh
python3 tools/update_qq_panels.py --config /path/to/AstrBot/data/cmd_config.json
```

工具分别更新私聊（c2c）和群聊（group）的全局面板，不存在时创建。更新前备份到 `data/temp/qq-panels-backup-*.json`，更新后读取核验；已有的指定用户或指定群面板保留关联关系。多个全局面板无法确定目标时停止写入。与私聊底部菜单独立配置，无需重启 AstrBot。

协议参考：[创建指令面板](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_panels.post.html)。

## 比赛查询

- `/mp 比赛ID`：比赛历史图，默认第 1 页；`-p 2` 翻页，`-p 0` 返回全部已结束对局。
- `/rating 比赛ID`：玩家评分图，默认 osuplus 算法；`-a bathbot` 或 `-a flashlight` 切换算法。
- 两者均接受 `https://osu.ppy.sh/community/matches/123456` 或旧版 `https://osu.ppy.sh/mp/123456` 链接，无需绑定。
- 两者均支持 `-t head-to-head`、`-t team-vs`；mp 还支持 tag-coop、tag-team-vs，rating 不支持 Tag 评分。
- 混合比赛需指定队伍类型；翻页时保留 ID、算法和队伍类型，例如 `/rating 123456 -a bathbot -t team-vs -p 2`。
- 不接受 @用户 或模式后缀，模式由比赛决定。评分页码从 1 开始，图片回复附带页数。

这些用法接入现有 `/multiplayer/history` 和 `/multiplayer/rating`；指定算法属于 rating 的参数，并非第三条独立命令。实时订阅使用 `/mpwatch`。

## 名片、增加 PP、群排名与视频

- `/oa` 返回自己的名片；`/oa @用户` 仅允许一位提及对象，直接返回图片。
- `/oa peppy "Player One"` 按用户名逐个生成名片并发送 ZIP，无需绑定。每批最多 20 个用户名；部分失败会在 ZIP 中附上失败清单，全部失败直接提示。单个显式用户名也按列表形式发送 ZIP。
- `/pp 增加PP [@用户]` 使用目标用户的绑定模式，返回所需单曲 PP 和预计 BP 位置。
- `/rank:3` 和 `/top5` 自动获取当前群成员，分批调用 `/users/bindings` 筛出已绑定名单。rank 默认 osu! 模式 0；top5 展示四模式各前五。
- 平台不能提供完整群成员名单时提示不支持；QQ OneBot 可提供该名单，QQ 官方机器人以其适配器能力为准。当前已绑定名单超过 100 人会明确提示接口上限，不截断、不生成不完整榜单。
- `/previewv 谱面ID -m HD,DT -s preview -d 30` 返回 MP4，时长大于 0 且最多 60 秒，起点可以是 preview 或非负秒数。视频响应上限 80 MiB。
- ZIP 和视频使用临时文件，发送完成后交由 AstrBot 的事件临时文件机制清理；实际平台是否支持文件/视频消息需要实际验证。
- 使用群排行榜前需要更新包含 `POST /users/bindings` 的 MintAPI。背景上传暂不接入。


## 比赛订阅

- `/mpwatch 比赛ID或链接`：订阅当前会话；`/mpwatch list`：查看当前会话订阅。
- `/mpwatch stop 比赛ID或链接`、`/mpwatch stopall`：停止指定或全部订阅。群内修改需要群主、群管理员或机器人管理员权限；私聊管理自己的订阅。查看列表不要求管理员权限。
- 每个会话默认最多 3 场（可配置），重复订阅不会创建新记录。每轮检查完成后默认等待 30 秒（可配置），同一比赛共享查询，同一单局共享图片；MintAPI 上游刷新频率由其 MatchLive 配置决定。
- 仅推送订阅后结束且有成绩的单局图片，以及比赛关闭通知。玩家进出、选图、开局、中止的空成绩局不推送。比赛结束后自动停止，不自动生成评分；使用 `/rating` 查询。
- SQLite 保存会话、单局推送进度、远端订阅 ID 与游标，位于 AstrBot 插件数据目录 `subscriptions.sqlite3`。重启恢复；失败保留订阅并重试，远端租期或游标过期后重新订阅，通过完整的已结束单局名单补发遗漏。停止最后一个本地订阅后取消远端订阅；取消请求失败会在后台重试。
- 消息成功发送后才保存单局进度。正常轮询和恢复不会重复推送；若进程恰好在平台收件后、保存进度前退出，平台没有幂等发送接口时可能重复一条通知。
- 必须更新到提供 `snapshot.games` 的 MintAPI，复用 `/multiplayer/live/subscriptions`、增量更新和单局图片接口。实时 JSON 响应最多 8 MiB，错误响应仍限制 64 KiB。
- 当前 AstrBot QQ 官方适配器不支持会话主动推送，因此拒绝新建订阅；QQ OneBot 使用通用会话推送。其他平台需支持 AstrBot 的主动消息接口及群管理员查询。真实群消息发送仍需实机验证。

### QQ 管理员一键同步

AstrBot 机器人管理员在目标 QQ 官方机器人的私聊中发送 `/mintmenu` 更新私聊底部菜单，发送 `/mintpanel` 更新私聊和群聊指令面板。仅支持 QQ 官方适配器，群聊、OneBot 和其他平台不能执行。自动使用当前机器人的凭证，不需要额外配置机器人 ID。管理指令不占用公开菜单或面板位置。

更新前备份到插件数据目录的 `qq_backups/`，更新后读取核验并回复结果；部分成功时会列出已完成的操作。重复执行会被阻止到本次更新结束。原有 tools 命令行入口仍可使用。

后台新增 `subscription_poll_interval`（默认 30，范围 10～3600 秒）和 `subscription_max_per_session`（默认 3，范围 1～20 场）。保存配置并重载插件后生效；降低上限保留已有订阅。QQ 官方适配器仍不支持比赛订阅主动推送，QQ OneBot 可使用。

## 周报、同图对比与群玩家动态

- `/weekly` 查询自己上一完整自然周；`/weekly @用户 -w 2026-10-12:3` 查询指定玩家和模式。缺少历史快照时显示未知；历史周必须已结束。
- `/compare @用户 657917 -m HD,HR:0` 比较自己与该用户；`/compare 657917 "Player One" peppy -l stable` 直接比较两位 osu! 玩家，无需绑定。一个显式用户名时左侧使用自己的绑定。绑定 ID 通过已有排行榜 JSON 解析，不把 QQ 号作为 osu! ID。不同 Mods 设置或客户端由 MintAPI 标注并停用优胜高亮。
- `/bpwatch peppy:0` 在当前群订阅；`/bpwatch` 使用自己的绑定；`/bpwatch @用户:3` 使用对方绑定。`list` 查询服务器当前群订阅，`stop 用户名或osu!ID` 取消该玩家全部模式，`:模式` 可收窄，`stopall` 取消整群。增删需要群管理员或 AstrBot 管理员，list 无需管理员。

玩家订阅按平台和当前群隔离，禁止私聊、缺少群 ID 或不支持主动推送的适配器。QQ 官方适配器不支持 AstrBot 主动群推送，使用 `/bpwatch` 会明确提示；周报与成绩对比仍可正常查询。

插件使用 MintAPI 的 `/players/watch/subscriptions` 群查询/取消接口；本地 `player_subscriptions.sqlite3` 保存目标群会话、订阅 ID 和投递游标，首次静默建立基线。插件只主动投递本插件在该群创建并持久化的订阅；服务器其他调用方建立的订阅可查询/取消，但不会自动接管推送。

后台通过 JSON 增量事件读取服务器生成的纯文本，只在消息发送成功后推进对应游标；上游或平台发送失败保留记录重试，重载插件保留进度。分段长消息发生部分发送失败时可能重发已成功的部分。410（取消、过期或游标失效）停止本地订阅并通知群，不自动复活已取消订阅；需要时先 `/bpwatch stop osu!ID:模式` 清理远端旧订阅，再执行 `/bpwatch` 重新建立基线。停止一群订阅不影响其他群。

`player_subscription_poll_interval` 默认 30 秒（10～3600），`player_subscription_max_per_group` 默认 10 条（1～100，同玩家不同模式分别计数）。这是本插件每群的本地投递上限，不代替 MintAPI 的全局限制。MintAPI 默认约五分钟采集官方数据，插件轮询不会提高官方采集频率。修改配置后重载插件。

需要支持群管理、周报和同图对比的 MintAPI 版本；重载插件即可识别指令。QQ 面板配置已同步至 `qq_panel.json`，尚需管理员按既有 `/mintpanel` 流程发布才会更新平台端面板。
