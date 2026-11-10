# -*- coding: utf-8 -*-
"""
napcat —— NapCat / OneBot v11 的 Python 封装。

两个核心模块：

    napcat.api     接口封装。NapCat 4.18.42 暴露的 207 个 OneBot 接口，
                   每个都是一个方法，共 511 个参数，全部从源码抽取。

    napcat.events  事件封装。29 类事件各对应一个 dataclass，
                   配 EventParser（解析）、EventDispatcher（分发）、
                   QQBotEvents（WebSocket 监听）。

快速上手：

    from napcat import QQBotEvents, PrivateMessageEvent

    bot = QQBotEvents("ws://127.0.0.1:3001", "token",
                      "http://127.0.0.1:3000")

    @bot.on_private_message
    async def handler(event: PrivateMessageEvent):
        bot.reply_private(event, "pong")

    bot.run()

完整示例见 examples/ 目录。
"""

from . import api, events
from .api import QQBot, QQBotError, Ref
from .events import (
    # 基础设施
    BaseEvent,
    BaseNotice,
    EventDispatcher,
    EventParser,
    QQBotEvents,
    parse_event,
    segments_to_text,
    # 消息事件
    GroupMessageEvent,
    GroupMessageSentEvent,
    PrivateMessageEvent,
    PrivateMessageSentEvent,
    # 元事件
    MetaHeartbeatEvent,
    MetaLifecycleEvent,
    # 通知事件
    BotOfflineNotice,
    FriendAddNotice,
    FriendRecallNotice,
    GroupAdminNotice,
    GroupBanNotice,
    GroupCardNotice,
    GroupDecreaseNotice,
    GroupEssenceNotice,
    GroupIncreaseNotice,
    GroupMsgEmojiLikeNotice,
    GroupNameNotify,
    GroupRecallNotice,
    GroupUploadNotice,
    GrayTipNotify,
    InputStatusNotify,
    OnlineFileSendNotice,
    PokeNotify,
    ProfileLikeNotify,
    TitleNotify,
    # 请求事件
    FriendRequest,
    GroupRequest,
)

__version__ = "1.0.0"

__all__ = [
    # 子模块
    "api",
    "events",
    # 接口
    "QQBot",
    "QQBotError",
    "Ref",
    # 事件基础设施
    "QQBotEvents",
    "EventParser",
    "EventDispatcher",
    "BaseEvent",
    "BaseNotice",
    "parse_event",
    "segments_to_text",
    # 消息事件
    "PrivateMessageEvent",
    "GroupMessageEvent",
    "PrivateMessageSentEvent",
    "GroupMessageSentEvent",
    # 元事件
    "MetaLifecycleEvent",
    "MetaHeartbeatEvent",
    # 通知事件
    "FriendAddNotice",
    "FriendRecallNotice",
    "GroupRecallNotice",
    "GroupUploadNotice",
    "GroupAdminNotice",
    "GroupDecreaseNotice",
    "GroupIncreaseNotice",
    "GroupBanNotice",
    "GroupCardNotice",
    "GroupEssenceNotice",
    "GroupMsgEmojiLikeNotice",
    "BotOfflineNotice",
    "OnlineFileSendNotice",
    "PokeNotify",
    "TitleNotify",
    "GrayTipNotify",
    "GroupNameNotify",
    "InputStatusNotify",
    "ProfileLikeNotify",
    # 请求事件
    "FriendRequest",
    "GroupRequest",
]
