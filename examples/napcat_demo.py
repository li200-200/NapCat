#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NapCat / OneBot v11 私聊实时监听 + 规则回复 Demo

功能:
  1. 通过 WebSocket 实时接收 NapCat 推送的事件(不需要轮询)
  2. 只处理私聊消息(message_type == "private")
  3. 按 config.json 里的规则做 精确/包含/前缀/正则 匹配
  4. 命中后通过 HTTP API 发送回复, 并「引用/回复」原消息(reply 消息段)
  5. 断线自动重连、消息去重、落盘 messages.jsonl、热加载配置

运行:
  python napcat_demo.py                # 正常监听
  python napcat_demo.py --test ping    # 只做本地规则匹配测试, 不发消息
  python napcat_demo.py --send 1544629526 "hello"   # 手动给某人发一条私聊

依赖: pip install websockets aiohttp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import signal
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import aiohttp
import websockets

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# websockets 13.x 用 extra_headers, 14+ 改成 additional_headers
_WS_MAJOR = int(getattr(websockets, "__version__", "13").split(".")[0])
_WS_HEADER_KW = "additional_headers" if _WS_MAJOR >= 14 else "extra_headers"


def ws_headers_kwargs(token: str) -> dict[str, Any]:
    """按当前 websockets 版本返回携带鉴权头的连接参数。"""
    if not token:
        return {}
    return {_WS_HEADER_KW: {"Authorization": f"Bearer {token}"}}

log = logging.getLogger("napcat")


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@dataclass
class Rule:
    name: str
    match: str                 # exact | contains | prefix | suffix | regex
    pattern: str
    reply: str
    enabled: bool = True
    scope: str = "private"     # private | group | all
    regex: re.Pattern[str] | None = field(default=None, repr=False)

    def compile(self) -> None:
        if self.match == "regex":
            self.regex = re.compile(self.pattern, re.S)

    def hit(self, text: str) -> re.Match[str] | None | bool:
        """命中返回匹配信息(或 True), 未命中返回 False/None。"""
        if not self.enabled:
            return False
        if self.match == "exact":
            return True if text.strip() == self.pattern else False
        if self.match == "contains":
            return True if self.pattern in text else False
        if self.match == "prefix":
            return True if text.startswith(self.pattern) else False
        if self.match == "suffix":
            return True if text.endswith(self.pattern) else False
        if self.match == "regex" and self.regex is not None:
            return self.regex.search(text)
        return False

    def render(self, text: str, hit: Any, ctx: dict[str, Any]) -> str:
        """把 reply 模板里的占位符替换成真实内容。"""
        out = self.reply

        groups: list[str] = []
        if isinstance(hit, re.Match):
            groups = [g if g is not None else "" for g in hit.groups()]
        elif self.match == "prefix":
            groups = [text[len(self.pattern):].strip()]

        for i, g in enumerate(groups, start=1):
            out = out.replace("{%d}" % i, g)

        # 纯数字分组时顺手提供求和, 方便做 calc 这类玩具指令
        if groups and all(g.isdigit() for g in groups if g):
            out = out.replace("{sum}", str(sum(int(g) for g in groups if g)))

        mapping = {
            "{text}": text,
            "{now}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "{date}": datetime.now().strftime("%Y-%m-%d"),
            "{time}": datetime.now().strftime("%H:%M:%S"),
            "{rule}": self.name,
        }
        for k, v in mapping.items():
            out = out.replace(k, v)
        for k, v in ctx.items():
            out = out.replace("{%s}" % k, str(v))
        return out


@dataclass
class Config:
    http_base: str
    ws_url: str
    access_token: str
    timeout: int
    self_id: int
    reply_self: bool
    reply_delay_ms: int
    dedup_window: int
    log_file: str
    reload_seconds: int
    rules: list[Rule]
    fallback_enabled: bool
    fallback_reply: str

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        ob = raw.get("onebot", {})
        bh = raw.get("behavior", {})
        rules = []
        for item in raw.get("rules", []):
            rule = Rule(
                name=item.get("name") or item.get("pattern", "rule"),
                match=item.get("match", "exact"),
                pattern=item.get("pattern", ""),
                reply=item.get("reply", ""),
                enabled=item.get("enabled", True),
                scope=item.get("scope", "private"),
            )
            rule.compile()
            rules.append(rule)
        fb = raw.get("fallback", {})
        return cls(
            http_base=ob.get("http_base", "http://127.0.0.1:3000").rstrip("/"),
            ws_url=ob.get("ws_url", "ws://127.0.0.1:3000"),
            access_token=ob.get("access_token", ""),
            timeout=int(ob.get("timeout", 10)),
            self_id=int(bh.get("self_id", 0) or 0),
            reply_self=bool(bh.get("reply_self", False)),
            reply_delay_ms=int(bh.get("reply_delay_ms", 0) or 0),
            dedup_window=int(bh.get("dedup_window", 500) or 0),
            log_file=bh.get("log_file", "messages.jsonl"),
            reload_seconds=int(bh.get("config_reload_seconds", 0) or 0),
            rules=rules,
            fallback_enabled=bool(fb.get("enabled", False)),
            fallback_reply=fb.get("reply", ""),
        )


# --------------------------------------------------------------------------- #
# 消息工具
# --------------------------------------------------------------------------- #
def segments_to_text(message: Any) -> str:
    """把 OneBot 的 array 格式消息段转成纯文本(图片/表情等用占位符表示)。"""
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


def build_reply_message(text: str, quote_id: int | None) -> list[dict[str, Any]]:
    """构造回复消息段数组; quote_id 非空时先放 reply 段实现「指定消息回复」。"""
    msg: list[dict[str, Any]] = []
    if quote_id:
        msg.append({"type": "reply", "data": {"id": str(quote_id)}})
    msg.append({"type": "text", "data": {"text": text}})
    return msg


# --------------------------------------------------------------------------- #
# OneBot 客户端
# --------------------------------------------------------------------------- #
class OneBot:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.session: aiohttp.ClientSession | None = None
        self.self_id: int = cfg.self_id

    async def start(self) -> None:
        headers = {}
        if self.cfg.access_token:
            headers["Authorization"] = f"Bearer {self.cfg.access_token}"
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.cfg.timeout),
        )

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def call(self, action: str, **params: Any) -> dict[str, Any]:
        assert self.session is not None, "session 未初始化"
        url = f"{self.cfg.http_base}/{action}"
        try:
            async with self.session.post(url, json=params) as resp:
                body = await resp.text()
                if resp.status != 200:
                    log.error("API %s HTTP %s: %s", action, resp.status, body[:300])
                    return {"status": "failed", "retcode": resp.status, "message": body}
                data = json.loads(body)
                if data.get("retcode") not in (0, 1, None):
                    log.warning("API %s 返回异常: %s", action, body[:300])
                return data
        except Exception as exc:  # noqa: BLE001
            log.error("API %s 调用失败: %r", action, exc)
            return {"status": "failed", "message": repr(exc)}

    async def login_info(self) -> dict[str, Any]:
        return await self.call("get_login_info")

    async def send_private(
        self,
        user_id: int,
        text: str,
        quote_id: int | None = None,
        auto_escape: bool = False,
    ) -> dict[str, Any]:
        """发送私聊消息。quote_id 给出时以「回复」形式引用那条消息。"""
        payload: dict[str, Any] = {
            "user_id": user_id,
            "message": build_reply_message(text, quote_id),
            "auto_escape": auto_escape,
        }
        return await self.call("send_private_msg", **payload)


# --------------------------------------------------------------------------- #
# 机器人主体
# --------------------------------------------------------------------------- #
class Bot:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.api = OneBot(cfg)
        self.seen: OrderedDict[int, float] = OrderedDict()
        self._stop = asyncio.Event()
        self._log_path = BASE_DIR / cfg.log_file
        self._msg_count = 0
        self._cfg_mtime = self._config_mtime()
        self._last_reload_check = 0.0
        # 自己发出去的消息 id, 用于防自激循环(回复内容命中规则再次触发)
        self._sent_ids: OrderedDict[int, float] = OrderedDict()

    # ---------------- 生命周期 ----------------
    def stop(self) -> None:
        self._stop.set()

    def _config_mtime(self) -> float:
        try:
            return CONFIG_PATH.stat().st_mtime
        except OSError:
            return 0.0

    def _maybe_reload_config(self) -> None:
        """config_reload_seconds > 0 时热加载规则, 改完 json 不用重启。"""
        interval = self.cfg.reload_seconds
        if interval <= 0:
            return
        now = time.time()
        if now - self._last_reload_check < interval:
            return
        self._last_reload_check = now

        mtime = self._config_mtime()
        if mtime <= 0 or mtime == self._cfg_mtime:
            return
        self._cfg_mtime = mtime
        try:
            new_cfg = Config.load()
        except Exception as exc:  # noqa: BLE001
            log.error("配置热加载失败, 继续使用旧配置: %r", exc)
            return
        # 只热更新规则/兜底/延迟这些运行期参数, 连接参数保持不变
        self.cfg.rules = new_cfg.rules
        self.cfg.fallback_enabled = new_cfg.fallback_enabled
        self.cfg.fallback_reply = new_cfg.fallback_reply
        self.cfg.reply_delay_ms = new_cfg.reply_delay_ms
        self.cfg.reply_self = new_cfg.reply_self
        log.info("配置已热加载, 当前规则数: %d", len(self.cfg.rules))


    async def run(self) -> None:
        await self.api.start()
        try:
            info = await self.api.login_info()
            data = info.get("data") or {}
            if data.get("user_id"):
                self.api.self_id = int(data["user_id"])
                log.info("已连接账号: %s (%s)", data.get("user_id"), data.get("nickname"))
            else:
                log.warning("get_login_info 未返回账号信息: %s", info)
            await self._loop_ws()
        finally:
            await self.api.close()

    async def _loop_ws(self) -> None:
        backoff = 1.0
        header_kwargs = ws_headers_kwargs(self.cfg.access_token)

        while not self._stop.is_set():
            try:
                log.info("连接 WebSocket: %s", self.cfg.ws_url)
                async with websockets.connect(
                    self.cfg.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=32 * 1024 * 1024,
                    **header_kwargs,
                ) as ws:
                    log.info("WebSocket 已连接, 开始实时监听")
                    backoff = 1.0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            log.warning("非 JSON 帧: %r", raw[:200])
                            continue
                        await self.on_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                log.error("WebSocket 断开: %r, %.1fs 后重连", exc, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    # ---------------- 事件处理 ----------------
    async def on_event(self, event: dict[str, Any]) -> None:
        post_type = event.get("post_type")
        if post_type == "meta_event":
            meta = event.get("meta_event_type")
            if meta == "lifecycle":
                log.info("生命周期事件: %s", event.get("sub_type"))
            elif meta == "heartbeat":
                log.debug("心跳: status=%s", event.get("status"))
            return
        # message: 别人发的消息; message_sent: 自己发出的消息(需开 reportSelfMessage)
        if post_type not in ("message", "message_sent"):
            return

        if event.get("message_type") != "private":
            log.debug("忽略非私聊消息: %s", event.get("message_type"))
            return

        msg_id = int(event.get("message_id") or 0)
        if self._is_duplicate(msg_id):
            log.debug("重复消息, 跳过: %s", msg_id)
            return

        self._maybe_reload_config()

        user_id = int(event.get("user_id") or 0)
        sender = event.get("sender") or {}
        nickname = sender.get("card") or sender.get("nickname") or str(user_id)
        text = segments_to_text(event.get("message"))
        is_self = post_type == "message_sent" or (
            bool(self.api.self_id) and user_id == self.api.self_id
        )
        # 自己刚发出去的消息(回复内容)不再触发规则, 避免自激死循环
        if is_self and msg_id in self._sent_ids:
            log.debug("忽略自己刚发出的回复: %s", msg_id)
            return

        self._record(event, user_id, nickname, text)
        log.info(
            "[%s私聊] %s(%s): %s",
            "自己" if is_self else "",
            nickname,
            user_id,
            text,
        )

        if is_self and not self.cfg.reply_self:
            log.debug("忽略自己发出的消息")
            return

        await self._dispatch(user_id, nickname, text, msg_id)

    async def _dispatch(self, user_id: int, nickname: str, text: str, msg_id: int) -> None:
        ctx = {"user_id": user_id, "nickname": nickname, "message_id": msg_id}
        for rule in self.cfg.rules:
            if rule.scope not in ("private", "all"):
                continue
            hit = rule.hit(text)
            if not hit:
                continue
            reply = rule.render(text, hit, ctx)
            log.info("命中规则 %s -> 回复: %s", rule.name, reply.replace("\n", "\\n"))
            await self._reply(user_id, reply, msg_id)
            return

        if self.cfg.fallback_enabled and self.cfg.fallback_reply:
            reply = self.cfg.fallback_reply
            for k, v in ctx.items():
                reply = reply.replace("{%s}" % k, str(v))
            reply = reply.replace("{text}", text)
            log.info("未命中规则, 走兜底回复: %s", reply)
            await self._reply(user_id, reply, msg_id)

    async def _reply(self, user_id: int, text: str, quote_id: int | None) -> None:
        if self.cfg.reply_delay_ms > 0:
            await asyncio.sleep(self.cfg.reply_delay_ms / 1000)
        result = await self.api.send_private(user_id, text, quote_id=quote_id)
        if result.get("status") == "ok" or result.get("retcode") == 0:
            log.info("已回复 -> %s", user_id)
            new_id = (result.get("data") or {}).get("message_id")
            if new_id:
                self._sent_ids[int(new_id)] = time.time()
                while len(self._sent_ids) > 200:
                    self._sent_ids.popitem(last=False)
        else:
            log.error("回复失败 -> %s: %s", user_id, result)

    # ---------------- 工具 ----------------
    def _is_duplicate(self, msg_id: int) -> bool:
        if not msg_id or self.cfg.dedup_window <= 0:
            return False
        if msg_id in self.seen:
            return True
        self.seen[msg_id] = time.time()
        while len(self.seen) > self.cfg.dedup_window:
            self.seen.popitem(last=False)
        return False

    def _record(self, event: dict[str, Any], user_id: int, nickname: str, text: str) -> None:
        self._msg_count += 1
        row = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_id": event.get("message_id"),
            "user_id": user_id,
            "nickname": nickname,
            "text": text,
            "raw": event.get("message"),
        }
        try:
            with self._log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("写日志失败: %r", exc)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("websockets").setLevel(logging.WARNING)


def test_rules(text: str) -> int:
    cfg = Config.load()
    ctx = {"user_id": 0, "nickname": "tester", "message_id": 0}
    for rule in cfg.rules:
        hit = rule.hit(text)
        if not hit:
            continue
        print(f"命中规则: {rule.name}")
        print("回复内容:")
        print(rule.render(text, hit, ctx))
        return 0
    if cfg.fallback_enabled:
        print("未命中规则, 兜底回复:")
        print(cfg.fallback_reply.replace("{text}", text))
        return 0
    print("未命中任何规则")
    return 1


async def manual_send(user_id: int, text: str, quote_id: int | None) -> int:
    cfg = Config.load()
    api = OneBot(cfg)
    await api.start()
    try:
        result = await api.send_private(user_id, text, quote_id=quote_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 1
    finally:
        await api.close()


async def amain() -> int:
    cfg = Config.load()
    bot = Bot(cfg)
    loop = asyncio.get_running_loop()

    def _shutdown(*_: Any) -> None:
        log.info("收到退出信号, 正在停止...")
        bot.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: _shutdown())

    task = asyncio.create_task(bot.run())
    stop_task = asyncio.create_task(bot._stop.wait())
    done, pending = await asyncio.wait({task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    if stop_task in done:
        task.cancel()
        with_suppress = asyncio.gather(task, return_exceptions=True)
        await with_suppress
    for p in pending:
        p.cancel()
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NapCat 私聊实时监听 + 规则回复 Demo")
    parser.add_argument("--test", metavar="TEXT", help="只本地测试规则匹配, 不连接 NapCat")
    parser.add_argument("--send", nargs=2, metavar=("USER_ID", "TEXT"), help="手动发一条私聊消息")
    parser.add_argument("--quote", type=int, default=None, help="配合 --send, 引用某条 message_id")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 日志")
    args = parser.parse_args(list(argv) if argv is not None else None)

    setup_logging(args.verbose)

    if args.test:
        return test_rules(args.test)
    if args.send:
        user_id = int(args.send[0])
        return asyncio.run(manual_send(user_id, args.send[1], args.quote))

    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
