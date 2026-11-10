#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQBot —— 按易语言「发送好友消息」的方法格式封装的 NapCat (OneBot v11) 调用类

对应易语言原型：
    .子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
    .参数 好友QQ, 长整数型
    .参数 发送内容, 文本型
    .参数 Random, 长整数型, 参考 可空, 撤回消息用
    .参数 Req, 整数型, 参考 可空, 撤回消息用

易语言 → Python 的对应关系：
    文本型      -> str
    长整数型    -> int (Python 的 int 本身是任意精度, 天然够 int64)
    整数型      -> int
    参考        -> Ref 容器对象 (Python 没有引用传参, 用可变对象写回)
    可空        -> 默认值 None
    公开        -> 不加下划线前缀的公有方法

撤回三元组 (time, Random, Req) 在 NapCat 里的实际来源：
    time    = 消息时间戳(秒)      -> get_msg 返回的 time
    Random  = message_seq         -> get_msg 返回的 message_seq
    Req     = real_id             -> get_msg 返回的 real_id
真正撤回时 delete_msg 需要的是 message_id，所以本类内部维护了一张
(time, Random, Req) -> message_id 的对照表，让易语言的调用习惯能直接落地。

依赖: pip install requests
"""

from __future__ import annotations

import json
import time as _time
from dataclasses import dataclass, field
from typing import Any

import requests


# --------------------------------------------------------------------------- #
# 模拟易语言的「参考」参数
# --------------------------------------------------------------------------- #
class Ref:
    """
    模拟易语言 `.参数 xxx, 长整数型, 参考` 的传址语义。

    易语言里：
        发送好友消息 (123456, "hi", Random, Req)
        调试输出 (Random)   ' 被方法内部写好了

    Python 里没有引用传参，所以调用方先造一个 Ref 容器，
    方法内部写 container.value，调用方再读 container.value。
    """

    __slots__ = ("value",)

    def __init__(self, value: Any = None) -> None:
        self.value = value

    def __int__(self) -> int:
        return int(self.value or 0)

    def __str__(self) -> str:
        return "" if self.value is None else str(self.value)

    def __bool__(self) -> bool:
        return self.value is not None

    def __repr__(self) -> str:
        return f"Ref({self.value!r})"


# --------------------------------------------------------------------------- #
# 发送结果
# --------------------------------------------------------------------------- #
@dataclass
class 发送结果:
    """一次发送的完整回执，字段名直接对齐易语言的撤回三元组。"""

    成功: bool
    time: int = 0          # 文本型返回值的内容来源
    Random: int = 0        # message_seq
    Req: int = 0           # real_id
    message_id: int = 0    # delete_msg 真正要的
    原始返回: dict = field(default_factory=dict)

    def 三元组(self) -> tuple[int, int, int]:
        return self.time, self.Random, self.Req

    def __str__(self) -> str:
        # 对齐易语言「文本型」返回值：就是 time 的字符串
        return str(self.time)


# --------------------------------------------------------------------------- #
# QQBot 主类
# --------------------------------------------------------------------------- #
class QQBot:
    """
    NapCat / OneBot v11 的易语言风格封装。

    用法：
        bot = QQBot("http://127.0.0.1:3000", "你的token")

        Random = Ref()
        Req = Ref()
        time = bot.发送好友消息(1544629526, "hello", Random, Req)
        print(time, Random.value, Req.value)

        bot.撤回好友消息(time, Random.value, Req.value)
    """

    def __init__(
        self,
        地址: str = "http://127.0.0.1:3000",
        令牌: str = "",
        超时: int = 10,
    ) -> None:
        self.地址 = 地址.rstrip("/")
        self.令牌 = 令牌
        self.超时 = 超时
        self._会话 = requests.Session()
        if 令牌:
            self._会话.headers["Authorization"] = f"Bearer {令牌}"
        self._会话.headers["Content-Type"] = "application/json"

        # (time, Random, Req) -> message_id，让撤回三元组能落到 delete_msg
        self._撤回表: dict[tuple[int, int, int], int] = {}
        # 兜底：message_id 也单独存一份，防止调用方只拿到部分字段
        self._消息表: dict[int, 发送结果] = {}

    # ------------------------------------------------------------------ #
    # 底层调用
    # ------------------------------------------------------------------ #
    def _调用(self, 动作: str, **参数: Any) -> dict:
        """统一 POST 到 OneBot HTTP API，返回原始 JSON。"""
        网址 = f"{self.地址}/{动作}"
        try:
            应答 = self._会话.post(
                网址,
                data=json.dumps(参数, ensure_ascii=False).encode("utf-8"),
                timeout=self.超时,
            )
        except requests.RequestException as 错误:
            return {"status": "failed", "retcode": -1, "message": f"网络错误: {错误}"}

        try:
            数据 = 应答.json()
        except ValueError:
            数据 = {
                "status": "failed",
                "retcode": 应答.status_code,
                "message": 应答.text[:300],
            }

        if 应答.status_code != 200:
            数据.setdefault("status", "failed")
            数据.setdefault("retcode", 应答.status_code)
        return 数据

    @staticmethod
    def _取数据(应答: dict) -> dict:
        """从 OneBot 应答里安全取出 data 字典。"""
        数据 = 应答.get("data")
        return 数据 if isinstance(数据, dict) else {}

    @staticmethod
    def _打包消息(发送内容: Any) -> Any:
        """
        把发送内容规整成 OneBot 消息格式。
        纯字符串 -> 消息段数组；已经是数组就原样透传。
        """
        if isinstance(发送内容, str):
            return [{"type": "text", "data": {"text": 发送内容}}]
        if isinstance(发送内容, list):
            return 发送内容
        return [{"type": "text", "data": {"text": str(发送内容)}}]

    # ------------------------------------------------------------------ #
    # 核心：发送好友消息（严格对齐易语言原型）
    # ------------------------------------------------------------------ #
    def 发送好友消息(
        self,
        好友QQ: int,
        发送内容: str,
        Random: Ref | None = None,
        Req: Ref | None = None,
    ) -> str:
        """
        易语言原型：
            .子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
            .参数 好友QQ, 长整数型
            .参数 发送内容, 文本型
            .参数 Random, 长整数型, 参考 可空, 撤回消息用
            .参数 Req, 整数型, 参考 可空, 撤回消息用

        成功时返回 time 的字符串（撤回用）；失败返回空文本 ""。
        同时把 message_seq 写进 Random、real_id 写进 Req。
        """
        结果 = self.发送好友消息_详细(好友QQ, 发送内容)

        if Random is not None:
            Random.value = 结果.Random
        if Req is not None:
            Req.value = 结果.Req

        return str(结果) if 结果.成功 else ""

    def 发送好友消息_详细(self, 好友QQ: int, 发送内容: str) -> 发送结果:
        """
        同上，但返回完整的 发送结果 对象（Python 侧更好用）。
        NapCat 的 send_private_msg 只回 message_id，
        time / Random / Req 需要再查一次 get_msg 补齐。
        """
        应答 = self._调用(
            "send_private_msg",
            user_id=int(好友QQ),
            message=self._打包消息(发送内容),
        )
        数据 = self._取数据(应答)
        消息号 = int(数据.get("message_id") or 0)

        if 应答.get("retcode") != 0 or not 消息号:
            return 发送结果(成功=False, 原始返回=应答)

        结果 = self._补齐三元组(消息号)
        结果.原始返回 = 应答
        return 结果

    def _补齐三元组(self, 消息号: int) -> 发送结果:
        """调 get_msg 把 time / message_seq / real_id 抓回来，并登记撤回表。"""
        详情 = self._调用("get_msg", message_id=int(消息号))
        数据 = self._取数据(详情)

        时间戳 = int(数据.get("time") or 0)
        序号 = int(数据.get("message_seq") or 0)
        真实号 = int(数据.get("real_id") or 0)

        # get_msg 失败时退化为用 message_id 顶替，保证撤回仍然可用
        if not 时间戳:
            时间戳 = int(_time.time())
        if not 序号:
            序号 = 消息号
        if not 真实号:
            真实号 = 消息号

        结果 = 发送结果(
            成功=True,
            time=时间戳,
            Random=序号,
            Req=真实号,
            message_id=int(消息号),
        )
        self._撤回表[(时间戳, 序号, 真实号)] = int(消息号)
        self._消息表[int(消息号)] = 结果
        return 结果

    # ------------------------------------------------------------------ #
    # 撤回好友消息
    # ------------------------------------------------------------------ #
    def 撤回好友消息(
        self,
        time: int | str,
        Random: int | None = None,
        Req: int | None = None,
        消息号: int | None = None,
    ) -> bool:
        """
        对应易语言的撤回子程序。参数顺序与发送时的三元组一致。

        取 message_id 的顺序：
            1) 显式传入的 消息号
            2) (time, Random, Req) 在撤回表里的登记
            3) 直接拿 Random 当 message_id 试（NapCat 私聊里三者通常相等）
        """
        时间戳 = int(time or 0)
        序号 = int(Random or 0)
        真实号 = int(Req or 0)

        消息号候选: list[int] = []
        if 消息号:
            消息号候选.append(int(消息号))

        登记号 = self._撤回表.get((时间戳, 序号, 真实号))
        if 登记号:
            消息号候选.append(登记号)
        if 序号:
            消息号候选.append(序号)
        if 真实号:
            消息号候选.append(真实号)

        # 去重但保持顺序
        已试: set[int] = set()
        for 候选 in 消息号候选:
            if 候选 in 已试:
                continue
            已试.add(候选)
            应答 = self._调用("delete_msg", message_id=候选)
            if 应答.get("retcode") == 0:
                self._撤回表.pop((时间戳, 序号, 真实号), None)
                self._消息表.pop(候选, None)
                return True
        return False

    # ------------------------------------------------------------------ #
    # 配套：群消息 / 登录信息 / 通用 API
    # ------------------------------------------------------------------ #
    def 发送群消息(
        self,
        群号: int,
        发送内容: str,
        Random: Ref | None = None,
        Req: Ref | None = None,
    ) -> str:
        """群消息版，格式与 发送好友消息 完全一致。"""
        应答 = self._调用(
            "send_group_msg",
            group_id=int(群号),
            message=self._打包消息(发送内容),
        )
        数据 = self._取数据(应答)
        消息号 = int(数据.get("message_id") or 0)
        if 应答.get("retcode") != 0 or not 消息号:
            if Random is not None:
                Random.value = 0
            if Req is not None:
                Req.value = 0
            return ""

        结果 = self._补齐三元组(消息号)
        if Random is not None:
            Random.value = 结果.Random
        if Req is not None:
            Req.value = 结果.Req
        return str(结果.time)

    def 取登录信息(self) -> dict:
        """get_login_info：返回 {'user_id': ..., 'nickname': ...}"""
        return self._取数据(self._调用("get_login_info"))

    def 取好友列表(self) -> list[dict]:
        return self._取数据(self._调用("get_friend_list")) or []

    def 调用接口(self, 动作: str, **参数: Any) -> dict:
        """逃生口：直接调任意 OneBot action。"""
        return self._调用(动作, **参数)


# --------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------- #
def main() -> int:
    地址 = "http://127.0.0.1:3000"
    令牌 = "pydemo_token_2024"
    测试对象 = 2108172573  # 改成你的好友 QQ 就能发给别人

    bot = QQBot(地址, 令牌)

    信息 = bot.取登录信息()
    if not 信息:
        print(f"[失败] 连不上 {地址}，检查 NapCat 是否启动、token 是否正确")
        return 1
    print(f"已登录: {信息.get('user_id')} ({信息.get('nickname')})")

    # ---- 完全按易语言的写法 ----
    print("\n=== 易语言风格调用 ===")
    Random = Ref()
    Req = Ref()
    time = bot.发送好友消息(测试对象, "易语言风格 Demo 消息", Random, Req)
    print(f"返回值 time = {time!r}   (文本型)")
    print(f"Random      = {Random.value}  (长整数型, 参考)")
    print(f"Req         = {Req.value}     (整数型, 参考)")

    if not time:
        print("[失败] 发送失败")
        return 1

    _time.sleep(1)
    print(f"\n撤回 (time={time}, Random={Random.value}, Req={Req.value}) ...")
    撤回成功 = bot.撤回好友消息(time, Random.value, Req.value)
    print("撤回结果:", "成功" if 撤回成功 else "失败")

    # ---- Python 风格写法：直接拿结果对象 ----
    print("\n=== Python 风格调用 ===")
    结果 = bot.发送好友消息_详细(测试对象, "带完整回执的消息")
    print(f"成功={结果.成功} time={结果.time} Random={结果.Random} "
          f"Req={结果.Req} message_id={结果.message_id}")
    if 结果.成功:
        _time.sleep(1)
        print("撤回结果:", "成功" if bot.撤回好友消息(*结果.三元组()) else "失败")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
