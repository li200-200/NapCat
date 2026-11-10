# NapCat 私聊实时监听 + 指定消息回复 Demo

基于 OneBot v11 协议，用 Python 实时接收 NapCat 推送的私聊消息，命中规则后以「引用回复」的方式回复原消息。

## 文件

| 文件 | 说明 |
| --- | --- |
| `napcat_demo.py` | 主程序：WS 实时监听 + 规则匹配 + HTTP 回复 |
| `config.json` | 规则与连接配置（支持热加载） |
| `test_pipeline.py` | 离线自测：起本地假 OneBot 服务端，跑通完整链路，不碰真实账号 |

## 环境现状（本机已配好）

- NapCat Desktop：`D:\NCQQ\NapCatQQ-Desktop.exe`，已登录 QQ `2108172573 (GeGe)`
- OneBot HTTP API：`http://127.0.0.1:3000`，token `pydemo_token_2024`
- OneBot WS 事件流：`ws://127.0.0.1:3001`（`reportSelfMessage: true`，自己发的消息也会推送）
- NapCat 配置文件：`C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\config\onebot11_2108172573.json`

> 注意：WebSocket **服务端** 才带 `reportSelfMessage`；HTTP 服务端的 schema 里没有这个字段。

## 依赖

```bash
pip install websockets aiohttp
```

## 运行

```bash
# 正常监听（Ctrl+C 退出）
python napcat_demo.py

# 详细日志
python napcat_demo.py -v

# 只测规则匹配，不连 NapCat
python napcat_demo.py --test "calc 12+30"

# 手动给某人发一条私聊
python napcat_demo.py --send 1544629526 "hello"

# 手动发一条「引用回复」，引用 message_id
python napcat_demo.py --send 1544629526 "这条是引用回复" --quote 897790584

# 离线全链路自测（不需要真实 QQ）
python test_pipeline.py
```

## 配置说明（config.json）

```jsonc
{
  "onebot": {
    "http_base": "http://127.0.0.1:3000",   // 发消息用的 HTTP API
    "ws_url": "ws://127.0.0.1:3001",        // 收事件用的 WS 服务端
    "access_token": "pydemo_token_2024",
    "timeout": 10
  },
  "behavior": {
    "self_id": 0,              // 0 = 启动时自动 get_login_info 获取
    "reply_self": true,        // 自己发的私聊也走规则（方便自测；生产建议 false）
    "reply_delay_ms": 300,     // 回复前延迟，防刷屏
    "dedup_window": 500,       // 消息去重窗口大小
    "log_file": "messages.jsonl",
    "config_reload_seconds": 3 // >0 时热加载规则，改完 json 不用重启
  },
  "rules": [
    { "name": "ping", "match": "exact",    "pattern": "ping",   "reply": "pong" },
    { "name": "echo", "match": "prefix",   "pattern": "复读 ",  "reply": "{1}" },
    { "name": "calc", "match": "regex",    "pattern": "^calc\\s+(\\d+)\\s*\\+\\s*(\\d+)$",
      "reply": "{1} + {2} = {sum}" }
  ],
  "fallback": { "enabled": false, "reply": "收到：{text}" }
}
```

### 匹配方式 `match`

| 值 | 含义 |
| --- | --- |
| `exact` | 去空格后完全相等 |
| `contains` | 包含子串 |
| `prefix` / `suffix` | 前缀 / 后缀 |
| `regex` | 正则搜索，`{1}` `{2}` 取分组 |

### 回复模板占位符

- `{1}` `{2}` … 正则分组 / `prefix` 匹配后的剩余部分
- `{sum}` 所有数字分组之和
- `{text}` 原文、`{now}` `{date}` `{time}` 时间、`{rule}` 规则名
- `{user_id}` `{nickname}` `{message_id}` 发送者上下文
- 规则可加 `"scope": "group"` 或 `"all"`，默认只处理私聊

## 核心实现要点

1. **实时性**：用 WebSocket 长连接接收 `post_type=message` 事件，不做 HTTP 轮询。
2. **只处理私聊**：`event["message_type"] == "private"` 才继续。
3. **指定消息回复**：发送时 message 用数组格式，首位塞 `{"type":"reply","data":{"id": str(message_id)}}`，再接 text 段。
4. **消息段转文本**：`segments_to_text()` 把 array 格式拍平成文本，图片/表情/语音用 `[图片]` 这类占位。
5. **防重复**：`message_id` 环形去重，避免 WS 重连或重推导致重复回复。
6. **防自激**：记录自己发出的 `message_id`，回复内容即使命中规则也不再触发（否则 `ping -> pong -> ...` 可能自循环）。
7. **断线重连**：指数退避 1s→30s，`_stop` 事件可优雅退出。
8. **兼容性**：`websockets` 13.x 用 `extra_headers`，14+ 用 `additional_headers`，代码自动判断。

## 自测结果（本机真实环境已验证）

```
[自己私聊] GeGe(2108172573): ping
命中规则 ping -> 回复: pong
已回复 -> 2108172573
忽略自己刚发出的回复: 546561644

[自己私聊] GeGe(2108172573): calc 7+35
命中规则 calc -> 回复: 7 + 35 = 42
已回复 -> 2108172573

引用回复验证：get_msg 返回
[{"type":"reply","data":{"id":"1585037374"}},{"type":"text","data":{"text":"这条是引用回复"}}]
```

`python test_pipeline.py` 离线用例全绿：私聊命中 3 条、群消息忽略、重复 message_id 去重、回复均带 reply 引用段。

## 接真实好友时

把 `behavior.reply_self` 改成 `false`，`config.json` 里的规则按需改，然后直接 `python napcat_demo.py`。
别人给你发 `ping`，就会收到一条引用他那条消息的 `pong`。
