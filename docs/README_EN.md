# qqbot_en.py — NapCat OneBot v11 的完整 Python 封装

按你给的易语言方法格式，把 NapCat 4.18.42 暴露的**全部 207 个 OneBot action** 都写成了 `QQBot` 类的方法。方法名、参数名、参数类型、默认值全部从 NapCat 源码 `napcat.mjs` 里自动抽取，共 **511 个参数**。

## 文件

| 文件 | 说明 |
| --- | --- |
| `qqbot_en.py` | 生成产物：`QQBot` 类，205 个方法（4491 行） |
| `demo_en.py` | 可直接跑的 demo |
| `test_qqbot_en.py` | 离线单测（假 session，不联网） |
| `_extract.py` | 从 napcat.mjs 抽取 action + payload schema |
| `_gen.py` | 由 `_actions.json` 生成 `qqbot_en.py` |
| `_actions.json` | 抽取结果（207 action / 511 参数） |

## 易语言原型 → Python

```
.子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
.参数 好友QQ, 长整数型
.参数 发送内容, 文本型
.参数 Random, 长整数型, 参考 可空, 撤回消息用
.参数 Req, 整数型, 参考 可空, 撤回消息用
```

对应生成的方法：

```python
def send_friend_msg(
    self,
    friend_qq: int,
    message: Any,
    random: Ref | None = None,   # by-ref, optional
    req: Ref | None = None,      # by-ref, optional
    auto_escape: bool = None,    # 额外可选参数
    timeout: int = None,
) -> str:                        # 返回 time，撤回用
```

| 易语言 | Python |
| --- | --- |
| `文本型` | `str` |
| `长整数型` | `int`（Python int 任意精度） |
| `整数型` | `int` |
| `参考` | `Ref` 容器，方法写 `.value` |
| `可空` | `= None` |
| `公开` | 无下划线方法名 |

## 用法

```python
from qqbot_en import QQBot, Ref

bot = QQBot("http://127.0.0.1:3000", "pydemo_token_2024")

# 易语言写法：Ref 出参 + 文本型 time 返回
random = Ref()
req = Ref()
t = bot.send_friend_msg(1544629526, "hello", random, req)
print(t, random.value, req.value)     # '1794330199' 2103784737 2103784737

bot.recall_friend_msg(t, random.value, req.value)   # True

# Python 写法：省略 Ref
t = bot.send_friend_msg(1544629526, "no refs")
bot.recall_friend_msg(t)                            # 只传 time 也能撤回

# 消息段直接透传
bot.send_friend_msg(1544629526, [
    {"type": "text", "data": {"text": "hi "}},
    {"type": "face", "data": {"id": "14"}},
])

# 群消息同构
random, req = Ref(), Ref()
t = bot.send_group_msg(856296858, "群消息", random, req)
bot.recall_group_msg(t, random.value, req.value)
```

## 撤回三元组的真实映射

`send_*_msg` 只返回 `message_id`。易语言要的 `(time, Random, Req)` 得从 `get_msg` 补：

| 易语言参数 | NapCat 字段 | 含义 |
| --- | --- | --- |
| `time`（返回值） | `time` | unix 秒 |
| `Random` | `message_seq` | 消息序号 |
| `Req` | `real_id` | 真实 ID |

所以 `send_*_msg` 内部发完立刻调一次 `get_msg` 补齐，并登记 `(time, random, req) → message_id` 和 `time → message_id` 两张表。`recall*` 按 `显式 id → 三元组 → time → random/req` 顺序解析 `delete_msg` 需要的 `message_id`。

## 其他 API 都是方法

```python
bot.get_login_info()                      # {'user_id': ..., 'nickname': ...}
bot.get_friend_list()
bot.get_group_list()
bot.get_stranger_info("1544629526")
bot.get_group_member_info("856296858", "1544629526")
bot.set_group_ban("856296858", "1544629526", 60)
bot.send_like("1544629526", 10)
bot.set_msg_emoji_like(message_id, 128077)
bot.send_poke("1544629526")
bot.delete_msg(message_id)
bot.get_msg(message_id)
bot.get_status() / get_version_info() / can_send_image() / can_send_record()
bot.call_raw("任意action", **params)       # 要完整 envelope 时用
bot.call("任意action", **params)           # 只取 data
```

签名示例（全部来自源码 schema）：

```
send_friend_msg(friend_qq, message, random, req, auto_escape, timeout) -> str
send_group_msg(group_id, message, random, req, auto_escape, timeout) -> str
delete_msg(message_id: int)
set_group_ban(group_id: str, user_id: str, duration: int = 0)
get_group_member_info(group_id: str, user_id: str, no_cache: bool = None)
send_like(user_id: str, times: int = 1)
set_msg_emoji_like(message_id: int, emoji_id: int, set: bool = None)
send_poke(user_id: str, group_id: str = None, target_id: str = None)
```

## 错误处理

非 0 `retcode` 抛 `QQBotError`（带 `action` / `retcode` / `message`）：

```python
try:
    bot.delete_msg(1)
except QQBotError as exc:
    print(exc)   # delete_msg failed (retcode=200): Recall failed
```

`send_friend_msg` / `send_group_msg` 是唯一不抛的：失败返回 `""`，并把 `random` / `req` 写成 `0`，符合易语言「文本型返回值」的习惯。

## 实测（真实 NapCat 4.18.42）

```
logged in as 2108172573 (GeGe)

=== E-language style ===
time   = '1794330199'   random = 2103784737   req = 2103784737
recall -> ok

=== Python style ===
time = '1794330200'
recall -> ok

=== message segments ===
time = '1794330202'
recall -> ok

=== group ===
group send time= 1794330221 random= 66326739 req= 66326739
group recall: True
```

离线单测 `python test_qqbot_en.py` 全部通过（8 组 / 30 项），覆盖返回类型、Ref 回写、三种撤回解析路径、消息段透传、失败分支、异常、生成签名、方法数量。

## 重新生成

NapCat 升级后重跑：

```bash
python _extract.py    # 重新抽 napcat.mjs -> _actions.json
python _gen.py        # 重新生成 qqbot_en.py
python test_qqbot_en.py
```

`_extract.py` 处理了三种声明形态：内联 `l.Object({...})`、`const X = l.Object({...})`、链式 `}), X = l.Object({...})`，并沿 `extends` 链找 `payloadSchema`（`send_private_msg` 就是继承基类 `eb` 拿到的 schema）。
