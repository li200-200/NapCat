#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""napcat.events 演示 —— 全部事件的实时监听与分发。

演示内容：
    1. 私聊消息：收到 ping 回 pong（引用回复）
    2. 群聊消息：打印解析结果，@机器人时回应
    3. 各类 notice：进群/退群/禁言/撤回/戳一戳/群名片/表情回应 等
    4. request：好友请求、群请求（只打印，不自动同意）
    5. meta_event：生命周期与心跳
    6. 全局兜底：任何事件都会打印一行

运行：
    python examples/demo_events.py                # 实时监听
    python examples/demo_events.py --offline      # 离线自测：喂假事件，不连 NapCat
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# 让脚本能从 examples/ 直接运行（把仓库根加入搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from napcat.events import (  # noqa: E402
    BotOfflineNotice,
    EventParser,
    FriendAddNotice,
    FriendRecallNotice,
    FriendRequest,
    GrayTipNotify,
    GroupAdminNotice,
    GroupBanNotice,
    GroupCardNotice,
    GroupDecreaseNotice,
    GroupEssenceNotice,
    GroupIncreaseNotice,
    GroupMessageEvent,
    GroupMsgEmojiLikeNotice,
    GroupNameNotify,
    GroupRecallNotice,
    GroupRequest,
    GroupUploadNotice,
    InputStatusNotify,
    MetaHeartbeatEvent,
    MetaLifecycleEvent,
    PokeNotify,
    PrivateMessageEvent,
    ProfileLikeNotify,
    QQBotEvents,
    TitleNotify,
    parse_event,
)

WS_URL = "ws://127.0.0.1:3001"
HTTP_BASE = "http://127.0.0.1:3000"
TOKEN = "pydemo_token_2024"


# ======================================================================= #
# 建客户端并注册全部处理器
# ======================================================================= #
def build_bot() -> QQBotEvents:
    bot = QQBotEvents(WS_URL, TOKEN, HTTP_BASE)

    # ---------------- 消息 ----------------
    @bot.on_private_message
    async def _on_private(event: PrivateMessageEvent):
        """私聊消息：ping -> pong，其他原样回显。"""
        text = event.plain_text
        print(f"[私聊] {event.sender.get('nickname', event.user_id)}"
              f"({event.user_id}): {text}")
        if text.strip().lower() == "ping":
            bot.reply_private(event, "pong")
        elif text.strip() == "撤回测试":
            # 先回一条，再立刻撤回，演示 delete_msg
            result = bot.reply_private(event, "这条会被撤回")
            mid = (result.get("data") or {}).get("message_id")
            if mid:
                await asyncio.sleep(1)
                ok = bot.recall(mid)
                print(f"  -> 撤回 {mid}: {'成功' if ok else '失败'}")

    @bot.on_group_message
    async def _on_group(event: GroupMessageEvent):
        """群聊消息：打印，被 @ 时回应。"""
        text = event.plain_text
        print(f"[群聊 {event.group_id}] "
              f"{event.sender.get('card') or event.sender.get('nickname')}"
              f"({event.user_id}): {text}")
        if f"@{bot.self_id}" in text or "机器人" in text:
            bot.reply_group(event, "在的")

    # ---------------- 通知：群成员变动 ----------------
    @bot.dispatcher.on(GroupIncreaseNotice)
    async def _on_group_increase(event: GroupIncreaseNotice):
        """有人进群（approve 管理员通过 / invite 被邀请）。"""
        print(f"[进群] 群 {event.group_id} 新成员 {event.user_id} "
              f"（方式: {event.sub_type}，操作者: {event.operator_id}）")

    @bot.dispatcher.on(GroupDecreaseNotice)
    async def _on_group_decrease(event: GroupDecreaseNotice):
        """有人退群/被踢。sub_type: leave 主动退 / kick 被踢 / kick_me 自己被踢。"""
        print(f"[退群] 群 {event.group_id} 成员 {event.user_id} "
              f"（方式: {event.sub_type}，操作者: {event.operator_id}）")

    @bot.dispatcher.on(GroupAdminNotice)
    async def _on_group_admin(event: GroupAdminNotice):
        """管理员变动。sub_type: set 上任 / unset 卸任。"""
        print(f"[管理员] 群 {event.group_id} 成员 {event.user_id} -> {event.sub_type}")

    @bot.dispatcher.on(GroupBanNotice)
    async def _on_group_ban(event: GroupBanNotice):
        """禁言变动。sub_type: ban 禁言 / lift_ban 解除。duration 单位秒。"""
        print(f"[禁言] 群 {event.group_id} 成员 {event.user_id} "
              f"{event.sub_type}，时长 {event.duration} 秒，操作者 {event.operator_id}")

    @bot.dispatcher.on(GroupCardNotice)
    async def _on_group_card(event: GroupCardNotice):
        """群名片变更。"""
        print(f"[群名片] 群 {event.group_id} 成员 {event.user_id}: "
              f"'{event.card_old}' -> '{event.card_new}'")

    # ---------------- 通知：消息相关 ----------------
    @bot.dispatcher.on(GroupRecallNotice)
    async def _on_group_recall(event: GroupRecallNotice):
        """群消息被撤回。"""
        print(f"[群撤回] 群 {event.group_id} 消息 {event.message_id} 被 "
              f"{event.operator_id} 撤回（原作者 {event.user_id}）")

    @bot.dispatcher.on(FriendRecallNotice)
    async def _on_friend_recall(event: FriendRecallNotice):
        """好友消息被撤回。"""
        print(f"[好友撤回] 好友 {event.user_id} 撤回了消息 {event.message_id}")

    @bot.dispatcher.on(GroupMsgEmojiLikeNotice)
    async def _on_emoji_like(event: GroupMsgEmojiLikeNotice):
        """群消息表情回应。likes 是 [{emoji_id, count}, ...]。"""
        print(f"[表情回应] 群 {event.group_id} 消息 {event.message_id} "
              f"{'新增' if event.is_add else '取消'} {event.likes}")

    @bot.dispatcher.on(PokeNotify)
    async def _on_poke(event: PokeNotify):
        """戳一戳。"""
        print(f"[戳一戳] {event.sender_id} -> {event.target_id}")

    @bot.dispatcher.on(GrayTipNotify)
    async def _on_gray_tip(event: GrayTipNotify):
        """灰条消息（可能是伪造的，user_id 是真实发送者）。"""
        print(f"[灰条] 群 {event.group_id} 内容: {str(event.content)[:80]}")

    @bot.dispatcher.on(TitleNotify)
    async def _on_title(event: TitleNotify):
        """群成员荣誉（龙王等）变更。"""
        print(f"[荣誉] 群 {event.group_id} 成员 {event.user_id} -> {event.title}")

    @bot.dispatcher.on(GroupNameNotify)
    async def _on_group_name(event: GroupNameNotify):
        """群名变更。"""
        print(f"[群名] 群 {event.group_id} 改名为 '{event.name_new}'")

    @bot.dispatcher.on(InputStatusNotify)
    async def _on_input_status(event: InputStatusNotify):
        """对方正在输入。"""
        print(f"[输入状态] {event.user_id} 在群 {event.group_id}: {event.status_text}")

    @bot.dispatcher.on(ProfileLikeNotify)
    async def _on_profile_like(event: ProfileLikeNotify):
        """名片点赞。"""
        print(f"[名片点赞] {event.operator_nick} 赞了 {event.times} 次")

    # ---------------- 通知：文件 / 好友 / 离线 ----------------
    @bot.dispatcher.on(GroupUploadNotice)
    async def _on_group_upload(event: GroupUploadNotice):
        """群文件上传。"""
        file_info = event.file or {}
        print(f"[群文件] 群 {event.group_id} {event.user_id} 上传 "
              f"{file_info.get('name')} ({file_info.get('size')} 字节)")

    @bot.dispatcher.on(GroupEssenceNotice)
    async def _on_essence(event: GroupEssenceNotice):
        """精华消息。sub_type: add 设为精华 / delete 取消精华。"""
        print(f"[精华] 群 {event.group_id} 消息 {event.message_id} -> {event.sub_type}")

    @bot.dispatcher.on(FriendAddNotice)
    async def _on_friend_add(event: FriendAddNotice):
        """新好友。"""
        print(f"[新好友] {event.user_id}")

    @bot.dispatcher.on(BotOfflineNotice)
    async def _on_bot_offline(event: BotOfflineNotice):
        """机器人掉线。"""
        print(f"[掉线] {event.tag}: {event.message}")

    # ---------------- 请求 ----------------
    @bot.on_request("friend")
    async def _on_friend_request(event: FriendRequest):
        """好友请求。自动同意用 bot.call("set_friend_add_request", flag=..., approve=True)。"""
        print(f"[好友请求] {event.user_id}: {event.comment}  flag={event.flag}")

    @bot.on_request("group")
    async def _on_group_request(event: GroupRequest):
        """加群/邀请请求。sub_type: add 主动加群 / invite 被邀请。"""
        print(f"[群请求] 群 {event.group_id} 用户 {event.user_id} "
              f"({event.sub_type}): {event.comment}  flag={event.flag}")

    # ---------------- 元事件 ----------------
    @bot.on_meta("lifecycle")
    async def _on_lifecycle(event: MetaLifecycleEvent):
        """生命周期：connect 连接建立 / enable 启用 / disable 禁用。"""
        print(f"[生命周期] {event.sub_type}")

    @bot.on_meta("heartbeat")
    async def _on_heartbeat(event: MetaHeartbeatEvent):
        """心跳：status 里是 online / good。"""
        status = event.status or {}
        print(f"[心跳] online={status.get('online')} good={status.get('good')}")

    # ---------------- 全局兜底 ----------------
    @bot.on_any
    async def _on_any(event):
        """任何事件都会走到这里，用于调试。"""
        second = (getattr(event, "notice_type", None)
                  or getattr(event, "request_type", None)
                  or getattr(event, "meta_event_type", None)
                  or getattr(event, "message_type", None) or "")
        sub = getattr(event, "sub_type", None) or ""
        print(f"[事件] {type(event).__name__}  post_type={event.post_type} "
              f"{second}/{sub}")

    return bot


# ======================================================================= #
# 离线自测：喂假事件，验证解析与分发
# ======================================================================= #
FAKE_EVENTS = [
    {
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "self_id": 2108172573, "user_id": 1544629526, "time": 1794000000,
        "message_id": 1001, "message_seq": 1001, "real_id": 1001, "real_seq": "10",
        "raw_message": "ping", "font": 14, "message_format": "array",
        "sender": {"user_id": 1544629526, "nickname": "一方通行", "card": ""},
        "message": [{"type": "text", "data": {"text": "ping"}}],
    },
    {
        "post_type": "message", "message_type": "group", "sub_type": "normal",
        "self_id": 2108172573, "user_id": 540682425, "group_id": 856296858,
        "group_name": "鸽鸽内测", "time": 1794000001, "message_id": 1002,
        "message_seq": 1002, "real_id": 1002, "real_seq": "11",
        "raw_message": "大家好", "font": 14, "message_format": "array",
        "sender": {"user_id": 540682425, "nickname": "科技月月", "card": "月月"},
        "message": [{"type": "text", "data": {"text": "大家好"}}],
    },
    {
        "post_type": "notice", "notice_type": "group_increase", "sub_type": "approve",
        "self_id": 2108172573, "time": 1794000002, "group_id": 856296858,
        "user_id": 123456789, "operator_id": 2108172573,
    },
    {
        "post_type": "notice", "notice_type": "group_decrease", "sub_type": "kick",
        "self_id": 2108172573, "time": 1794000003, "group_id": 856296858,
        "user_id": 123456789, "operator_id": 2108172573,
    },
    {
        "post_type": "notice", "notice_type": "group_ban", "sub_type": "ban",
        "self_id": 2108172573, "time": 1794000004, "group_id": 856296858,
        "user_id": 123456789, "operator_id": 2108172573, "duration": 600,
    },
    {
        "post_type": "notice", "notice_type": "group_card", "sub_type": "",
        "self_id": 2108172573, "time": 1794000005, "group_id": 856296858,
        "user_id": 123456789, "card_new": "新名片", "card_old": "旧名片",
    },
    {
        "post_type": "notice", "notice_type": "group_recall", "sub_type": "",
        "self_id": 2108172573, "time": 1794000006, "group_id": 856296858,
        "user_id": 123456789, "operator_id": 2108172573, "message_id": 5555,
    },
    {
        "post_type": "notice", "notice_type": "notify", "sub_type": "poke",
        "self_id": 2108172573, "time": 1794000007, "sender_id": 1544629526,
        "target_id": 2108172573, "user_id": 1544629526,
    },
    {
        "post_type": "notice", "notice_type": "group_msg_emoji_like",
        "sub_type": "", "self_id": 2108172573, "time": 1794000008,
        "group_id": 856296858, "user_id": 123456789, "message_id": 7777,
        "likes": [{"emoji_id": "128077", "count": 1}], "is_add": True,
    },
    {
        "post_type": "notice", "notice_type": "group_upload", "sub_type": "",
        "self_id": 2108172573, "time": 1794000009, "group_id": 856296858,
        "user_id": 123456789,
        "file": {"id": "f1", "name": "test.zip", "size": 1024, "busid": 102},
    },
    {
        "post_type": "notice", "notice_type": "essence", "sub_type": "add",
        "self_id": 2108172573, "time": 1794000010, "group_id": 856296858,
        "user_id": 123456789, "operator_id": 2108172573, "message_id": 8888,
        "sender_id": 123456789,
    },
    {
        "post_type": "notice", "notice_type": "notify", "sub_type": "title",
        "self_id": 2108172573, "time": 1794000011, "group_id": 856296858,
        "user_id": 123456789, "title": "龙王",
    },
    {
        "post_type": "notice", "notice_type": "notify", "sub_type": "group_name",
        "self_id": 2108172573, "time": 1794000012, "group_id": 856296858,
        "user_id": 123456789, "name_new": "新群名",
    },
    {
        "post_type": "notice", "notice_type": "friend_add", "sub_type": "",
        "self_id": 2108172573, "time": 1794000013, "user_id": 987654321,
    },
    {
        "post_type": "request", "request_type": "friend", "sub_type": "",
        "self_id": 2108172573, "time": 1794000014, "user_id": 987654321,
        "comment": "我是xxx", "flag": "flag_friend_1",
    },
    {
        "post_type": "request", "request_type": "group", "sub_type": "add",
        "self_id": 2108172573, "time": 1794000015, "group_id": 856296858,
        "user_id": 987654321, "comment": "求进群", "flag": "flag_group_1",
    },
    {
        "post_type": "meta_event", "meta_event_type": "lifecycle",
        "sub_type": "connect", "self_id": 2108172573, "time": 1794000016,
    },
    {
        "post_type": "meta_event", "meta_event_type": "heartbeat",
        "sub_type": "", "self_id": 2108172573, "time": 1794000017,
        "status": {"online": True, "good": True}, "interval": 30000,
    },
]


async def run_offline() -> int:
    """离线模式：不连 NapCat，直接喂假事件，验证解析 + 分发。"""
    bot = build_bot()
    # 离线时不真的发消息，把 call 换成记录器
    sent: list[tuple[str, dict]] = []

    def fake_call(action: str, **params):
        sent.append((action, params))
        return {"status": "ok", "retcode": 0,
                "data": {"message_id": 9000 + len(sent)}}

    bot.call = fake_call  # type: ignore[assignment]
    bot.self_id = 2108172573

    print("=" * 66)
    print("离线自测：解析并分发 18 条假事件")
    print("=" * 66)

    parsed_types = []
    for raw in FAKE_EVENTS:
        event = parse_event(raw)
        parsed_types.append(type(event).__name__)
        await bot.dispatcher.dispatch(event)

    print("\n" + "=" * 66)
    print("解析结果")
    print("=" * 66)
    ok = True
    for raw, name in zip(FAKE_EVENTS, parsed_types):
        second = (raw.get("notice_type") or raw.get("request_type")
                  or raw.get("meta_event_type") or raw.get("message_type") or "")
        tag = f"{raw.get('post_type')}/{second}/{raw.get('sub_type') or '-'}"
        print(f"  {tag:<38} -> {name}")
        if name in ("BaseEvent", "BaseNotice", "UnknownEvent"):
            ok = False

    print("\n" + "=" * 66)
    print(f"主动调用记录: {len(sent)} 次")
    for action, params in sent:
        brief = {k: v for k, v in params.items() if k != "message"}
        print(f"  {action}  {brief}")
    print("=" * 66)
    print("全部事件解析正确" if ok else "存在未识别事件")
    return 0 if ok else 1


def main() -> int:
    if "--offline" in sys.argv:
        return asyncio.run(run_offline())

    bot = build_bot()
    print("=" * 66)
    print("实时监听中，Ctrl+C 退出")
    print("=" * 66)
    bot.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
