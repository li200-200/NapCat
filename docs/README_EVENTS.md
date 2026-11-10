# qqbot_events.py — NapCat 全部事件的中文封装

把 NapCat 4.18.42 上报的**全部 29 个事件变体**（40 个注册项）封装成 Python 数据类 + 分发器 + WebSocket 监听客户端。字段全部从 `napcat.mjs` 源码抽取，每个类、每个方法都有中文备注。

## 文件

| 文件 | 说明 |
| --- | --- |
| `qqbot_events.py` | 生成产物：事件类 + 解析器 + 分发器 + 监听客户端（919 行） |
| `demo_events.py` | 演示：注册全部事件处理器；`--offline` 可离线自测 |
| `test_qqbot_events.py` | 离线单测（11 组，不联网） |
| `_extract_events.py` | 从 napcat.mjs 抽取事件定义 |
| `_gen_events.py` | 由 `_events.json` 生成 `qqbot_events.py` |
| `_events.json` | 抽取结果（29 个事件变体） |

## 四层结构

```python
qqbot_events
├── segments_to_text()      消息段拍平工具
├── BaseEvent               公共基类（time / self_id / post_type）
├── 28 个事件数据类          PrivateMessageEvent、GroupBanNotice、PokeNotify ...
├── EventParser             原始 JSON -> 数据类，40 个注册项
├── EventDispatcher         装饰器注册式分发，支持同步/异步
└── QQBotEvents             WebSocket 监听 + HTTP 主动操作
```

## 事件全景（29 个变体）

### 消息类
| 事件 | 类名 | 触发 |
| --- | --- | --- |
| `message/private` | `PrivateMessageEvent` | 收到私聊 |
| `message/group` | `GroupMessageEvent` | 收到群聊 |
| `message_sent/private` | `PrivateMessageSentEvent` | 自己发的私聊 |
| `message_sent/group` | `GroupMessageSentEvent` | 自己发的群聊 |

### 元事件
| 事件 | 类名 | 说明 |
| --- | --- | --- |
| `meta_event/lifecycle` | `MetaLifecycleEvent` | `connect` / `enable` / `disable` |
| `meta_event/heartbeat` | `MetaHeartbeatEvent` | 定期心跳，含 `status.online` |

### 通知类（notice）
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

### 请求类（request）
| 事件 | 类名 | sub_type |
| --- | --- | --- |
| `friend` | `FriendRequest` | — |
| `group` | `GroupRequest` | `add` / `invite` |

## 用法

```python
from qqbot_events import QQBotEvents, PrivateMessageEvent, GroupBanNotice

bot = QQBotEvents("ws://127.0.0.1:3001", "pydemo_token_2024",
                  "http://127.0.0.1:3000")


@bot.on_private_message
async def handle_private(event: PrivateMessageEvent):
    print(f"{event.user_id}: {event.plain_text}")
    if event.plain_text == "ping":
        bot.reply_private(event, "pong")     # 引用回复原消息


@bot.dispatcher.on(GroupBanNotice)
async def handle_ban(event: GroupBanNotice):
    print(f"群 {event.group_id} 成员 {event.user_id} "
          f"{event.sub_type}，时长 {event.duration} 秒")


@bot.on_notice("group_increase")
async def handle_join(event):
    print(f"新人 {event.user_id} 加入群 {event.group_id}")


@bot.on_request("friend")
async def handle_friend_req(event):
    # 自动同意
    bot.call("set_friend_add_request", flag=event.flag, approve=True)


bot.run()      # 阻塞监听，Ctrl+C 退出
```

## 三种注册粒度

```python
@bot.dispatcher.on(GroupBanNotice)        # 1. 具体事件类（最精确）
@bot.on_notice("group_ban")               # 2. 事件族
@bot.on_request("friend")                 #    请求族
@bot.on_meta("heartbeat")                 #    元事件族
@bot.on_any                               # 3. 全局兜底（调试用）
```

分发顺序：**具体类 → 事件族（带二级类型）→ 事件族（post_type）→ 全局兜底**。处理器可以是 `def` 或 `async def`；单个处理器抛异常会被记录，不影响其他处理器。

## 主动操作

```python
bot.reply_private(event, "文本", quote=True)   # 引用回复私聊
bot.reply_group(event, "文本", quote=True)     # 引用回复群聊
bot.recall(message_id)                         # 撤回
bot.call("任意action", **params)               # 直接调 OneBot API
```

## 字段来源

事件字段不是猜的，全部来自 `napcat.mjs`：

- **class 声明型事件**（notice / request / meta）：class field + constructor 赋值 + `extends` 链合并。基类 `r4 → na → Qo` 提供 `time` / `self_id` / `post_type` / `group_id` / `user_id`。
- **消息事件**：由 `initializeMessage()` 返回对象字面量，再被 `handleGroupMessage` / `handlePrivateMessage` / `handleTempGroupMessage` 补字段（`group_name`、`temp_source`、`sender.role` 等）。

两个抽取难点：

1. `post_type` 是枚举引用 `Fl.NOTICE`，必须解析 `var Fl = ((t) => (t.NOTICE = "notice", ...))` 才能得到字面值。
2. `sub_type` 常是 constructor 参数（`o = "leave"`），真实取值要看实例化处传入的字面量。比如 `group_increase` 在 4 处分别传 `"approve"` 和 `"invite"`，所以一个类要注册多个 sub_type 键。

## 实测（真实 NapCat 4.18.42）

```
[生命周期] connect
[事件] MetaLifecycleEvent  post_type=meta_event lifecycle/connect
[事件] PrivateMessageSentEvent  post_type=message_sent private/friend
[戳一戳] 2108172573 -> 2108172573
[事件] PokeNotify  post_type=notice notify/poke
[事件] GroupMessageSentEvent  post_type=message_sent group/normal
[心跳] online=True good=True
[事件] MetaHeartbeatEvent  post_type=meta_event heartbeat/
[群撤回] 群 856296858 消息 1295088174 被 2108172573 撤回（原作者 2108172573）
[事件] GroupRecallNotice  post_type=notice group_recall/
```

离线自测 `python demo_events.py --offline`：喂 18 条假事件，全部解析到正确类，无一退化成兜底类。

单测 `python test_qqbot_events.py`：11 组全绿，覆盖注册表全覆盖、多 sub_type 共用类、未知事件兜底、字段填充、消息段拍平、分发优先级、异步处理器、异常隔离、无参构造。

## 重新生成

```bash
python _extract_events.py    # napcat.mjs -> _events.json
python _gen_events.py        # _events.json -> qqbot_events.py
python test_qqbot_events.py
```

## 说明

NapCat 对**自己发出**的消息只报 `message_sent`，不会额外产生 `group_msg_emoji_like` 这类 notice —— 这是平台行为，需要其他真实用户操作才能触发对应事件。
