#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
私聊消息自动回复机器人 —— API 模块 + 事件模块 结合示例

流程：
    WebSocket 收到私聊事件
        -> EventParser 解析成 PrivateMessageEvent
        -> 打印该事件返回的全部字段
        -> 按字段内容决定回复什么
        -> 调 HTTP API 发回去（可引用原消息，可撤回）

两个模块的分工：
    napcat.events  负责「收」：WebSocket 长连接 + 事件解析 + 分发
    napcat.api     负责「发」：HTTP API，含易语言风格的撤回三元组

运行：
    python examples/private_reply_bot.py

配置在文件底部的 CONFIG 里，改完直接跑。
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import Path

# 让脚本能从 examples/ 直接运行（把仓库根加入搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from napcat.api import QQBot, Ref  # noqa: E402
from napcat.events import (  # noqa: E402
    FriendRecallNotice,
    PokeNotify,
    PrivateMessageEvent,
    PrivateMessageSentEvent,
    QQBotEvents,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("私聊机器人")


# ======================================================================= #
# 配置
# ======================================================================= #
CONFIG = {
    # NapCat 连接参数
    "ws_url": "ws://127.0.0.1:3001",      # 收事件
    "http_base": "http://127.0.0.1:3000",  # 发消息
    "token": "pydemo_token_2024",

    # 白名单：留空表示所有人都回；填了 QQ 号就只回这些人
    "allow_list": [],

    # 回复前延迟（秒），避免秒回显得像机器
    "reply_delay": 0.3,

    # 是否引用原消息回复
    "quote_reply": True,

    # 是否打印事件全部字段（调试用，正式跑可以关掉）
    "dump_fields": True,
}


# ======================================================================= #
# 一、打印事件返回的全部字段
# ======================================================================= #
def dump_event(event: PrivateMessageEvent) -> None:
    """把私聊事件返回的每个字段都打印出来。

    PrivateMessageEvent 的字段（来自 NapCat 的 initializeMessage）：
        self_id        机器人 QQ
        user_id        发送者 QQ
        time           消息时间戳（unix 秒）
        message_id     消息 ID（撤回、引用回复都用它）
        message_seq    消息序号
        real_id        真实消息 ID
        real_seq       真实序号
        message_type   private / group
        sender         发送者信息字典 {user_id, nickname, card, role?}
        raw_message    原始消息字符串
        font           字体
        sub_type       friend（好友）/ group（临时会话）
        message        消息段数组
        message_format array / string
        post_type      message / message_sent
    """
    print("\n" + "=" * 70)
    print("收到私聊消息，事件返回的字段：")
    print("=" * 70)

    for f in dataclass_fields(event):
        值 = getattr(event, f.name, None)
        print(f"  {f.name:<16} = {值!r}")

    # 派生信息：不是协议字段，但常用来做判断
    print("-" * 70)
    print(f"  {'plain_text':<16} = {event.plain_text!r}   （消息段拍平后的文本）")
    print(f"  {'datetime':<16} = {event.datetime}   （time 转本地时间）")
    print(f"  {'sender.nickname':<16} = {(event.sender or {}).get('nickname')!r}")
    print(f"  {'sender.card':<16} = {(event.sender or {}).get('card')!r}")
    print("=" * 70 + "\n")


# ======================================================================= #
# 二、回复规则
# ======================================================================= #
# 按顺序匹配，命中第一条就回复并结束。
#   match   : exact 完全相等 / contains 包含 / prefix 前缀 / regex 正则
#   reply   : 回复模板，可用 {nickname} {user_id} {time} {text} {1} {2} 等占位符
#   action  : 特殊动作，见下面 _handle_action
RULES = [
    {
        "name": "打招呼",
        "match": "exact",
        "pattern": "你好",
        "reply": "你好，{nickname}！我是自动回复机器人。",
    },
    {
        "name": "ping",
        "match": "exact",
        "pattern": "ping",
        "reply": "pong",
    },
    {
        "name": "查自己的信息",
        "match": "exact",
        "pattern": "我的信息",
        # 直接用事件返回的字段拼装
        "reply": (
            "你的 QQ：{user_id}\n"
            "昵称：{nickname}\n"
            "群名片：{card}\n"
            "会话类型：{sub_type}\n"
            "这条消息的 message_id：{message_id}\n"
            "发送时间：{time_text}"
        ),
    },
    {
        "name": "复读",
        "match": "prefix",
        "pattern": "复读 ",
        "reply": "{1}",
    },
    {
        "name": "加法",
        "match": "regex",
        "pattern": r"^(\d+)\s*\+\s*(\d+)$",
        "reply": "{1} + {2} = {sum}",
    },
    {
        "name": "撤回演示",
        "match": "exact",
        "pattern": "撤回测试",
        # 特殊动作：先回一条，再撤回，演示易语言三元组
        "action": "send_then_recall",
    },
    {
        "name": "帮助",
        "match": "contains",
        "pattern": "帮助",
        "reply": (
            "可用指令：\n"
            "  你好        —— 打个招呼\n"
            "  ping        —— 测连通\n"
            "  我的信息    —— 返回你的资料和本条消息字段\n"
            "  复读 xxx    —— 复读机\n"
            "  12+30       —— 加法\n"
            "  撤回测试    —— 发一条再撤回"
        ),
    },
]


# ======================================================================= #
# 三、机器人主体
# ======================================================================= #
class PrivateReplyBot:
    """私聊自动回复机器人。

    同时持有两个客户端：
        self.events  收事件（WebSocket）
        self.api     发消息（HTTP，支持撤回三元组）
    """

    def __init__(self, config: dict) -> None:
        self.cfg = config

        # 收事件
        self.events = QQBotEvents(
            ws_url=config["ws_url"],
            token=config["token"],
            http_base=config["http_base"],
        )

        # 发消息（易语言风格，带 Ref 出参）
        self.api = QQBot(
            base_url=config["http_base"],
            access_token=config["token"],
        )

        self.self_id = 0
        self._register_handlers()

    # ------------------------------------------------------------------ #
    # 注册事件处理器
    # ------------------------------------------------------------------ #
    def _register_handlers(self) -> None:
        # 别人发来的私聊
        self.events.dispatcher.on(PrivateMessageEvent)(self.on_private_message)

        # 自己发出的私聊（用于观察回复是否成功，不参与规则匹配）
        self.events.dispatcher.on(PrivateMessageSentEvent)(
            self.on_private_sent)

        # 好友撤回消息
        self.events.dispatcher.on(FriendRecallNotice)(self.on_friend_recall)

        # 戳一戳
        self.events.dispatcher.on(PokeNotify)(self.on_poke)

    # ------------------------------------------------------------------ #
    # 主逻辑：收到私聊 -> 看字段 -> 决定回复
    # ------------------------------------------------------------------ #
    async def on_private_message(self, event: PrivateMessageEvent) -> None:
        # 1. 拿到机器人自己的 QQ（首次事件时补上）
        if not self.self_id:
            self.self_id = event.self_id or 0

        # 2. 打印事件返回的全部字段
        if self.cfg["dump_fields"]:
            dump_event(event)

        # 3. 用返回的字段做基础判断
        user_id = event.user_id
        nickname = (event.sender or {}).get("nickname") or str(user_id)
        card = (event.sender or {}).get("card") or ""
        text = event.plain_text
        sub_type = event.sub_type

        # 忽略自己发的（防止回复内容再次触发规则）
        if self.self_id and user_id == self.self_id:
            log.debug("忽略自己发出的消息")
            return

        # 白名单过滤
        if self.cfg["allow_list"] and user_id not in self.cfg["allow_list"]:
            log.info("非白名单用户 %s(%s)，忽略", nickname, user_id)
            return

        # 临时会话（sub_type == group）也可以区别对待
        if sub_type == "group":
            log.info("收到临时会话消息，来源群 %s", getattr(event, "group_id", 0))

        log.info("[私聊] %s(%s): %s", nickname, user_id, text)

        # 4. 按规则匹配并回复
        await self._dispatch_rules(event)

    async def _dispatch_rules(self, event: PrivateMessageEvent) -> None:
        """遍历规则表，命中第一条就执行。"""
        text = event.plain_text
        ctx = self._build_context(event)

        for rule in RULES:
            hit = self._match(rule, text)
            if hit is None:
                continue

            log.info("命中规则「%s」", rule["name"])

            # 特殊动作
            action = rule.get("action")
            if action:
                await self._handle_action(action, event)
                return

            # 普通回复：渲染模板
            reply_text = self._render(rule, text, hit, ctx)
            await self._reply(event, reply_text)
            return

        # 没命中任何规则：不回复，只记日志
        log.info("未命中规则，不回复")

    @staticmethod
    def _match(rule: dict, text: str):
        """按 match 类型判断是否命中。命中返回匹配信息，否则返回 None。"""
        import re

        kind = rule["match"]
        pattern = rule["pattern"]
        stripped = text.strip()

        if kind == "exact":
            return True if stripped == pattern else None
        if kind == "contains":
            return True if pattern in text else None
        if kind == "prefix":
            return True if stripped.startswith(pattern) else None
        if kind == "suffix":
            return True if stripped.endswith(pattern) else None
        if kind == "regex":
            return re.search(pattern, stripped, re.S)
        return None

    @staticmethod
    def _build_context(event: PrivateMessageEvent) -> dict:
        """把事件字段整理成模板占位符的取值表。"""
        sender = event.sender or {}
        return {
            "user_id": event.user_id,
            "nickname": sender.get("nickname") or str(event.user_id),
            "card": sender.get("card") or "",
            "message_id": event.message_id,
            "message_seq": event.message_seq,
            "real_id": event.real_id,
            "sub_type": event.sub_type,
            "message_type": event.message_type,
            "time": event.time,
            "time_text": event.datetime.strftime("%Y-%m-%d %H:%M:%S"),
            "self_id": event.self_id,
            "raw_message": event.raw_message,
        }

    @staticmethod
    def _render(rule: dict, text: str, hit, ctx: dict) -> str:
        """渲染回复模板。

        支持三类占位符：
            {1} {2} ...   正则分组；prefix 规则下 {1} 是前缀之后的内容
            {sum}         所有数字分组之和
            {text} {nickname} {user_id} ...   上下文里的字段
        """
        out = rule["reply"]
        stripped = text.strip()

        # 1) 先收集分组内容
        groups: list[str] = []
        if rule["match"] == "regex" and hasattr(hit, "groups"):
            groups = [g if g is not None else "" for g in hit.groups()]
        elif rule["match"] == "prefix":
            groups = [stripped[len(rule["pattern"]):].strip()]

        # 2) 替换 {1} {2} ...
        for i, g in enumerate(groups, start=1):
            out = out.replace("{%d}" % i, g)

        # 3) 全数字分组时提供求和
        if groups and all(g.isdigit() for g in groups if g):
            out = out.replace("{sum}", str(sum(int(g) for g in groups if g)))

        # 4) 替换上下文占位符
        for k, v in ctx.items():
            out = out.replace("{%s}" % k, str(v))
        out = out.replace("{text}", text)

        return out

    # ------------------------------------------------------------------ #
    # 回复 / 特殊动作
    # ------------------------------------------------------------------ #
    async def _reply(self, event: PrivateMessageEvent, text: str) -> None:
        """引用原消息回复。"""
        if self.cfg["reply_delay"]:
            await asyncio.sleep(self.cfg["reply_delay"])

        result = self.events.reply_private(
            event, text, quote=self.cfg["quote_reply"])
        if result.get("retcode") == 0:
            mid = (result.get("data") or {}).get("message_id")
            log.info("已回复 -> %s（message_id=%s）", event.user_id, mid)
        else:
            log.error("回复失败: %s", result.get("message") or result)

    async def _handle_action(self, action: str,
                             event: PrivateMessageEvent) -> None:
        """特殊动作。"""
        if action == "send_then_recall":
            await self._send_then_recall(event)
        else:
            log.warning("未知动作: %s", action)

    async def _send_then_recall(self, event: PrivateMessageEvent) -> None:
        """演示易语言三元组：发一条，拿 time/Random/Req，再撤回。

        这里用 QQBot（API 模块）而不是 events.reply_private，
        因为只有 send_friend_msg 会返回撤回三元组。
        """
        random = Ref()
        req = Ref()
        t = self.api.send_friend_msg(
            event.user_id, "这条消息 2 秒后会被撤回", random, req)

        if not t:
            log.error("发送失败，无法演示撤回")
            return

        log.info("已发送 time=%s Random=%s Req=%s", t, random.value, req.value)

        await asyncio.sleep(2)

        ok = self.api.recall_friend_msg(t, random.value, req.value)
        log.info("撤回结果：%s", "成功" if ok else "失败")

    # ------------------------------------------------------------------ #
    # 其他事件（不回复，只记录）
    # ------------------------------------------------------------------ #
    async def on_private_sent(self, event: PrivateMessageSentEvent) -> None:
        """自己发出的私聊。用来确认回复真的送达了。"""
        log.debug("[自发] %s: %s", event.user_id, event.plain_text)

    async def on_friend_recall(self, event: FriendRecallNotice) -> None:
        """好友撤回了消息。"""
        log.info("[好友撤回] %s 撤回了消息 %s", event.user_id, event.message_id)

    async def on_poke(self, event: PokeNotify) -> None:
        """被戳一戳，戳回去。"""
        log.info("[戳一戳] %s -> %s", event.sender_id, event.target_id)
        if event.target_id and self.self_id and event.target_id == self.self_id:
            # 用 API 模块的 send_poke 戳回去
            try:
                self.api.send_poke(str(event.sender_id))
                log.info("已戳回 %s", event.sender_id)
            except Exception as exc:
                log.error("戳回失败: %r", exc)

    # ------------------------------------------------------------------ #
    # 启动
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """阻塞运行，Ctrl+C 退出。"""
        info = self.api.call("get_login_info") or {}
        if info.get("user_id"):
            self.self_id = int(info["user_id"])
            log.info("已登录：%s（%s）", info.get("user_id"),
                     info.get("nickname"))
        else:
            log.warning("拿不到登录信息，检查 NapCat 是否启动、token 是否正确")

        log.info("开始监听私聊，Ctrl+C 退出")
        self.events.run()


# ======================================================================= #
# 入口
# ======================================================================= #
def main() -> int:
    bot = PrivateReplyBot(CONFIG)
    bot.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
