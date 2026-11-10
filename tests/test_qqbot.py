#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qqbot.py 的离线自测：用假的 HTTP 会话替换 requests，验证
  1) 发送好友消息 的「文本型返回值 = time」
  2) Random / Req 两个「参考」参数被正确写回
  3) 撤回时能靠三元组找回 message_id
  4) 发送失败时返回空文本、参考参数不残留脏值

运行: python test_qqbot.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qqbot import QQBot, Ref  # noqa: E402


class 假应答:
    def __init__(self, 数据: dict, 状态码: int = 200) -> None:
        self._数据 = 数据
        self.status_code = 状态码
        self.text = json.dumps(数据, ensure_ascii=False)

    def json(self) -> dict:
        return self._数据


class 假会话:
    """记录每次请求，按 action 返回预设应答。"""

    def __init__(self, 失败动作: set[str] | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.调用记录: list[tuple[str, dict]] = []
        self.失败动作 = 失败动作 or set()
        self._下一个消息号 = 100000
        # message_id -> (time, message_seq, real_id)
        self._消息库: dict[int, tuple[int, int, int]] = {}

    def post(self, 网址: str, data: bytes, timeout: int) -> 假应答:
        动作 = 网址.rsplit("/", 1)[-1]
        参数 = json.loads(data.decode("utf-8"))
        self.调用记录.append((动作, 参数))

        if 动作 in self.失败动作:
            return 假应答({"status": "failed", "retcode": 100, "message": "模拟失败"})

        if 动作 in ("send_private_msg", "send_group_msg"):
            消息号 = self._下一个消息号
            self._下一个消息号 += 1
            时间戳 = 1794000000 + 消息号 % 1000
            self._消息库[消息号] = (时间戳, 消息号, 消息号)
            return 假应答({"status": "ok", "retcode": 0, "data": {"message_id": 消息号}})

        if 动作 == "get_msg":
            消息号 = int(参数["message_id"])
            三元组 = self._消息库.get(消息号)
            if not 三元组:
                return 假应答({"status": "failed", "retcode": 200, "message": "消息不存在"})
            时间戳, 序号, 真实号 = 三元组
            return 假应答({
                "status": "ok", "retcode": 0,
                "data": {"time": 时间戳, "message_id": 消息号,
                         "message_seq": 序号, "real_id": 真实号},
            })

        if 动作 == "delete_msg":
            消息号 = int(参数["message_id"])
            if 消息号 in self._消息库:
                del self._消息库[消息号]
                return 假应答({"status": "ok", "retcode": 0, "data": None})
            return 假应答({"status": "failed", "retcode": 200, "message": "消息不存在"})

        if 动作 == "get_login_info":
            return 假应答({"status": "ok", "retcode": 0,
                          "data": {"user_id": 2108172573, "nickname": "GeGe"}})

        return 假应答({"status": "failed", "retcode": 404}, 404)


def 用例_发送与撤回() -> bool:
    bot = QQBot("http://127.0.0.1:3000", "tok")
    假 = 假会话()
    bot._会话 = 假  # type: ignore[assignment]

    Random = Ref()
    Req = Ref()
    time = bot.发送好友消息(1544629526, "hello", Random, Req)

    ok = True
    检查 = [
        ("返回值是文本型 str", isinstance(time, str)),
        ("返回值非空", time != ""),
        ("返回值 == time 字段", int(time) == 1794000000 + 100000 % 1000),
        ("Random 被写回", Random.value == 100000),
        ("Req 被写回", Req.value == 100000),
        ("消息体是 array 格式", 假.调用记录[0][1]["message"] ==
            [{"type": "text", "data": {"text": "hello"}}]),
        ("user_id 是 int", 假.调用记录[0][1]["user_id"] == 1544629526),
    ]
    for 名, 通过 in 检查:
        print(f"  [{'PASS' if 通过 else 'FAIL'}] {名}")
        ok = ok and 通过

    # 撤回：只给三元组，看能不能找回 message_id
    撤回ok = bot.撤回好友消息(time, Random.value, Req.value)
    print(f"  [{'PASS' if 撤回ok else 'FAIL'}] 用三元组撤回成功")
    ok = ok and 撤回ok

    撤回动作 = [a for a, _ in 假.调用记录 if a == "delete_msg"]
    print(f"  [{'PASS' if 撤回动作 else 'FAIL'}] 确实调了 delete_msg")
    ok = ok and bool(撤回动作)
    return ok


def 用例_失败分支() -> bool:
    bot = QQBot("http://127.0.0.1:3000", "tok")
    bot._会话 = 假会话(失败动作={"send_private_msg"})  # type: ignore[assignment]

    Random = Ref()
    Req = Ref()
    time = bot.发送好友消息(1544629526, "会失败的消息", Random, Req)

    ok = True
    检查 = [
        ("失败时返回空文本", time == ""),
        ("失败时 Random 写 0", Random.value == 0),
        ("失败时 Req 写 0", Req.value == 0),
        ("失败时撤回返回 False", bot.撤回好友消息(time or 0, 0, 0) is False),
    ]
    for 名, 通过 in 检查:
        print(f"  [{'PASS' if 通过 else 'FAIL'}] {名}")
        ok = ok and 通过
    return ok


def 用例_可空参数() -> bool:
    """Random / Req 都可空：不传也能正常发。"""
    bot = QQBot("http://127.0.0.1:3000", "tok")
    bot._会话 = 假会话()  # type: ignore[assignment]

    time = bot.发送好友消息(1544629526, "不传参考参数")
    ok = isinstance(time, str) and time != ""
    print(f"  [{'PASS' if ok else 'FAIL'}] 省略 Random/Req 也能发送")
    return ok


def 用例_详细结果() -> bool:
    bot = QQBot("http://127.0.0.1:3000", "tok")
    bot._会话 = 假会话()  # type: ignore[assignment]

    结果 = bot.发送好友消息_详细(1544629526, "详细回执")
    ok = True
    检查 = [
        ("成功标志", 结果.成功 is True),
        ("time 非 0", 结果.time > 0),
        ("Random 非 0", 结果.Random > 0),
        ("Req 非 0", 结果.Req > 0),
        ("message_id 非 0", 结果.message_id > 0),
        ("三元组顺序 = (time, Random, Req)", 结果.三元组() ==
            (结果.time, 结果.Random, 结果.Req)),
        ("str(结果) == str(time)", str(结果) == str(结果.time)),
    ]
    for 名, 通过 in 检查:
        print(f"  [{'PASS' if 通过 else 'FAIL'}] {名}")
        ok = ok and 通过
    return ok


def main() -> int:
    全部 = [
        ("发送 + 撤回（易语言风格）", 用例_发送与撤回),
        ("发送失败分支", 用例_失败分支),
        ("Random/Req 可空", 用例_可空参数),
        ("详细结果对象", 用例_详细结果),
    ]
    汇总 = []
    for 名, 函数 in 全部:
        print(f"\n=== {名} ===")
        通过 = 函数()
        汇总.append((名, 通过))

    print("\n" + "=" * 50)
    for 名, 通过 in 汇总:
        print(f"[{'PASS' if 通过 else 'FAIL'}] {名}")
    全通过 = all(p for _, p in 汇总)
    print("=" * 50)
    print("全部通过" if 全通过 else "存在失败项")
    return 0 if 全通过 else 1


if __name__ == "__main__":
    raise SystemExit(main())
