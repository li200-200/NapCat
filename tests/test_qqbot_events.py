#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qqbot_events.py 的离线单测 —— 不连 NapCat、不发消息。

覆盖：
    1. 每个事件类型都能解析成正确的数据类
    2. 未知事件退化成 BaseEvent 而不抛异常
    3. 同一事件的多种 sub_type 落到同一个类
    4. 分发器优先级：具体类 > 事件族 > 全局兜底
    5. 同步与异步处理器都能被正确 await
    6. 处理器抛异常不影响其他处理器
    7. 消息段拍平、便捷属性、时间转换
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import napcat.events as q  # noqa: E402
from napcat.events import (  # noqa: E402
    BaseEvent,
    EventDispatcher,
    EventParser,
    GroupBanNotice,
    GroupDecreaseNotice,
    GroupMessageEvent,
    GroupRequest,
    PrivateMessageEvent,
    parse_event,
    segments_to_text,
)

FAILS: list[str] = []


def check(name: str, passed: bool) -> bool:
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if not passed:
        FAILS.append(name)
    return passed


# ======================================================================= #
def case_all_events_parse() -> bool:
    """每个注册项都能解析出对应类，且不是兜底类。"""
    ok = True
    for (post_type, second, sub_type), cls in sorted(
            EventParser.REGISTRY.items(), key=lambda x: str(x[0])):
        if cls.__name__ in ("BaseNotice", "UnknownEvent"):
            continue
        raw = {"post_type": post_type, "time": 1794000000, "self_id": 1}
        if post_type == "notice":
            raw["notice_type"] = second
        elif post_type == "request":
            raw["request_type"] = second
        elif post_type == "meta_event":
            raw["meta_event_type"] = second
        elif post_type in ("message", "message_sent"):
            raw["message_type"] = second
            raw["message"] = []
        if sub_type:
            raw["sub_type"] = sub_type

        event = parse_event(raw)
        good = type(event) is cls
        if not good:
            print(f"    {post_type}/{second}/{sub_type} -> {type(event).__name__}"
                  f" (期望 {cls.__name__})")
        ok = good and ok
    return check(f"全部 {len(EventParser.REGISTRY)} 个注册项解析正确", ok)


def case_shared_subtypes() -> bool:
    """同一事件的多种 sub_type 落到同一个类。"""
    cases = [
        ("notice", "group_decrease", "leave", GroupDecreaseNotice),
        ("notice", "group_decrease", "kick", GroupDecreaseNotice),
        ("notice", "group_decrease", "kick_me", GroupDecreaseNotice),
        ("notice", "group_ban", "ban", GroupBanNotice),
        ("notice", "group_ban", "lift_ban", GroupBanNotice),
        ("request", "group", "add", GroupRequest),
        ("request", "group", "invite", GroupRequest),
    ]
    ok = True
    for post_type, second, sub_type, expected in cases:
        raw = {"post_type": post_type, "sub_type": sub_type, "time": 1, "self_id": 1}
        raw["notice_type" if post_type == "notice" else "request_type"] = second
        got = type(parse_event(raw))
        ok = check(f"{second}/{sub_type} -> {expected.__name__}",
                   got is expected) and ok
    return ok


def case_unknown_fallback() -> bool:
    """未知事件退化成 BaseEvent，不抛异常。"""
    ok = True
    ok = check("完全未知的 post_type",
               type(parse_event({"post_type": "weird"})) is BaseEvent) and ok
    ok = check("notice 未知 notice_type",
               isinstance(parse_event({"post_type": "notice",
                                       "notice_type": "nope"}),
                          BaseEvent)) and ok
    ok = check("空 dict", type(parse_event({})) is BaseEvent) and ok
    ok = check("JSON 字符串输入",
               isinstance(parse_event('{"post_type": "notice",'
                                      ' "notice_type": "friend_add"}'),
                          BaseEvent)) and ok
    return ok


def case_fields_populated() -> bool:
    """字段真的被填进去了，而不是全默认值。"""
    raw = {
        "post_type": "message", "message_type": "group", "sub_type": "normal",
        "self_id": 2108172573, "user_id": 540682425, "group_id": 856296858,
        "group_name": "鸽鸽内测", "time": 1794000001, "message_id": 1002,
        "message_seq": 1002, "real_id": 1002, "real_seq": "11",
        "raw_message": "大家好", "font": 14, "message_format": "array",
        "sender": {"user_id": 540682425, "nickname": "科技月月", "card": "月月"},
        "message": [{"type": "text", "data": {"text": "大家好"}}],
    }
    e = parse_event(raw)
    ok = True
    ok = check("类型是 GroupMessageEvent", isinstance(e, GroupMessageEvent)) and ok
    ok = check("group_id 正确", e.group_id == 856296858) and ok
    ok = check("group_name 正确", e.group_name == "鸽鸽内测") and ok
    ok = check("user_id 正确", e.user_id == 540682425) and ok
    ok = check("message_id 正确", e.message_id == 1002) and ok
    ok = check("sender 是 dict", isinstance(e.sender, dict)) and ok
    ok = check("plain_text 拍平正确", e.plain_text == "大家好") and ok
    ok = check("datetime 可转换", e.datetime.year == 2026 or e.datetime.year > 2000) and ok
    return ok


def case_private_message_plain_text() -> bool:
    """私聊消息的 plain_text 能处理图片等非文本段。"""
    raw = {
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "self_id": 1, "user_id": 2, "time": 1794000000, "message_id": 1,
        "sender": {"nickname": "x"},
        "message": [
            {"type": "text", "data": {"text": "看图 "}},
            {"type": "image", "data": {"file": "a.jpg"}},
            {"type": "face", "data": {"id": "14"}},
        ],
    }
    e = parse_event(raw)
    ok = isinstance(e, PrivateMessageEvent)
    ok = check("类型是 PrivateMessageEvent", ok) and ok
    ok = check("plain_text 含占位符", e.plain_text == "看图 [图片][表情14]") and ok
    return ok


def case_segments_to_text() -> bool:
    ok = True
    ok = check("纯字符串原样返回", segments_to_text("hi") == "hi") and ok
    ok = check("非列表返回空串", segments_to_text(None) == "") and ok
    ok = check("at 全体",
               segments_to_text([{"type": "at", "data": {"qq": "all"}}])
               == "@全体成员") and ok
    ok = check("at 指定人",
               segments_to_text([{"type": "at", "data": {"qq": "123"}}])
               == "@123") and ok
    ok = check("reply 段被跳过",
               segments_to_text([{"type": "reply", "data": {"id": "1"}},
                                 {"type": "text", "data": {"text": "x"}}]) == "x") and ok
    ok = check("语音占位",
               segments_to_text([{"type": "record", "data": {}}]) == "[语音]") and ok
    return ok


# ======================================================================= #
def case_dispatcher_priority() -> bool:
    """分发优先级：具体类 > 事件族 > 全局兜底。"""
    d = EventDispatcher()
    order: list[str] = []

    @d.on(GroupBanNotice)
    def h_class(e):
        order.append("class")

    @d.on_family("notice", "group_ban")
    def h_family(e):
        order.append("family")

    @d.on_family("notice", None)
    def h_family_all(e):
        order.append("family_all")

    @d.on_any()
    def h_any(e):
        order.append("any")

    event = parse_event({"post_type": "notice", "notice_type": "group_ban",
                         "sub_type": "ban", "time": 1, "self_id": 1})
    asyncio.run(d.dispatch(event))

    ok = check("四个处理器都被调用", len(order) == 4)
    ok = check("具体类最先", order[0] == "class") and ok
    ok = check("事件族其次", order[1] == "family") and ok
    ok = check("族兜底再次", order[2] == "family_all") and ok
    ok = check("全局兜底最后", order[3] == "any") and ok
    return ok


def case_async_handlers() -> bool:
    """异步处理器会被正确 await。"""
    d = EventDispatcher()
    hits: list[str] = []

    @d.on_any()
    async def h_async(e):
        await asyncio.sleep(0)
        hits.append("async")

    @d.on_any()
    def h_sync(e):
        hits.append("sync")

    asyncio.run(d.dispatch(parse_event({"post_type": "notice",
                                        "notice_type": "friend_add",
                                        "time": 1, "self_id": 1})))
    ok = check("同步与异步都执行", hits == ["async", "sync"])
    return ok


def case_handler_exception_isolated() -> bool:
    """一个处理器抛异常，不影响后续处理器。"""
    d = EventDispatcher()
    hits: list[str] = []

    @d.on_any()
    def h_boom(e):
        raise RuntimeError("故意炸掉")

    @d.on_any()
    def h_after(e):
        hits.append("after")

    asyncio.run(d.dispatch(parse_event({"post_type": "notice",
                                        "notice_type": "friend_add",
                                        "time": 1, "self_id": 1})))
    return check("异常后仍执行后续处理器", hits == ["after"])


def case_registry_coverage() -> bool:
    """注册表覆盖了 NapCat 全部事件族。"""
    expected_families = {
        "meta_event", "message", "message_sent", "notice", "request",
    }
    families = {k[0] for k in EventParser.REGISTRY}
    ok = check(f"覆盖 5 个 post_type (实际 {sorted(families)})",
               expected_families <= families)

    expected_notice = {
        "friend_add", "friend_recall", "group_recall", "group_upload",
        "group_admin", "group_decrease", "group_increase", "group_ban",
        "group_card", "essence", "group_msg_emoji_like", "bot_offline",
        "online_file_send", "notify",
    }
    actual_notice = {k[1] for k in EventParser.REGISTRY if k[0] == "notice"}
    missing = expected_notice - actual_notice
    ok = check(f"notice 类型齐全 (缺 {missing or '无'})", not missing) and ok

    ok = check("request 有 friend/group",
               {"friend", "group"} <= {k[1] for k in EventParser.REGISTRY
                                       if k[0] == "request"}) and ok
    ok = check("meta_event 有 lifecycle/heartbeat",
               {"lifecycle", "heartbeat"} <= {k[1] for k in EventParser.REGISTRY
                                              if k[0] == "meta_event"}) and ok
    return ok


def case_dataclass_defaults() -> bool:
    """数据类字段都有安全默认值，可以无参构造。"""
    ok = True
    for name in q.__all__:
        cls = getattr(q, name, None)
        if not isinstance(cls, type) or not issubclass(cls, BaseEvent):
            continue
        try:
            cls()
        except TypeError as exc:
            ok = check(f"{name} 可无参构造", False)
            print(f"    {exc}")
    ok = check("全部事件类可无参构造", ok) and ok
    return ok


def main() -> int:
    cases = [
        ("全部事件解析", case_all_events_parse),
        ("多 sub_type 共用类", case_shared_subtypes),
        ("未知事件兜底", case_unknown_fallback),
        ("字段填充", case_fields_populated),
        ("私聊 plain_text", case_private_message_plain_text),
        ("消息段拍平", case_segments_to_text),
        ("分发优先级", case_dispatcher_priority),
        ("异步处理器", case_async_handlers),
        ("异常隔离", case_handler_exception_isolated),
        ("注册表覆盖", case_registry_coverage),
        ("数据类默认值", case_dataclass_defaults),
    ]

    summary = []
    for name, fn in cases:
        print(f"\n=== {name} ===")
        summary.append((name, fn()))

    print("\n" + "=" * 54)
    for name, passed in summary:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print("=" * 54)
    all_ok = all(p for _, p in summary)
    print("全部通过" if all_ok else f"失败 {len(FAILS)} 项")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
