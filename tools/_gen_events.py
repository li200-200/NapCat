"""由 _events.json 生成 qqbot_events.py —— 全部 OneBot 事件的中文封装。

产物包含：
  1. 事件数据类（每个事件一个 dataclass，字段来自 napcat.mjs 抽取结果）
  2. EventParser —— 把原始 JSON 分派成对应数据类
  3. EventDispatcher —— 装饰器注册式分发器，支持异步
  4. QQBotEvents —— 基于 WebSocket 的实时监听客户端
"""
import json


from pathlib import Path

# 仓库根目录（tools/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent

EVENTS = str(ROOT / 'tools' / '_events.json')
OUT = str(ROOT / 'napcat' / 'events.py')

events = json.load(open(EVENTS, encoding='utf-8'))

# ------------------------------------------------------------------ 中文说明表
# (post_type, 二级类型, sub_type) -> (类名, 中文说明)
DESC = {
    ('meta_event', 'lifecycle', None): ('MetaLifecycleEvent', '生命周期事件：连接建立/启用/禁用'),
    ('meta_event', 'heartbeat', None): ('MetaHeartbeatEvent', '心跳事件：定期上报运行状态'),
    ('message', 'private', None): ('PrivateMessageEvent', '私聊消息'),
    ('message', 'group', None): ('GroupMessageEvent', '群聊消息'),
    ('message_sent', 'private', None): ('PrivateMessageSentEvent', '自己发出的私聊消息'),
    ('message_sent', 'group', None): ('GroupMessageSentEvent', '自己发出的群聊消息'),
    ('notice', 'friend_add', None): ('FriendAddNotice', '好友已添加'),
    ('notice', 'friend_recall', None): ('FriendRecallNotice', '好友消息撤回'),
    ('notice', 'group_recall', None): ('GroupRecallNotice', '群消息撤回'),
    ('notice', 'group_upload', None): ('GroupUploadNotice', '群文件上传'),
    ('notice', 'group_admin', None): ('GroupAdminNotice', '群管理员变动（set 设置 / unset 取消）'),
    ('notice', 'group_decrease', None): ('GroupDecreaseNotice', '群成员减少（leave 主动退 / kick 被踢 / kick_me 自己被踢）'),
    ('notice', 'group_increase', None): ('GroupIncreaseNotice', '群成员增加（approve 管理员通过 / invite 被邀请）'),
    ('notice', 'group_ban', None): ('GroupBanNotice', '群禁言（ban 禁言 / lift_ban 解除禁言）'),
    ('notice', 'group_card', None): ('GroupCardNotice', '群名片变更'),
    ('notice', 'essence', None): ('GroupEssenceNotice', '群精华消息（add 添加 / delete 移除）'),
    ('notice', 'group_msg_emoji_like', None): ('GroupMsgEmojiLikeNotice', '群消息表情回应'),
    ('notice', 'bot_offline', None): ('BotOfflineNotice', '机器人离线'),
    ('notice', 'online_file_send', None): ('OnlineFileSendNotice', '在线文件发送'),
    ('notice', 'notify', 'poke'): ('PokeNotify', '戳一戳'),
    ('notice', 'notify', 'title'): ('TitleNotify', '群成员荣誉变更'),
    ('notice', 'notify', 'gray_tip'): ('GrayTipNotify', '灰条消息'),
    ('notice', 'notify', 'group_name'): ('GroupNameNotify', '群名变更'),
    ('notice', 'notify', 'input_status'): ('InputStatusNotify', '输入状态（正在输入）'),
    ('notice', 'notify', 'profile_like'): ('ProfileLikeNotify', '名片点赞'),
    ('notice', None, None): ('BaseNotice', '未知通知事件（兜底）'),
    ('request', 'friend', None): ('FriendRequest', '好友添加请求'),
    ('request', 'group', None): ('GroupRequest', '群添加/邀请请求（add 加群 / invite 邀请）'),
}

# 字段类型标注：按字段名推断
FIELD_TYPES = {
    'time': 'int', 'self_id': 'int', 'post_type': 'str',
    'notice_type': 'str', 'request_type': 'str', 'meta_event_type': 'str',
    'message_type': 'str', 'sub_type': 'str',
    'user_id': 'int', 'group_id': 'int', 'operator_id': 'int',
    'target_id': 'int', 'sender_id': 'int', 'peer_id': 'int',
    'message_id': 'int', 'message_seq': 'int', 'busi_id': 'int',
    'duration': 'int', 'interval': 'int', 'times': 'int',
    'status': 'dict', 'likes': 'list', 'file': 'dict', 'raw_info': 'dict',
    'is_add': 'bool', 'card_new': 'str', 'card_old': 'str',
    'name_new': 'str', 'title': 'str', 'comment': 'str', 'flag': 'str',
    'message': 'str', 'tag': 'str', 'content': 'str', 'status_text': 'str',
    'operator_nick': 'str', 'event_type': 'str',
}

HEADER = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQBot 事件模块 —— NapCat / OneBot v11 全部事件的中文封装。

本文件由 _events.json（从 napcat.mjs 抽取）自动生成，覆盖 NapCat 4.18.42
上报的全部 24 类事件。每个事件都对应一个 dataclass，字段名与 OneBot v11
协议一致，类型按语义标注。

包含四部分：
    1. 事件数据类    —— 每个事件一个 @dataclass，字段即协议字段
    2. EventParser   —— 把原始 JSON dict 分派成对应数据类
    3. EventDispatcher —— 装饰器注册式分发器，支持同步/异步处理器
    4. QQBotEvents   —— 基于 WebSocket 的实时监听客户端（自动重连）

用法：
    from qqbot_events import QQBotEvents

    bot = QQBotEvents("ws://127.0.0.1:3001", "你的token")

    @bot.on_private_message
    async def handle_private(event):
        print(f"收到 {event.user_id} 的私聊：{event.plain_text}")
        await bot.reply_private(event, "收到")

    bot.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, fields as dataclass_fields
from datetime import datetime
from typing import Any, Callable, Iterable

import requests
import websockets

log = logging.getLogger("qqbot.events")


# ======================================================================= #
# 一、消息段工具
# ======================================================================= #
def segments_to_text(message: Any) -> str:
    """把 OneBot 消息段数组拍平成可读文本。

    图片、表情、语音等非文本段用方括号占位，方便直接打印/日志。
    """
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return ""
    parts: list[str] = []
    for seg in message:
        if not isinstance(seg, dict):
            continue
        stype = seg.get("type")
        data = seg.get("data") or {}
        if stype == "text":
            parts.append(str(data.get("text", "")))
        elif stype == "at":
            qq = data.get("qq")
            parts.append("@全体成员" if qq == "all" else f"@{qq}")
        elif stype == "face":
            parts.append(f"[表情{data.get('id', '')}]")
        elif stype == "image":
            parts.append("[图片]")
        elif stype == "record":
            parts.append("[语音]")
        elif stype == "video":
            parts.append("[视频]")
        elif stype == "file":
            parts.append(f"[文件 {data.get('file', '')}]")
        elif stype == "reply":
            continue
        else:
            parts.append(f"[{stype}]")
    return "".join(parts).strip()


# ======================================================================= #
# 二、事件数据类
# ======================================================================= #
@dataclass
class BaseEvent:
    """所有事件的公共字段。"""

    time: int = 0
    self_id: int = 0
    post_type: str = ""

    @property
    def datetime(self) -> datetime:
        """事件时间转本地 datetime。"""
        return datetime.fromtimestamp(self.time or 0)

    @classmethod
    def from_dict(cls, data: dict) -> "BaseEvent":
        """按 dataclass 字段过滤未知键，构造实例。"""
        known = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
'''

# ------------------------------------------------------------------ 生成数据类
class_blocks = []

# 按 post_type 分组
by_post = {}
for e in events:
    by_post.setdefault(e['post_type'], []).append(e)

ORDER = ['meta_event', 'message', 'message_sent', 'notice', 'request', None]


def field_line(fname: str, indent: str = '    ') -> str:
    typ = FIELD_TYPES.get(fname, 'Any')
    if typ == 'Any':
        return f'{indent}{fname}: Any = None'
    if typ == 'int':
        return f'{indent}{fname}: int = 0'
    if typ == 'str':
        return f'{indent}{fname}: str = ""'
    if typ == 'bool':
        return f'{indent}{fname}: bool = False'
    if typ == 'dict':
        return f'{indent}{fname}: dict = field(default_factory=dict)'
    if typ == 'list':
        return f'{indent}{fname}: list = field(default_factory=list)'
    return f'{indent}{fname}: Any = None'


def build_class(e, base: str, extra_fields: list[str], doc: str) -> str:
    cls_name = DESC[(e['post_type'], e['notice_type'] or e['request_type']
                     or e['meta_event_type'] or e['message_type'],
                     e['sub_type'])][0] if False else None
    return ''


# 每个事件生成一个类
generated = []
used_names = set()
# 同一 (post_type, 二级类型) 下多个 sub_type 共用一个类，注册多个键
family_class: dict[tuple[str, str], str] = {}


def pick_class(e) -> tuple[str, str]:
    """决定该事件用哪个类名 + 中文说明。"""
    second = (e['notice_type'] or e['request_type']
              or e['meta_event_type'] or e['message_type'])
    family = (e['post_type'], second)

    # notify 的每个 sub_type 是不同事件，各自建类，不能共用
    share = second != 'notify'

    if share and family in family_class:
        cls_name = family_class[family]
        return cls_name, DESC.get((e['post_type'], second, e['sub_type']),
                                  ('', ''))[1]

    key = (e['post_type'], second, e['sub_type'])
    cls_name, doc = DESC.get(key, (None, None))
    if cls_name is None:
        cls_name, doc = DESC.get((e['post_type'], second, None),
                                 ('UnknownEvent', '未知事件'))
    if share:
        family_class[family] = cls_name
    return cls_name, doc


for post_type in ORDER:
    for e in by_post.get(post_type, []):
        cls_name, doc = pick_class(e)
        if cls_name in used_names:
            continue          # 同族已生成，跳过
        used_names.add(cls_name)

        # 需要额外声明的字段（排除基类已有的）
        base_fields = {'time', 'self_id', 'post_type'}
        own = [f for f in e['fields'] if f not in base_fields]

        lines = ['@dataclass', f'class {cls_name}(BaseEvent):']
        lines.append(f'    """{doc}')
        lines.append('')
        lines.append(f'    原始来源: {e["class"]}')
        lines.append(f'    字段: {", ".join(e["fields"])}')
        lines.append('    """')
        if not own:
            lines.append('    pass')
        else:
            for f in own:
                lines.append(field_line(f))

        # 消息类附加便捷属性
        if e['post_type'] in ('message', 'message_sent'):
            lines.append('')
            lines.append('    @property')
            lines.append('    def plain_text(self) -> str:')
            lines.append('        """消息段数组拍平后的纯文本（图片等用占位符）。"""')
            lines.append('        return segments_to_text(self.message)')

        generated.append('\n'.join(lines))

DATA_CLASSES = '\n\n\n'.join(generated)

# ------------------------------------------------------------------ 解析器
parser_lines = ['''# ======================================================================= #
# 三、事件解析器
# ======================================================================= #
class EventParser:
    """把 OneBot 原始 JSON dict 分派成对应的数据类实例。

    分派顺序：先看 post_type，再按 notice_type / request_type /
    meta_event_type / message_type 二级区分，最后用 sub_type 细分。
    """

    #: (post_type, 二级类型, sub_type) -> 事件类
    REGISTRY: dict[tuple[str, str, str | None], type[BaseEvent]] = {}
''']

for post_type in ORDER:
    for e in by_post.get(post_type, []):
        second = (e['notice_type'] or e['request_type']
                  or e['meta_event_type'] or e['message_type'])
        key = (e['post_type'], second, e['sub_type'])
        cls_name, _ = DESC.get(key, (None, None))
        if cls_name is None:
            cls_name = DESC.get((e['post_type'], second, None),
                                ('UnknownEvent', ''))[0]
        parser_lines.append(
            f'    REGISTRY[({e["post_type"]!r}, {second!r}, {e["sub_type"]!r})] = {cls_name}')

# 补充：同一类事件的其他 sub_type 取值也要能分派到同一个类
# （NapCat 源码里 sub_type 由构造函数参数决定，扫描只见到其中一个字面量）
EXTRA_SUBTYPES = {
    ('notice', 'group_decrease'): ['leave', 'kick', 'kick_me'],
    ('notice', 'group_increase'): ['approve', 'invite'],
    ('notice', 'group_admin'): ['set', 'unset'],
    ('notice', 'group_ban'): ['ban', 'lift_ban'],
    ('notice', 'essence'): ['add', 'delete'],
    ('request', 'group'): ['add', 'invite'],
}
parser_lines.append('')
parser_lines.append('    # 同一事件的其他 sub_type 取值，指向同一个类')
for (post_type, second), subtypes in EXTRA_SUBTYPES.items():
    cls_name = DESC.get((post_type, second, None), (None, ''))[0]
    if cls_name is None:
        continue
    for st in subtypes:
        parser_lines.append(
            f'    REGISTRY[({post_type!r}, {second!r}, {st!r})] = {cls_name}')

parser_lines.append('''
    @classmethod
    def parse(cls, raw: dict) -> BaseEvent:
        """解析单条原始事件。无法识别时返回 BaseEvent。"""
        if not isinstance(raw, dict):
            return BaseEvent()

        post_type = raw.get("post_type") or ""
        second = (raw.get("notice_type") or raw.get("request_type")
                  or raw.get("meta_event_type") or raw.get("message_type") or "")
        sub_type = raw.get("sub_type")

        # 精确匹配优先
        target = cls.REGISTRY.get((post_type, second, sub_type))
        # 退到不带 sub_type 的条目
        if target is None:
            target = cls.REGISTRY.get((post_type, second, None))
        # notice 兜底
        if target is None and post_type == "notice":
            target = cls.REGISTRY.get(("notice", None, None))
        if target is None:
            return BaseEvent.from_dict(raw)

        return target.from_dict(raw)


def parse_event(raw: dict | str) -> BaseEvent:
    """模块级便捷函数：dict 或 JSON 字符串 -> 事件对象。"""
    if isinstance(raw, (str, bytes)):
        raw = json.loads(raw)
    return EventParser.parse(raw)
''')

PARSER = '\n'.join(parser_lines)

# ------------------------------------------------------------------ 分发器
DISPATCHER = '''

# ======================================================================= #
# 四、事件分发器
# ======================================================================= #
Handler = Callable[[BaseEvent], Any]


class EventDispatcher:
    """装饰器注册式事件分发器。

    支持三种注册粒度，优先级从高到低：
        1. 具体事件类：``@dispatcher.on(GroupBanNotice)``
        2. 事件族：    ``@dispatcher.on_notice("group_ban")``
        3. 全局兜底：  ``@dispatcher.on_any()``

    处理器可以是同步函数，也可以是 async 函数。
    """

    def __init__(self) -> None:
        self._by_class: dict[type, list[Handler]] = {}
        self._by_family: dict[tuple[str, str | None], list[Handler]] = {}
        self._any: list[Handler] = []

    # ---------------- 注册 ----------------
    def on(self, event_cls: type[BaseEvent]) -> Callable[[Handler], Handler]:
        """按具体事件类注册。"""
        def deco(fn: Handler) -> Handler:
            self._by_class.setdefault(event_cls, []).append(fn)
            return fn
        return deco

    def on_family(self, post_type: str,
                  second: str | None = None) -> Callable[[Handler], Handler]:
        """按事件族注册，例如 (notice, group_ban) 或 (message, None)。"""
        def deco(fn: Handler) -> Handler:
            self._by_family.setdefault((post_type, second), []).append(fn)
            return fn
        return deco

    def on_any(self) -> Callable[[Handler], Handler]:
        """全局兜底：任何事件都会触发。"""
        def deco(fn: Handler) -> Handler:
            self._any.append(fn)
            return fn
        return deco

    # ---------------- 分发 ----------------
    async def dispatch(self, event: BaseEvent) -> None:
        """按优先级依次调用处理器，单个处理器异常不影响其他。"""
        handlers: list[Handler] = []
        handlers.extend(self._by_class.get(type(event), []))

        post_type = event.post_type
        second = getattr(event, 'notice_type', None) or \\
            getattr(event, 'request_type', None) or \\
            getattr(event, 'meta_event_type', None) or \\
            getattr(event, 'message_type', None)
        handlers.extend(self._by_family.get((post_type, second), []))
        handlers.extend(self._by_family.get((post_type, None), []))
        handlers.extend(self._any)

        for fn in handlers:
            try:
                result = fn(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("事件处理器 %s 抛异常", getattr(fn, "__name__", fn))
'''

# ------------------------------------------------------------------ 监听客户端
CLIENT = '''

# ======================================================================= #
# 五、WebSocket 实时监听客户端
# ======================================================================= #
class QQBotEvents:
    """基于 WebSocket 的 OneBot 事件监听客户端。

    同时带一个 HTTP 会话用于「回消息」这类主动操作。

    :param ws_url:     WebSocket 地址，NapCat 的 websocketServers
    :param token:      access token（可为空）
    :param http_base:  HTTP API 地址，用于发消息/撤回
    :param reconnect:  断线是否自动重连
    """

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:3001",
        token: str = "",
        http_base: str = "http://127.0.0.1:3000",
        reconnect: bool = True,
        max_backoff: float = 30.0,
    ) -> None:
        self.ws_url = ws_url
        self.token = token
        self.http_base = http_base.rstrip("/")
        self.reconnect = reconnect
        self.max_backoff = max_backoff
        self.dispatcher = EventDispatcher()
        self.self_id = 0
        self._stop = asyncio.Event()
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    # ---------------- 注册快捷方式 ----------------
    def on_private_message(self, fn: Handler) -> Handler:
        """私聊消息（message_type == private）。"""
        return self.dispatcher.on(PrivateMessageEvent)(fn)

    def on_group_message(self, fn: Handler) -> Handler:
        """群聊消息（message_type == group）。"""
        return self.dispatcher.on(GroupMessageEvent)(fn)

    def on_any(self, fn: Handler) -> Handler:
        """任何事件。"""
        return self.dispatcher.on_any()(fn)

    def on_notice(self, notice_type: str) -> Callable[[Handler], Handler]:
        """指定 notice_type 的通知事件，如 "group_ban"。"""
        return self.dispatcher.on_family("notice", notice_type)

    def on_request(self, request_type: str) -> Callable[[Handler], Handler]:
        """指定 request_type 的请求事件，如 "friend" / "group"。"""
        return self.dispatcher.on_family("request", request_type)

    def on_meta(self, meta_type: str) -> Callable[[Handler], Handler]:
        """指定 meta_event_type 的元事件，如 "lifecycle" / "heartbeat"。"""
        return self.dispatcher.on_family("meta_event", meta_type)

    # ---------------- 主动操作 ----------------
    def call(self, action: str, **params: Any) -> dict:
        """调用 OneBot HTTP API（发消息、撤回等）。"""
        url = f"{self.http_base}/{action}"
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            resp = self._session.post(url, json=payload, timeout=10)
            return resp.json()
        except Exception as exc:
            log.error("调用 %s 失败: %r", action, exc)
            return {"status": "failed", "message": repr(exc)}

    def reply_private(self, event: PrivateMessageEvent, text: str,
                      quote: bool = True) -> dict:
        """回复私聊消息；quote=True 时以「引用」形式回复原消息。"""
        message: list[dict] = []
        if quote and getattr(event, "message_id", 0):
            message.append({"type": "reply",
                            "data": {"id": str(event.message_id)}})
        message.append({"type": "text", "data": {"text": text}})
        return self.call("send_private_msg", user_id=event.user_id,
                         message=message)

    def reply_group(self, event: GroupMessageEvent, text: str,
                    quote: bool = True) -> dict:
        """回复群消息；quote=True 时引用原消息。"""
        message: list[dict] = []
        if quote and getattr(event, "message_id", 0):
            message.append({"type": "reply",
                            "data": {"id": str(event.message_id)}})
        message.append({"type": "text", "data": {"text": text}})
        return self.call("send_group_msg", group_id=event.group_id,
                         message=message)

    def recall(self, message_id: int) -> bool:
        """撤回消息。"""
        result = self.call("delete_msg", message_id=message_id)
        return result.get("retcode") == 0

    # ---------------- 生命周期 ----------------
    def stop(self) -> None:
        """请求停止监听。"""
        self._stop.set()

    def run(self) -> None:
        """阻塞运行（Ctrl+C 退出）。"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            log.info("已手动停止")

    async def run_async(self) -> None:
        """异步运行入口。"""
        info = self.call("get_login_info").get("data") or {}
        if info.get("user_id"):
            self.self_id = int(info["user_id"])
            log.info("已连接账号: %s (%s)", info.get("user_id"),
                     info.get("nickname"))
        else:
            log.warning("get_login_info 未返回账号，继续尝试连接 WS")

        await self._ws_loop()

    async def _ws_loop(self) -> None:
        backoff = 1.0
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        # websockets 13.x 用 extra_headers，14+ 用 additional_headers
        major = int(getattr(websockets, "__version__", "13").split(".")[0])
        header_kw = {"additional_headers" if major >= 14 else "extra_headers":
                     headers} if headers else {}

        while not self._stop.is_set():
            try:
                log.info("连接 WebSocket: %s", self.ws_url)
                async with websockets.connect(
                    self.ws_url, ping_interval=20, ping_timeout=20,
                    max_size=32 * 1024 * 1024, **header_kw,
                ) as ws:
                    log.info("WebSocket 已连接，开始监听事件")
                    backoff = 1.0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        await self._handle_raw(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set() or not self.reconnect:
                    break
                log.error("WebSocket 断开: %r，%.1f 秒后重连", exc, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, self.max_backoff)

    async def _handle_raw(self, raw: str | bytes) -> None:
        """把一帧原始数据解析并分发。"""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning("非 JSON 帧: %r", str(raw)[:200])
            return

        # 响应帧（带 echo）不是事件，跳过
        if "post_type" not in data:
            return

        event = EventParser.parse(data)
        await self.dispatcher.dispatch(event)
'''

# 组装文件
body = HEADER + '\n\n' + DATA_CLASSES + '\n\n\n' + PARSER + DISPATCHER + CLIENT

# 追加：模块级导出
exports = [DESC[k][0] for k in DESC]
body += '''

# ======================================================================= #
# 六、导出
# ======================================================================= #
__all__ = [
    "BaseEvent",
    "EventParser",
    "EventDispatcher",
    "QQBotEvents",
    "parse_event",
    "segments_to_text",
'''
for name in sorted(set(exports)):
    body += f'    "{name}",\n'
body += ']\n'

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(body)

print(f'wrote {OUT}')
print(f'data classes: {len(generated)}')
