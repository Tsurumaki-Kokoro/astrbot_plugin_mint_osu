# Mint osu!

AstrBot 的 osu! 查询插件，提供玩家资料、成绩、谱面预览、比赛查询与群订阅。需要可访问的 [MintAPI](https://github.com/Tsurumaki-Kokoro/MintAPI) 服务。

## 安装与配置

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

## 命令

短参数：`-p` 页码、`-c` 游标、`-m` Mods、`-f` 图片格式、`-s` 视频起点、`-d` 视频时长、`-a` 评分算法、`-t` 队伍类型、`-w` 周报起始日期、`-l` 成绩客户端。

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
| `/minthelp` | 指令帮助海报，接口不可用时回退文字帮助 |


### 模式、用户与历史

- 命令末尾使用 `:0` osu!、`:1` taiko、`:2` catch、`:3` mania，例如 `/statme:3`、`/bp 1-10:3`、`/nb @用户 #7:3`。
- 资料、成绩、分析、历史和周报省略模式时使用查询对象的绑定模式。`/stat 用户名` 使用调用者的默认模式，调用者未绑定时为 0。同图对比、新建玩家订阅与 `/rank` 默认模式为 0；取消玩家订阅省略模式时取消该玩家全部模式。
- 不写 `@用户` 的个人查询默认查询自己；请使用平台真正的提及操作。`/stat 用户名` 无需绑定，用户名可以含空格；`/compare`、`/oa`、`/bpwatch` 中含空格的用户名需加引号。
- 资料卡默认对比当日凌晨快照；`#7` 指定历史天数，`#0` 等同默认。超出历史范围时使用最早可用快照并显示实际天数，没有快照则不显示对比。
- 天数使用 `#数字`，`nb` 支持 1～365 天，`history` 支持 1～3650 天。历史缺失表示未知，不代表玩家没有游玩。
- pr/recent 仅查询最近一条，不接受序号。BP 序号为 1～100，区间最多 20 条。

### 搜索与媒体

- `/search Blue Zenith -p 2:0`：每张图片最多 5 个谱面集。`-p` 是当前批次的图片页；下一批使用回复中的游标，例如 `/search Blue Zenith -p 1 -c 游标:0`，保持关键词与模式不变。支持 `artist:...` 等搜索语法。
- `/preview 123456 -m HD,DT` 默认生成 GIF；`-f png` 改为静态图。生成较慢时可提高请求超时，动图显示取决于平台。
- `/previewv 123456 -m HD,DT -s preview -d 30` 返回 MP4；起点为 preview 或非负秒数，时长大于 0 且不超过 60 秒，视频上限 80 MiB。
- `/oa`、`/oa @用户` 返回单张名片；`/oa peppy "Player One"` 按用户名返回 ZIP，最多 20 人。即使只有一个显式用户名也返回 ZIP；部分失败时附失败清单。
- `/pp 100 [@用户]` 查询增加指定 PP 所需的单曲 PP 与预计 BP 位置，使用目标绑定模式。
- `/rank:3` 查询当前群已绑定成员榜单，`/top5` 展示四模式各前五。平台必须能提供完整成员名单；已绑定成员超过 100 人时无法生成榜单。
- 谱面查询、搜索、预览及显式用户名名片无需绑定。ZIP、视频和动图是否可用取决于平台消息能力。

### 比赛查询与订阅

- `/mp 比赛ID [-p 2] [-t team-vs]`：历史图，默认第一页，`-p 0` 返回全部已结束对局。
- `/rating 比赛ID [-a bathbot] [-p 2] [-t team-vs]`：评分图，默认 osuplus，可选 bathbot、flashlight，页码从 1 开始。
- 两者均接受 osu! 比赛链接，无需绑定，不接受 @用户 或模式后缀。混合比赛需指定队伍类型；支持 head-to-head、team-vs，mp 另支持 tag-coop、tag-team-vs。翻页时保留比赛 ID、算法和队伍类型。
- `/mpwatch 比赛ID或链接` 订阅当前会话，`/mpwatch list` 查看列表，`/mpwatch stop 比赛ID或链接` 停止一场，`/mpwatch stopall` 停止当前会话全部订阅。
- 群内修改比赛订阅需要群主、群管理员或 AstrBot 管理员权限；私聊管理自己的订阅。查看列表无需管理员权限。
- 仅推送订阅后结束且有成绩的单局与比赛关闭通知。比赛结束后自动停止；评分使用 `/rating` 查询。
- 重载或重启后恢复订阅，服务暂时不可用时保留订阅并重试。异常退出后可能重复一条已送达通知。

### 周报、对比与玩家动态

- `/weekly @用户 -w 2026-10-12:3` 查询指定周报，日期必须为已结束周的周一；历史快照不足时显示未知。
- `/compare @用户 657917 -m HD,HR:0` 与自己对比；`/compare 657917 "Player One" peppy -l stable` 直接比较两位玩家，无需绑定。只填一个用户名时与自己绑定的账号对比。客户端可选 stable、lazer；Mods 或客户端不一致时图片会标注并停用优胜高亮。
- `/bpwatch peppy:0` 订阅本群玩家新 BP、排名与总 PP 里程碑；省略玩家使用自己的绑定，也可使用 @用户。
- `/bpwatch list [-p 2]` 查看当前群所有订阅；`/bpwatch stop 用户名或osu!ID[:模式]` 取消指定玩家，`/bpwatch stopall` 取消当前群全部订阅。增删需要群管理员或 AstrBot 管理员，查看无需管理员。
- 玩家动态仅支持群聊，各群独立。新订阅从当前状态开始，不推送旧动态；重载后保留投递进度。插件仅推送由本插件在该群创建的订阅，其他调用方创建的订阅可查询、取消。
- 发送失败后重试，长消息部分发送成功时可能重复已发送部分。订阅取消、过期或失效时停止推送并通知群；需要恢复时先 `/bpwatch stop osu!ID:模式`，再重新订阅。

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
