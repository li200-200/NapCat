#!/usr/bin/env python3
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


@dataclass
class MetaHeartbeatEvent(BaseEvent):
    """心跳事件：定期上报运行状态

    原始来源: z0
    字段: meta_event_type, status, interval, post_type, time, self_id
    """
    meta_event_type: str = ""
    status: dict = field(default_factory=dict)
    interval: int = 0


@dataclass
class MetaLifecycleEvent(BaseEvent):
    """生命周期事件：连接建立/启用/禁用

    原始来源: Vy
    字段: meta_event_type, sub_type, post_type, time, self_id
    """
    meta_event_type: str = ""
    sub_type: str = ""


@dataclass
class GroupMessageEvent(BaseEvent):
    """群聊消息

    原始来源: initializeMessage + handleGroupMessage
    字段: self_id, user_id, time, message_id, message_seq, real_id, real_seq, message_type, sender, raw_message, font, sub_type, message, message_format, post_type, group_id, group_name
    """
    user_id: int = 0
    message_id: int = 0
    message_seq: int = 0
    real_id: Any = None
    real_seq: Any = None
    message_type: str = ""
    sender: Any = None
    raw_message: Any = None
    font: Any = None
    sub_type: str = ""
    message: str = ""
    message_format: Any = None
    group_id: int = 0
    group_name: Any = None

    @property
    def plain_text(self) -> str:
        """消息段数组拍平后的纯文本（图片等用占位符）。"""
        return segments_to_text(self.message)


@dataclass
class PrivateMessageEvent(BaseEvent):
    """私聊消息

    原始来源: initializeMessage + handlePrivateMessage
    字段: self_id, user_id, time, message_id, message_seq, real_id, real_seq, message_type, sender, raw_message, font, sub_type, message, message_format, post_type
    """
    user_id: int = 0
    message_id: int = 0
    message_seq: int = 0
    real_id: Any = None
    real_seq: Any = None
    message_type: str = ""
    sender: Any = None
    raw_message: Any = None
    font: Any = None
    sub_type: str = ""
    message: str = ""
    message_format: Any = None

    @property
    def plain_text(self) -> str:
        """消息段数组拍平后的纯文本（图片等用占位符）。"""
        return segments_to_text(self.message)


@dataclass
class GroupMessageSentEvent(BaseEvent):
    """自己发出的群聊消息

    原始来源: initializeMessage (self) + handleGroupMessage
    字段: self_id, user_id, time, message_id, message_seq, real_id, real_seq, message_type, sender, raw_message, font, sub_type, message, message_format, post_type, message_sent_type, emoji_likes_list, group_id, group_name
    """
    user_id: int = 0
    message_id: int = 0
    message_seq: int = 0
    real_id: Any = None
    real_seq: Any = None
    message_type: str = ""
    sender: Any = None
    raw_message: Any = None
    font: Any = None
    sub_type: str = ""
    message: str = ""
    message_format: Any = None
    message_sent_type: Any = None
    emoji_likes_list: Any = None
    group_id: int = 0
    group_name: Any = None

    @property
    def plain_text(self) -> str:
        """消息段数组拍平后的纯文本（图片等用占位符）。"""
        return segments_to_text(self.message)


@dataclass
class PrivateMessageSentEvent(BaseEvent):
    """自己发出的私聊消息

    原始来源: initializeMessage (self) + handlePrivateMessage
    字段: self_id, user_id, time, message_id, message_seq, real_id, real_seq, message_type, sender, raw_message, font, sub_type, message, message_format, post_type, message_sent_type, emoji_likes_list
    """
    user_id: int = 0
    message_id: int = 0
    message_seq: int = 0
    real_id: Any = None
    real_seq: Any = None
    message_type: str = ""
    sender: Any = None
    raw_message: Any = None
    font: Any = None
    sub_type: str = ""
    message: str = ""
    message_format: Any = None
    message_sent_type: Any = None
    emoji_likes_list: Any = None

    @property
    def plain_text(self) -> str:
        """消息段数组拍平后的纯文本（图片等用占位符）。"""
        return segments_to_text(self.message)


@dataclass
class BaseNotice(BaseEvent):
    """未知通知事件（兜底）

    原始来源: iF
    字段: notice_type, sub_type, peer_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    peer_id: int = 0


@dataclass
class BotOfflineNotice(BaseEvent):
    """机器人离线

    原始来源: H6e
    字段: notice_type, user_id, tag, message, post_type, time, self_id
    """
    notice_type: str = ""
    user_id: int = 0
    tag: str = ""
    message: str = ""


@dataclass
class GroupEssenceNotice(BaseEvent):
    """群精华消息（add 添加 / delete 移除）

    原始来源: Uxe
    字段: notice_type, message_id, sender_id, operator_id, sub_type, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    message_id: int = 0
    sender_id: int = 0
    operator_id: int = 0
    sub_type: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class FriendAddNotice(BaseEvent):
    """好友已添加

    原始来源: Rwe
    字段: notice_type, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    user_id: int = 0


@dataclass
class FriendRecallNotice(BaseEvent):
    """好友消息撤回

    原始来源: G6e
    字段: notice_type, user_id, message_id, post_type, time, self_id
    """
    notice_type: str = ""
    user_id: int = 0
    message_id: int = 0


@dataclass
class GroupAdminNotice(BaseEvent):
    """群管理员变动（set 设置 / unset 取消）

    原始来源: Qwe
    字段: notice_type, sub_type, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupBanNotice(BaseEvent):
    """群禁言（ban 禁言 / lift_ban 解除禁言）

    原始来源: Sxe
    字段: notice_type, operator_id, duration, sub_type, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    operator_id: int = 0
    duration: int = 0
    sub_type: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupCardNotice(BaseEvent):
    """群名片变更

    原始来源: Bxe
    字段: notice_type, card_new, card_old, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    card_new: str = ""
    card_old: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupDecreaseNotice(BaseEvent):
    """群成员减少（leave 主动退 / kick 被踢 / kick_me 自己被踢）

    原始来源: Bwe
    字段: notice_type, sub_type, operator_id, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    operator_id: int = 0
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupIncreaseNotice(BaseEvent):
    """群成员增加（approve 管理员通过 / invite 被邀请）

    原始来源: Ng
    字段: notice_type, operator_id, sub_type, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    operator_id: int = 0
    sub_type: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupMsgEmojiLikeNotice(BaseEvent):
    """群消息表情回应

    原始来源: Rxe
    字段: notice_type, message_id, likes, is_add, message_seq, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    message_id: int = 0
    likes: list = field(default_factory=list)
    is_add: bool = False
    message_seq: int = 0
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupRecallNotice(BaseEvent):
    """群消息撤回

    原始来源: q6e
    字段: notice_type, operator_id, message_id, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    operator_id: int = 0
    message_id: int = 0
    group_id: int = 0
    user_id: int = 0


@dataclass
class GroupUploadNotice(BaseEvent):
    """群文件上传

    原始来源: jxe
    字段: notice_type, file, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    file: dict = field(default_factory=dict)
    group_id: int = 0
    user_id: int = 0


@dataclass
class GrayTipNotify(BaseEvent):
    """灰条消息

    原始来源: Qxe
    字段: notice_type, sub_type, group_id, user_id, message_id, busi_id, content, raw_info, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    group_id: int = 0
    user_id: int = 0
    message_id: int = 0
    busi_id: int = 0
    content: str = ""
    raw_info: dict = field(default_factory=dict)


@dataclass
class GroupNameNotify(BaseEvent):
    """群名变更

    原始来源: $xe
    字段: notice_type, sub_type, name_new, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    name_new: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class InputStatusNotify(BaseEvent):
    """输入状态（正在输入）

    原始来源: j6e
    字段: notice_type, sub_type, status_text, event_type, user_id, group_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    status_text: str = ""
    event_type: str = ""
    user_id: int = 0
    group_id: int = 0


@dataclass
class PokeNotify(BaseEvent):
    """戳一戳

    原始来源: xxe
    字段: raw_info, sender_id, notice_type, sub_type, target_id, user_id, post_type, time, self_id
    """
    raw_info: dict = field(default_factory=dict)
    sender_id: int = 0
    notice_type: str = ""
    sub_type: str = ""
    target_id: int = 0
    user_id: int = 0


@dataclass
class ProfileLikeNotify(BaseEvent):
    """名片点赞

    原始来源: Wxe
    字段: notice_type, sub_type, operator_id, operator_nick, times, time, post_type, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    operator_id: int = 0
    operator_nick: str = ""
    times: int = 0


@dataclass
class TitleNotify(BaseEvent):
    """群成员荣誉变更

    原始来源: Lxe
    字段: notice_type, sub_type, title, group_id, user_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    title: str = ""
    group_id: int = 0
    user_id: int = 0


@dataclass
class OnlineFileSendNotice(BaseEvent):
    """在线文件发送

    原始来源: dS
    字段: notice_type, sub_type, peer_id, post_type, time, self_id
    """
    notice_type: str = ""
    sub_type: str = ""
    peer_id: int = 0


@dataclass
class FriendRequest(BaseEvent):
    """好友添加请求

    原始来源: $6e
    字段: request_type, user_id, comment, flag, post_type, time, self_id
    """
    request_type: str = ""
    user_id: int = 0
    comment: str = ""
    flag: str = ""


@dataclass
class GroupRequest(BaseEvent):
    """群添加/邀请请求（add 加群 / invite 邀请）

    原始来源: Dg
    字段: request_type, group_id, user_id, comment, flag, sub_type, post_type, time, self_id
    """
    request_type: str = ""
    group_id: int = 0
    user_id: int = 0
    comment: str = ""
    flag: str = ""
    sub_type: str = ""


# ======================================================================= #
# 三、事件解析器
# ======================================================================= #
class EventParser:
    """把 OneBot 原始 JSON dict 分派成对应的数据类实例。

    分派顺序：先看 post_type，再按 notice_type / request_type /
    meta_event_type / message_type 二级区分，最后用 sub_type 细分。
    """

    #: (post_type, 二级类型, sub_type) -> 事件类
    REGISTRY: dict[tuple[str, str, str | None], type[BaseEvent]] = {}

    REGISTRY[('meta_event', 'heartbeat', None)] = MetaHeartbeatEvent
    REGISTRY[('meta_event', 'lifecycle', None)] = MetaLifecycleEvent
    REGISTRY[('message', 'group', 'normal')] = GroupMessageEvent
    REGISTRY[('message', 'private', 'friend')] = PrivateMessageEvent
    REGISTRY[('message', 'private', 'group')] = PrivateMessageEvent
    REGISTRY[('message_sent', 'group', 'normal')] = GroupMessageSentEvent
    REGISTRY[('message_sent', 'private', 'friend')] = PrivateMessageSentEvent
    REGISTRY[('notice', None, None)] = BaseNotice
    REGISTRY[('notice', 'bot_offline', None)] = BotOfflineNotice
    REGISTRY[('notice', 'essence', 'add')] = GroupEssenceNotice
    REGISTRY[('notice', 'friend_add', None)] = FriendAddNotice
    REGISTRY[('notice', 'friend_recall', None)] = FriendRecallNotice
    REGISTRY[('notice', 'group_admin', None)] = GroupAdminNotice
    REGISTRY[('notice', 'group_ban', None)] = GroupBanNotice
    REGISTRY[('notice', 'group_card', None)] = GroupCardNotice
    REGISTRY[('notice', 'group_decrease', 'leave')] = GroupDecreaseNotice
    REGISTRY[('notice', 'group_increase', None)] = GroupIncreaseNotice
    REGISTRY[('notice', 'group_msg_emoji_like', None)] = GroupMsgEmojiLikeNotice
    REGISTRY[('notice', 'group_recall', None)] = GroupRecallNotice
    REGISTRY[('notice', 'group_upload', None)] = GroupUploadNotice
    REGISTRY[('notice', 'notify', 'gray_tip')] = GrayTipNotify
    REGISTRY[('notice', 'notify', 'group_name')] = GroupNameNotify
    REGISTRY[('notice', 'notify', 'input_status')] = InputStatusNotify
    REGISTRY[('notice', 'notify', 'poke')] = PokeNotify
    REGISTRY[('notice', 'notify', 'profile_like')] = ProfileLikeNotify
    REGISTRY[('notice', 'notify', 'title')] = TitleNotify
    REGISTRY[('notice', 'online_file_send', None)] = OnlineFileSendNotice
    REGISTRY[('request', 'friend', None)] = FriendRequest
    REGISTRY[('request', 'group', None)] = GroupRequest

    # 同一事件的其他 sub_type 取值，指向同一个类
    REGISTRY[('notice', 'group_decrease', 'leave')] = GroupDecreaseNotice
    REGISTRY[('notice', 'group_decrease', 'kick')] = GroupDecreaseNotice
    REGISTRY[('notice', 'group_decrease', 'kick_me')] = GroupDecreaseNotice
    REGISTRY[('notice', 'group_increase', 'approve')] = GroupIncreaseNotice
    REGISTRY[('notice', 'group_increase', 'invite')] = GroupIncreaseNotice
    REGISTRY[('notice', 'group_admin', 'set')] = GroupAdminNotice
    REGISTRY[('notice', 'group_admin', 'unset')] = GroupAdminNotice
    REGISTRY[('notice', 'group_ban', 'ban')] = GroupBanNotice
    REGISTRY[('notice', 'group_ban', 'lift_ban')] = GroupBanNotice
    REGISTRY[('notice', 'essence', 'add')] = GroupEssenceNotice
    REGISTRY[('notice', 'essence', 'delete')] = GroupEssenceNotice
    REGISTRY[('request', 'group', 'add')] = GroupRequest
    REGISTRY[('request', 'group', 'invite')] = GroupRequest

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
        second = getattr(event, 'notice_type', None) or \
            getattr(event, 'request_type', None) or \
            getattr(event, 'meta_event_type', None) or \
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
    "BaseNotice",
    "BotOfflineNotice",
    "FriendAddNotice",
    "FriendRecallNotice",
    "FriendRequest",
    "GrayTipNotify",
    "GroupAdminNotice",
    "GroupBanNotice",
    "GroupCardNotice",
    "GroupDecreaseNotice",
    "GroupEssenceNotice",
    "GroupIncreaseNotice",
    "GroupMessageEvent",
    "GroupMessageSentEvent",
    "GroupMsgEmojiLikeNotice",
    "GroupNameNotify",
    "GroupRecallNotice",
    "GroupRequest",
    "GroupUploadNotice",
    "InputStatusNotify",
    "MetaHeartbeatEvent",
    "MetaLifecycleEvent",
    "OnlineFileSendNotice",
    "PokeNotify",
    "PrivateMessageEvent",
    "PrivateMessageSentEvent",
    "ProfileLikeNotify",
    "TitleNotify",
]
