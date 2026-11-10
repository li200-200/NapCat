#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for qqbot_en.py -- no NapCat, no network.

Covers:
  * send_friend_msg returns the recall time as text
  * random / req are written back through the Ref out-params
  * recall resolves message_id from triple, from time alone, or explicit id
  * optional params are omitted from the wire payload when left as None
  * non-zero retcode raises QQBotError
  * generated methods expose the extracted parameter names
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from napcat.api import QQBot, QQBotError, Ref  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Records every call and answers with canned OneBot envelopes."""

    def __init__(self, fail_actions: set[str] | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []
        self.fail_actions = fail_actions or set()
        self._next_id = 500000
        self._store: dict[int, tuple[int, int, int]] = {}

    def post(self, url: str, json: dict, timeout: int) -> FakeResponse:  # noqa: A002
        action = url.rsplit("/", 1)[-1]
        self.calls.append((action, json))

        if action in self.fail_actions:
            return FakeResponse({"status": "failed", "retcode": 200,
                                 "message": "boom", "data": None})

        if action in ("send_private_msg", "send_group_msg"):
            mid = self._next_id
            self._next_id += 1
            ts = 1794000000 + (mid % 1000)
            self._store[mid] = (ts, mid, mid)
            return FakeResponse({"status": "ok", "retcode": 0,
                                 "data": {"message_id": mid}})

        if action == "get_msg":
            mid = int(json["message_id"])
            triple = self._store.get(mid)
            if not triple:
                return FakeResponse({"status": "failed", "retcode": 200,
                                     "message": "not found", "data": None})
            ts, seq, real = triple
            return FakeResponse({"status": "ok", "retcode": 0,
                                 "data": {"time": ts, "message_id": mid,
                                          "message_seq": seq, "real_id": real}})

        if action == "delete_msg":
            mid = int(json["message_id"])
            if mid in self._store:
                del self._store[mid]
                return FakeResponse({"status": "ok", "retcode": 0, "data": None})
            return FakeResponse({"status": "failed", "retcode": 200,
                                 "message": "Recall failed", "data": None})

        return FakeResponse({"status": "ok", "retcode": 0, "data": {}})


def make_bot(fail: set[str] | None = None) -> tuple[QQBot, FakeSession]:
    bot = QQBot("http://127.0.0.1:3000", "tok")
    fake = FakeSession(fail)
    bot._session = fake  # type: ignore[assignment]
    return bot, fake


def case_send_and_recall() -> bool:
    bot, fake = make_bot()
    random, req = Ref(), Ref()
    t = bot.send_friend_msg(1544629526, "hello", random, req)

    ok = True
    checks = [
        ("returns str", isinstance(t, str)),
        ("non-empty", t != ""),
        ("returns get_msg time", int(t) == 1794000000 + 500000 % 1000),
        ("random written back", random.value == 500000),
        ("req written back", req.value == 500000),
        ("friend_qq mapped to user_id", fake.calls[0][1]["user_id"] == 1544629526),
        ("message sent verbatim", fake.calls[0][1]["message"] == "hello"),
        ("None options stripped", "auto_escape" not in fake.calls[0][1]),
        ("get_msg was called", any(a == "get_msg" for a, _ in fake.calls)),
    ]
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed

    ok = _check("recall by triple", bot.recall_friend_msg(t, random.value, req.value)) and ok
    return ok


def case_recall_by_time_only() -> bool:
    bot, _ = make_bot()
    t = bot.send_friend_msg(1544629526, "time only")
    return _check("recall by time alone", bot.recall_friend_msg(t))


def case_recall_by_explicit_id() -> bool:
    bot, fake = make_bot()
    bot.send_friend_msg(1544629526, "explicit")
    sent_id = fake.calls[0][1] and fake._store and list(fake._store)[0]
    return _check("recall by explicit message_id",
                  bot.recall(time=0, random=0, req=0, message_id=sent_id))


def case_segments() -> bool:
    bot, fake = make_bot()
    segs = [{"type": "text", "data": {"text": "a"}},
            {"type": "face", "data": {"id": "14"}}]
    t = bot.send_friend_msg(1544629526, segs)
    ok = _check("segment list passes through",
                fake.calls[0][1]["message"] == segs and t != "")
    return ok


def case_failure() -> bool:
    bot, _ = make_bot({"send_private_msg"})
    random, req = Ref(), Ref()
    t = bot.send_friend_msg(1544629526, "will fail", random, req)

    ok = True
    for name, passed in [
        ("returns empty str", t == ""),
        ("random reset to 0", random.value == 0),
        ("req reset to 0", req.value == 0),
        ("recall on empty triple is False", bot.recall_friend_msg(t, 0, 0) is False),
    ]:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    return ok


def case_error_raises() -> bool:
    bot, _ = make_bot({"delete_msg"})
    try:
        bot.delete_msg(1)
    except QQBotError as exc:
        return _check("QQBotError carries retcode", exc.retcode == 200)
    return _check("QQBotError raised", False)


def case_signatures() -> bool:
    """Generated methods must expose the parameters extracted from NapCat."""
    expected = {
        "send_friend_msg": ["friend_qq", "message", "random", "req"],
        "send_group_msg": ["group_id", "message", "random", "req"],
        "delete_msg": ["message_id"],
        "set_group_ban": ["group_id", "user_id", "duration"],
        "get_group_member_info": ["group_id", "user_id", "no_cache"],
        "send_like": ["user_id", "times"],
        "set_msg_emoji_like": ["message_id", "emoji_id", "set"],
        "get_msg": ["message_id"],
        "send_poke": ["user_id", "group_id", "target_id"],
    }
    bot = QQBot()
    ok = True
    for method, params in expected.items():
        fn = getattr(bot, method, None)
        if fn is None:
            ok = _check(f"{method} exists", False)
            continue
        actual = [p for p in inspect.signature(fn).parameters if p != "self"]
        missing = [p for p in params if p not in actual]
        ok = _check(f"{method} exposes {params}", not missing) and ok
    return ok


def case_method_count() -> bool:
    bot = QQBot()
    methods = [n for n in dir(bot)
               if not n.startswith("_") and callable(getattr(bot, n))]
    return _check(f"generated methods >= 150 (got {len(methods)})", len(methods) >= 150)


def _check(name: str, passed: bool) -> bool:
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    return passed


def main() -> int:
    cases = [
        ("send + recall", case_send_and_recall),
        ("recall by time only", case_recall_by_time_only),
        ("recall by explicit id", case_recall_by_explicit_id),
        ("message segments", case_segments),
        ("failure branch", case_failure),
        ("error raises", case_error_raises),
        ("generated signatures", case_signatures),
        ("method count", case_method_count),
    ]
    summary = []
    for name, fn in cases:
        print(f"\n=== {name} ===")
        summary.append((name, fn()))

    print("\n" + "=" * 50)
    for name, passed in summary:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    all_ok = all(p for _, p in summary)
    print("=" * 50)
    print("all passed" if all_ok else "some checks failed")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
