#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线自测: 用本地假 OneBot 服务端(WS 推送 + HTTP API)跑通 napcat_demo 的完整链路。
不连接真实 NapCat, 不需要真实好友。

运行: python test_pipeline.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))

from napcat_demo import Bot, Config, Rule, build_reply_message, segments_to_text  # noqa: E402

WS_PORT = 39301
HTTP_PORT = 39302
TOKEN = "test_token"

sent: list[dict] = []


# --------------------------------------------------------------------------- #
# 假服务端
# --------------------------------------------------------------------------- #
async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {TOKEN}":
        return web.Response(status=401, text="unauthorized")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    # 私聊消息 1: ping  -> pong
    await ws.send_str(json.dumps({
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 1001,
        "user_id": 1544629526,
        "self_id": 2108172573,
        "raw_message": "ping",
        "sender": {"user_id": 1544629526, "nickname": "一方通行"},
        "message": [{"type": "text", "data": {"text": "ping"}}],
    }, ensure_ascii=False))
    await asyncio.sleep(0.2)

    # 私聊消息 2: 复读 你好 -> 你好
    await ws.send_str(json.dumps({
        "post_type": "message",
        "message_type": "private",
        "message_id": 1002,
        "user_id": 1544629526,
        "self_id": 2108172573,
        "sender": {"user_id": 1544629526, "nickname": "一方通行"},
        "message": [{"type": "text", "data": {"text": "复读 你好"}}],
    }, ensure_ascii=False))
    await asyncio.sleep(0.2)

    # 私聊消息 3: 重复 message_id 1002, 应被去重
    await ws.send_str(json.dumps({
        "post_type": "message",
        "message_type": "private",
        "message_id": 1002,
        "user_id": 1544629526,
        "self_id": 2108172573,
        "sender": {"user_id": 1544629526, "nickname": "一方通行"},
        "message": [{"type": "text", "data": {"text": "复读 你好"}}],
    }, ensure_ascii=False))
    await asyncio.sleep(0.2)

    # 群消息: 必须被忽略
    await ws.send_str(json.dumps({
        "post_type": "message",
        "message_type": "group",
        "message_id": 1003,
        "group_id": 123456,
        "user_id": 540682425,
        "self_id": 2108172573,
        "sender": {"user_id": 540682425, "nickname": "科技月月"},
        "message": [{"type": "text", "data": {"text": "ping"}}],
    }, ensure_ascii=False))
    await asyncio.sleep(0.2)

    # 私聊消息 4: calc 12+30, 带 reply 引用
    await ws.send_str(json.dumps({
        "post_type": "message",
        "message_type": "private",
        "message_id": 1004,
        "user_id": 1544629526,
        "self_id": 2108172573,
        "sender": {"user_id": 1544629526, "nickname": "一方通行"},
        "message": [{"type": "text", "data": {"text": "calc 12+30"}}],
    }, ensure_ascii=False))
    await asyncio.sleep(0.5)

    await ws.close()
    return ws


async def api_handler(request: web.Request) -> web.Response:
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {TOKEN}":
        return web.json_response({"status": "failed", "retcode": 401}, status=401)

    action = request.match_info["action"]
    body = await request.json() if request.can_read_body else {}

    if action == "get_login_info":
        return web.json_response({
            "status": "ok", "retcode": 0,
            "data": {"user_id": 2108172573, "nickname": "GeGe"},
        })
    if action == "send_private_msg":
        sent.append({"action": action, **body})
        return web.json_response({
            "status": "ok", "retcode": 0, "data": {"message_id": 9000 + len(sent)},
        })
    return web.json_response({"status": "failed", "retcode": 404}, status=404)


async def main() -> int:
    app = web.Application()
    app.router.add_get("/", ws_handler)
    app.router.add_post("/{action}", api_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    http_site = web.TCPSite(runner, "127.0.0.1", HTTP_PORT)
    ws_site = web.TCPSite(runner, "127.0.0.1", WS_PORT)
    await http_site.start()
    await ws_site.start()

    cfg = Config(
        http_base=f"http://127.0.0.1:{HTTP_PORT}",
        ws_url=f"ws://127.0.0.1:{WS_PORT}",
        access_token=TOKEN,
        timeout=5,
        self_id=0,
        reply_self=False,
        reply_delay_ms=0,
        dedup_window=100,
        log_file="test_messages.jsonl",
        reload_seconds=0,
        rules=[
            Rule(name="ping", match="exact", pattern="ping", reply="pong"),
            Rule(name="echo", match="prefix", pattern="复读 ", reply="{1}"),
            Rule(name="calc", match="regex", pattern=r"^calc\s+(\d+)\s*\+\s*(\d+)$",
                 reply="{1} + {2} = {sum}"),
        ],
        fallback_enabled=False,
        fallback_reply="",
    )
    for r in cfg.rules:
        r.compile()

    bot = Bot(cfg)
    run_task = asyncio.create_task(bot.run())

    # 等假服务端把 4 条事件推完
    await asyncio.sleep(3.0)
    bot.stop()
    try:
        await asyncio.wait_for(run_task, timeout=5)
    except asyncio.TimeoutError:
        run_task.cancel()

    await runner.cleanup()

    print("=" * 60)
    print(f"收到并回复的消息数: {len(sent)} (期望 3: ping / 复读 / calc)")
    for item in sent:
        print(f"  -> user_id={item.get('user_id')} message={item.get('message')}")

    ok = True
    texts = []
    for item in sent:
        segs = item.get("message") or []
        texts.append("".join(s.get("data", {}).get("text", "") for s in segs))

    checks = [
        ("ping -> pong", texts[0:1] == ["pong"] if len(texts) > 0 else False),
        ("复读 你好 -> 你好", texts[1:2] == ["你好"] if len(texts) > 1 else False),
        ("calc 12+30 -> 42", "42" in texts[2] if len(texts) > 2 else False),
        ("群消息被忽略 / 重复消息被去重", len(sent) == 3),
        ("回复带 reply 引用段", all(
            any(s.get("type") == "reply" for s in (item.get("message") or []))
            for item in sent
        )),
    ]
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed

    # 消息段解析单测
    assert segments_to_text([{"type": "text", "data": {"text": "hi"}},
                             {"type": "image", "data": {}}]) == "hi[图片]"
    assert build_reply_message("x", 5)[0] == {"type": "reply", "data": {"id": "5"}}
    print("[PASS] segments_to_text / build_reply_message")

    print("=" * 60)
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
