# NapCat

NapCat 4.18.42 / OneBot v11 的 Python 封装。**207 个 API 方法、29 类事件**，参数与字段全部从 `napcat.mjs` 源码抽取，注释全中文。

## 两个核心模块

| 模块 | 职责 | 内容 |
| --- | --- | --- |
| `napcat.api` | 发消息、查数据、改群设置 | `QQBot` 类，207 个方法，511 个参数 |
| `napcat.events` | 收事件、解析、分发 | 28 个事件类 + 解析器 + 分发器 + WS 客户端 |

## 安装

```bash
pip install websockets aiohttp requests
git clone https://github.com/li200-200/NapCat.git
cd NapCat
```

本仓库不发布到 PyPI，直接 clone 使用。

## 前置：配置 NapCat

在 NapCat WebUI（默认 `http://127.0.0.1:6099`）里打开两个服务：

**HTTP 服务端**（发消息用）

```
地址  127.0.0.1
端口  3000
Token pydemo_token_2024
```

**WebSocket 服务端**（收事件用）

```
地址  127.0.0.1
端口  3001
Token pydemo_token_2024
上报自身消息  ✓
```

配置存在 `C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\config\onebot11_<QQ号>.json`。

> `reportSelfMessage` 只存在于 **websocketServers** 的 schema，`httpServers` 没有这个字段。所以收事件必须走 WS 服务端。

## 快速上手

```python
from napcat import QQBotEvents, PrivateMessageEvent

bot = QQBotEvents("ws://127.0.0.1:3001", "pydemo_token_2024",
                  "http://127.0.0.1:3000")


@bot.on_private_message
async def handler(event: PrivateMessageEvent):
    print(f"{event.user_id}: {event.plain_text}")
    if event.plain_text == "ping":
        bot.reply_private(event, "pong")     # 引用原消息回复


bot.run()
```

## API 模块

### 易语言风格的发送与撤回

`send_friend_msg` 对齐易语言原型：

```
.子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
.参数 好友QQ, 长整数型
.参数 发送内容, 文本型
.参数 Random, 长整数型, 参考 可空, 撤回消息用
.参数 Req, 整数型, 参考 可空, 撤回消息用
```

对应 Python：

```python
from napcat import QQBot, Ref

bot = QQBot("http://127.0.0.1:3000", "pydemo_token_2024")

random = Ref()
req = Ref()
t = bot.send_friend_msg(1544629526, "hello", random, req)
# t = '1794330243'  random.value = 651301545  req.value = 651301545

bot.recall_friend_msg(t, random.value, req.value)   # True
```

类型对应：

| 易语言 | Python |
| --- | --- |
| `文本型` | `str` |
| `长整数型` | `int` |
| `参考` | `Ref` 容器，方法写 `.value` |
| `可空` | `= None` |

### 撤回三元组的真实映射

`send_*_msg` 只返回 `message_id`。易语言要的 `(time, Random, Req)` 得从 `get_msg` 补：

| 易语言 | NapCat 字段 |
| --- | --- |
| `time`（返回值） | `time` |
| `Random` | `message_seq` |
| `Req` | `real_id` |

所以 `send_*_msg` 内部发完立刻调一次 `get_msg` 补齐，并维护 `(time, random, req) -> message_id` 和 `time -> message_id` 两张表。`recall*` 按 `显式 id -> 三元组 -> time -> random/req` 顺序解析出 `delete_msg` 需要的 `message_id`。

### 其他接口都是方法

```python
bot.get_login_info()                      # {'user_id': ..., 'nickname': ...}
bot.get_friend_list()
bot.get_group_list()
bot.get_stranger_info("1544629526")
bot.set_group_ban("856296858", "1544629526", 60)
bot.send_like("1544629526", 10)
bot.set_msg_emoji_like(message_id, 128077)
bot.send_poke("1544629526")
bot.delete_msg(message_id)
bot.get_status() / get_version_info() / can_send_image()
bot.call("任意action", **params)           # 只取 data
bot.call_raw("任意action", **params)       # 要完整 envelope
```

非 0 `retcode` 抛 `QQBotError`：

```python
try:
    bot.delete_msg(1)
except QQBotError as exc:
    print(exc)   # delete_msg 调用失败 (retcode=200)：Recall failed
```

## 事件模块

### 事件全景

**消息（4）** `PrivateMessageEvent` / `GroupMessageEvent` / `PrivateMessageSentEvent` / `GroupMessageSentEvent`

**元事件（2）** `MetaLifecycleEvent` / `MetaHeartbeatEvent`

**通知（19）**

| 事件 | 类名 | sub_type |
| --- | --- | --- |
| `friend_add` | `FriendAddNotice` | — |
| `friend_recall` | `FriendRecallNotice` | — |
| `group_recall` | `GroupRecallNotice` | — |
| `group_upload` | `GroupUploadNotice` | — |
| `group_admin` | `GroupAdminNotice` | `set` / `unset` |
| `group_decrease` | `GroupDecreaseNotice` | `leave` / `kick` / `kick_me` |
| `group_increase` | `GroupIncreaseNotice` | `approve` / `invite` |
| `group_ban` | `GroupBanNotice` | `ban` / `lift_ban` |
| `group_card` | `GroupCardNotice` | — |
| `essence` | `GroupEssenceNotice` | `add` / `delete` |
| `group_msg_emoji_like` | `GroupMsgEmojiLikeNotice` | — |
| `bot_offline` | `BotOfflineNotice` | — |
| `online_file_send` | `OnlineFileSendNotice` | — |
| `notify/poke` | `PokeNotify` | 戳一戳 |
| `notify/title` | `TitleNotify` | 荣誉变更 |
| `notify/gray_tip` | `GrayTipNotify` | 灰条消息 |
| `notify/group_name` | `GroupNameNotify` | 群名变更 |
| `notify/input_status` | `InputStatusNotify` | 正在输入 |
| `notify/profile_like` | `ProfileLikeNotify` | 名片点赞 |

**请求（2）** `FriendRequest` / `GroupRequest`（`add` / `invite`）

### 三种注册粒度

```python
@bot.dispatcher.on(GroupBanNotice)    # 1. 具体事件类（最精确）
@bot.on_notice("group_ban")           # 2. 事件族
@bot.on_request("friend")
@bot.on_meta("heartbeat")
@bot.on_any                           # 3. 全局兜底
```

分发顺序：**具体类 -> 事件族（带二级类型）-> 事件族（post_type）-> 全局兜底**。处理器可以是 `def` 或 `async def`；单个处理器抛异常会被记录，不影响其他处理器。

### 主动操作

```python
bot.reply_private(event, "文本", quote=True)   # 引用回复私聊
bot.reply_group(event, "文本", quote=True)     # 引用回复群聊
bot.recall(message_id)                         # 撤回
bot.call("任意action", **params)               # 直接调 OneBot API
```

## 示例

| 文件 | 说明 |
| --- | --- |
| `examples/demo_en.py` | API 模块：发送 + 撤回三元组 |
| `examples/demo_events.py` | 事件模块：全部事件监听（`--offline` 可离线自测） |
| `examples/private_reply_bot.py` | 两个模块结合：私聊自动回复机器人 |
| `examples/elang_private_bot.txt` | 易语言版（HTTP 上报模式，纯标准库） |
| `examples/napcat_demo.py` | 早期 WS 版本（规则写在 config.json） |
| `examples/legacy_qqbot.py` | 早期中文方法名版本 |

## 测试

```bash
python tests/test_qqbot_en.py              # API：8 组
python tests/test_qqbot_events.py          # 事件：11 组
python examples/demo_events.py --offline   # 离线喂 18 条假事件
```

## 重新生成

NapCat 升级后重跑（需要 `C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\napcat.mjs`）：

```bash
python tools/_extract.py         # napcat.mjs -> tools/_actions.json
python tools/_gen.py             # -> napcat/api.py
python tools/_extract_events.py  # napcat.mjs -> tools/_events.json
python tools/_gen_events.py      # -> napcat/events.py
python tests/test_qqbot_en.py
python tests/test_qqbot_events.py
```

### 抽取时的三个坑

1. **actionName 的枚举名不是类名。** `actionName = ne.DeleteMsg` 里 `DeleteMsg` 是枚举成员，真正的类是 `A_e`。必须按位置反查所在 class。

2. **payloadSchema 会继承。** `send_private_msg` 自己没有 schema，继承基类 `eb`；`send_poke` 只写了一个 `actionName`，schema 全来自 `f4`。必须沿 `extends` 链回溯。

3. **const 声明有链式形态。** 除了 `const S_e = l.Object({...})`，还有 `}), Kwe = l.Object({...})` 这种跟在别的声明后面的，正则要一并匹配。

## 易语言版说明

易语言标准库没有 WebSocket 客户端，所以用 NapCat 的 `httpClients`（HTTP 上报）模式：NapCat 主动 POST 事件到你的端口。

关键坑：**chunk 长度是字节数，中文 UTF-8 占 3 字节**。若先 `到文本()` 再按字符数比较长度，中文消息一定解析失败。所以 `取HTTP报文体` 全程用字节集，只有请求头和 chunk 长度行（纯 ASCII）才转文本。

详见 `examples/elang_private_bot.txt` 顶部注释。

## 目录结构

```
NapCat/
├── napcat/
│   ├── __init__.py      包入口
│   ├── api.py           207 个 API 方法（自动生成）
│   └── events.py        28 个事件类 + 解析 + 分发 + WS（自动生成）
├── examples/            6 个示例
├── tests/               4 个测试
├── tools/               抽取与生成脚本
│   ├── _extract.py          action + payload schema
│   ├── _extract_events.py   事件定义
│   ├── _gen.py              生成 api.py
│   ├── _gen_events.py       生成 events.py
│   ├── _actions.json        207 action / 511 参数
│   └── _events.json         29 事件变体
└── docs/                详细文档
```

## 已知限制

- 消息事件只提取 `text` 段，图片/语音等用 `[图片]` 这类占位符。
- `reportSelfMessage` 打开后自己发的消息也会上报，规则里要判 `user_id == self_id` 跳过，否则可能自激循环。
- NapCat 对自己发出的消息不产生 `group_msg_emoji_like` 这类 notice，需要其他真实用户操作才能触发。

## 协议参考

- [OneBot v11 标准](https://github.com/botuniverse/onebot-11)
- [NapCat 文档](https://napneko.github.io/)

## License

MIT
