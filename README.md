# Mint osu!

通过 MintAPI 查询 osu! 玩家资料卡、成绩与谱面。先验证 QQ OneBot，使用 AstrBot 消息组件兼容其他平台。

## 安装与配置

将插件安装到 AstrBot 的 `data/plugins/astrbot_plugin_mint_osu`，在插件配置中填写：

- `api_base_url`：MintAPI 地址，默认 `http://127.0.0.1:5251`。
- `api_token`：MintAPI 的 `ApiKey`；插件使用 `access_token` 请求头。
- `theme`：`default` 或 `yaowan`；BP 列表与谱面使用 `default`。
- `request_timeout`：超时秒数，默认 90。
- `max_concurrency`：同时请求上限，默认 2。

保存后重载插件。容器里的 localhost 指向容器自身，请使用 AstrBot 能访问的 MintAPI 地址。
需要包含本轮 `/user_info` 直接用户名查询改动的 MintAPI；旧版本会要求调用者先绑定。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/stat 用户名` | 指定 osu! 玩家资料卡，用户名支持空格，无需调用者绑定 |
| `/stat @用户` | 查询被提及用户在当前平台绑定的玩家 |
| `/statme` | 调用者自己的资料卡；未绑定时提示绑定 |
| `/pr [@用户]` | 最近一条成绩，不包含失败 |
| `/recent [@用户]` | 最近一条成绩，包含失败 |
| `/bp [@用户] [序号或区间]` | 默认 BP1；例如 `/bp 3`、`/bp @用户 1-10` |
| `/nb [@用户] [#天数]` | 新增 BP，默认 1 天，例如 `/nb #7:3` |
| `/fix [@用户]` | BP 补 FC 分析图 |
| `/analyze [@用户]` | BP 成绩分析图 |
| `/history [@用户] [#天数]` | PP/排名趋势，默认 30 天，例如 `/history #90:3` |
| `/score [@用户] 谱面ID` | 指定谱面的个人成绩 |
| `/scorehistory [@用户] 谱面ID [--mods HD,HR] [--page 2]` | 谱面成绩历史，默认每页 20 条 |
| `/beatmap 谱面ID` | 谱面信息 |
| `/bind 用户名` | 绑定自己；已绑定需先解绑 |
| `/unbind` | 解除自己的绑定 |
| `/mode 0～3` | 修改自己的默认模式，也支持 osu、taiko、catch、mania |
| `/minthelp` | 命令帮助 |

资料卡、pr、recent、bp 的末尾可添加模式：`:0` osu!、`:1` taiko、`:2` catch、`:3` mania。
nb、fix、analyze、history、score、scorehistory 同样支持末尾模式，不写 @用户 时查询自己。
天数必须用 `#数字`，nb 为 1～365 天，history 为 1～3650 天，不接受裸数字天数。
例如 `/nb @用户 #7:3`、`/scorehistory @用户 123456 --mods HD,HR --page 2:0`。
history 和 scorehistory 显式请求 PNG，保留服务端历史来源与提示；fix、analyze、nb 使用默认分析主题。
analyze 的临时模式需要更新包含 `performance_analyze?game_mode=` 支持的 MintAPI。
例如 `/statme:3`、`/stat Player Name:1`、`/pr @用户:3`、`/bp 1-10:3`。
省略模式时使用查询对象绑定的默认模式；`stat 用户名` 使用调用者默认模式，未绑定则使用 0。
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
本轮不包含谱面预览、群排行榜或实时比赛订阅。

## 参考

- [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)
