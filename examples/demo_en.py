#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""napcat.api 演示 —— 易语言风格的发送与撤回。

重点看 :meth:`QQBot.send_friend_msg`，它对应易语言原型：

    .子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
    .参数 好友QQ, 长整数型
    .参数 发送内容, 文本型
    .参数 Random, 长整数型, 参考 可空, 撤回消息用
    .参数 Req, 整数型, 参考 可空, 撤回消息用

``random`` 和 ``req`` 是 ``Ref`` 对象，方法会把值写回去；
返回值是撤回用的 ``time``。

运行：
    python examples/demo_en.py                 # 发给自己并撤回
    python examples/demo_en.py 123456789       # 发给指定 QQ 并撤回
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# 让脚本能从 examples/ 直接运行（把仓库根加入搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from napcat.api import QQBot, QQBotError, Ref  # noqa: E402

BASE_URL = "http://127.0.0.1:3000"
TOKEN = "pydemo_token_2024"


def main() -> int:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 2108172573

    bot = QQBot(BASE_URL, TOKEN)

    # ---- who am I ----
    me = bot.call("get_login_info") or {}
    if not me:
        print(f"cannot reach NapCat at {BASE_URL}")
        return 1
    print(f"logged in as {me.get('user_id')} ({me.get('nickname')})")

    # ------------------------------------------------------------------ #
    # 1. E-language style: Ref out-params, string time return
    # ------------------------------------------------------------------ #
    print("\n=== E-language style ===")
    random = Ref()
    req = Ref()
    t = bot.send_friend_msg(target, "hello from qqbot_en", random, req)

    print(f"time   = {t!r}        (text return, used for recall)")
    print(f"random = {random.value}  (int64, by-ref)")
    print(f"req    = {req.value}     (int, by-ref)")

    if not t:
        print("send failed")
        return 1

    time.sleep(1)
    recalled = bot.recall_friend_msg(t, random.value, req.value)
    print(f"recall -> {'ok' if recalled else 'failed'}")

    # ------------------------------------------------------------------ #
    # 2. Python style: skip the Ref params entirely
    # ------------------------------------------------------------------ #
    print("\n=== Python style ===")
    t2 = bot.send_friend_msg(target, "no Ref params needed")
    print(f"time = {t2!r}")
    if t2:
        time.sleep(1)
        print(f"recall -> {'ok' if bot.recall_friend_msg(t2) else 'failed'}")

    # ------------------------------------------------------------------ #
    # 3. message segments pass straight through
    # ------------------------------------------------------------------ #
    print("\n=== message segments ===")
    t3 = bot.send_friend_msg(target, [
        {"type": "text", "data": {"text": "segments: "}},
        {"type": "face", "data": {"id": "14"}},
    ])
    print(f"time = {t3!r}")
    if t3:
        time.sleep(1)
        print(f"recall -> {'ok' if bot.recall_friend_msg(t3) else 'failed'}")

    # ------------------------------------------------------------------ #
    # 4. any other action is just a method
    # ------------------------------------------------------------------ #
    print("\n=== other actions ===")
    print("get_status      :", bot.get_status())
    print("get_version_info:", bot.get_version_info())
    print("can_send_image  :", bot.can_send_image())
    print("friends         :", len(bot.get_friend_list() or []), "entries")

    # errors surface as exceptions, not silent failures
    print("\n=== error handling ===")
    try:
        bot.delete_msg(1)
    except QQBotError as exc:
        print(f"QQBotError caught: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
