"""Generate qqbot_en.py from _actions.json.

Emits one method per OneBot action, in the same call shape as the E-language
prototype: positional required params, keyword optional params, and a trailing
`Ref` out-parameter where a recall triple is meaningful.
"""
import json
import re


from pathlib import Path

# 仓库根目录（tools/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent

ACTIONS = str(ROOT / 'tools' / '_actions.json')
OUT = str(ROOT / 'napcat' / 'api.py')

actions = json.load(open(ACTIONS, encoding='utf-8'))
by_action = {a['action']: a for a in actions}

# Actions excluded from codegen: placeholders, internals, or destructive
SKIP = {
    'unknown', 'test_auto_register_01', 'test_auto_register_02',
    '.ocr_image', 'IOCRImage',
}

# 源码里缺 actionSummary 的接口，补中文名
FALLBACK_SUMMARY = {
    'forward_friend_single_msg': '转发单条消息给好友',
    'forward_group_single_msg': '转发单条消息到群',
    'ArkSharePeer': '获取用户 Ark 分享卡片',
    'ArkShareGroup': '获取群 Ark 分享卡片',
    'send_group_ark_share': '发送群 Ark 分享卡片',
    'send_ark_share': '发送 Ark 分享卡片',
    'set_group_sign': '群签到',
    'send_group_sign': '发送群签到',
    'send_poke': '发送戳一戳',
    'group_poke': '群内戳一戳',
    'friend_poke': '私聊戳一戳',
}

# 源码里缺 description 的字段，补中文说明
FALLBACK_FIELD_DESC = {
    'message': '消息内容，支持字符串或消息段数组',
    'content': '内容',
    'context': '事件上下文',
    'operation': '要执行的操作',
    'tid': '说说/消息 ID',
    'format': '返回格式',
    'page_num': '页码',
    'count': '数量',
    'cursor': '翻页游标',
    'target_uin': '目标 QQ',
    'pos': '起始位置',
    'num': '数量',
    'feed_ref': '说说引用',
    'data': '数据',
    'cmd': '命令字',
    'rsp': '应答数据',
    'url': '链接',
    'file': '文件路径或标识',
    'file_id': '文件 ID',
    'name': '名称',
    'text': '文本',
    'seq': '序号',
    'uin': 'QQ 号',
    'uid': '用户 UID',
    'group_uin': '群号',
    'is_dismiss': '是否解散',
    'approve': '是否同意',
    'reason': '理由',
    'flag': '请求标识',
    'enable': '是否启用',
    'duration': '时长（秒）',
    'card': '群名片',
    'group_name': '群名',
    'nick': '昵称',
    'longNick': '个性签名',
    'emoji_id': '表情 ID',
    'set': '是否设置',
    'times': '次数',
    'no_cache': '是否跳过缓存',
    'busid': '业务 ID',
    'folder_id': '文件夹 ID',
    'base64': 'Base64 内容',
    'thread_count': '下载线程数',
    'headers': '请求头',
    'title': '标题',
    'type': '类型',
    'message_id': '消息 ID',
    'message_seq': '消息序号',
    'user_id': '用户 QQ',
    'group_id': '群号',
    'operator_id': '操作者 QQ',
    'target_id': '目标 QQ',
    'face_id': '表情 ID',
    'face_type': '表情类型',
    'wording': '状态文字',
    'sub_type': '子类型',
    'status': '状态',
    'interval': '间隔（毫秒）',
    'likes': '表情回应列表',
    'is_add': '是否为新增',
    'raw_info': '原始信息',
    'sender_id': '发送者 QQ',
    'busi_id': '业务 ID',
    'status_text': '状态文字',
    'event_type': '事件类型',
    'operator_nick': '操作者昵称',
    'card_new': '新名片',
    'card_old': '旧名片',
    'name_new': '新群名',
    'tag': '标签',
    'comment': '附言',
    'peer_id': '会话 ID',
    'self_id': '机器人 QQ',
    'time': '时间戳',
    'post_type': '事件大类',
    'notice_type': '通知类型',
    'request_type': '请求类型',
    'meta_event_type': '元事件类型',
    'message_type': '消息类型',
    'real_id': '真实消息 ID',
    'real_seq': '真实序号',
    'font': '字体',
    'sender': '发送者信息',
    'message_format': '消息格式',
    'message_sent_type': '自发消息类型',
    'emoji_likes_list': '表情回应列表',
    'temp_source': '临时会话来源',
    'duration_ms': '时长（毫秒）',
    'batch_id': '批次 ID',
    'abstime': '绝对时间戳',
    'reply_user': '被回复用户',
    'comment_id': '评论 ID',
    'comment_uin': '评论者 QQ',
    'reply_uin': '被回复者 QQ',
    'reply_name': '被回复者昵称',
    'images': '图片列表',
    'description': '描述',
    'feed': '说说对象',
    'policy': '策略',
    'reply': '回复内容',
    'feed_ref': '说说引用',
    'message_type': '消息类型',
}


def py_default(f):
    """Render a Python default literal for a field."""
    d = f['default']
    if d is None:
        return 'None'
    if d in ('!0', 'true'):
        return 'True'
    if d in ('!1', 'false'):
        return 'False'
    if d.startswith('"') or d.startswith("'"):
        return d.replace('"', "'")
    return d


def snake(action):
    """action string -> python method name (dots stripped)."""
    name = action.lstrip('.').replace('.', '_')
    return re.sub(r'[^\w]', '_', name)


def annot(f):
    return f['type']


def signature(action, fields):
    """Build a Python parameter list: required first, then optional."""
    required = [f for f in fields if not f['optional'] and f['default'] is None]
    optional = [f for f in fields if f not in required]

    parts = ['self']
    for f in required:
        parts.append(f"{f['name']}: {annot(f)}")
    for f in optional:
        parts.append(f"{f['name']}: {annot(f)} = {py_default(f)}")
    return parts, required, optional


def field_desc(f):
    """取字段的中文说明：优先用源码 description，其次查补丁表。

    源码里有些字段的 description 只是把字段名重复一遍（例如
    ``batch_id: 'batch_id'``），这种视为无说明，改用补丁表。
    """
    desc = (f.get('desc') or '').strip()
    if desc and desc != f['name']:
        return desc
    return FALLBACK_FIELD_DESC.get(f['name']) or ''


def build_doc(action, info, required, optional):
    lines = []
    title = info.get('summary') or FALLBACK_SUMMARY.get(action) or action
    lines.append(f'"""{title}。')
    lines.append('')
    lines.append(f'OneBot 接口：``{action}``')
    if required:
        lines.append('')
        lines.append('必填参数：')
        for f in required:
            desc = field_desc(f)
            lines.append(f'    {f["name"]} ({f["type"]})'
                         + (f' —— {desc}' if desc else ''))
    if optional:
        lines.append('')
        lines.append('可选参数：')
        for f in optional:
            desc = field_desc(f)
            lines.append(f'    {f["name"]} ({f["type"]}, 默认 {py_default(f)})'
                         + (f' —— {desc}' if desc else ''))
    lines.append('')
    lines.append('返回值：接口 ``data`` 字段的内容。')
    lines.append('"""')
    return lines


header = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQBot —— NapCat / OneBot v11 接口封装。

NapCat 4.18.42 暴露的每一个 OneBot 接口，在本类里都有一个同名方法。
方法形态对齐易语言原型：

    .子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
    .参数 好友QQ, 长整数型
    .参数 发送内容, 文本型
    .参数 Random, 长整数型, 参考 可空, 撤回消息用
    .参数 Req, 整数型, 参考 可空, 撤回消息用

类型对应关系：

    文本型      -> str
    长整数型    -> int            （Python 的 int 是任意精度，天然覆盖 int64）
    整数型      -> int
    参考        -> Ref            （可变容器，方法内部写 .value）
    可空        -> 默认值 None
    公开        -> 无下划线前缀的方法名

撤回三元组
----------
NapCat 的 ``send_*_msg`` 只返回 ``message_id``，而易语言接口按
``(time, random, req)`` 三元组撤回。三者在 ``get_msg`` 应答里的对应关系：

    time    = time           （unix 秒）
    random  = message_seq
    req     = real_id

所以本类在发送成功后立刻调一次 ``get_msg`` 补齐这三个值，并维护
``(time, random, req) -> message_id`` 对照表，让 ``recall_friend_msg``
能反查出 ``delete_msg`` 真正需要的 id。

本文件由 NapCat 源码自动生成，请勿手工修改生成出来的方法体。
"""

from __future__ import annotations

from typing import Any

import requests


class Ref:
    """模拟易语言「参数 ..., 参考」的传址语义。

    被调用方写入 :attr:`value`，调用方随后读取::

        random = Ref()
        req = Ref()
        t = bot.send_friend_msg(qq, "hi", random, req)
        print(t, random.value, req.value)
    """

    __slots__ = ("value",)

    def __init__(self, value: Any = None) -> None:
        self.value = value

    def __int__(self) -> int:
        return int(self.value or 0)

    def __bool__(self) -> bool:
        return self.value is not None

    def __repr__(self) -> str:
        return f"Ref({self.value!r})"


class QQBotError(RuntimeError):
    """NapCat 返回非 0 retcode 时抛出。"""

    def __init__(self, action: str, retcode: int, message: str) -> None:
        super().__init__(f"{action} 调用失败 (retcode={retcode})：{message}")
        self.action = action
        self.retcode = retcode
        self.message = message


class QQBot:
    """NapCat OneBot HTTP 接口的完整封装。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000",
        access_token: str = "",
        timeout: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        if access_token:
            self._session.headers["Authorization"] = f"Bearer {access_token}"

        # (time, random, req) -> message_id，供三元组撤回使用
        self._recall_index: dict[tuple[int, int, int], int] = {}
        # time -> message_id，让只传 time 的撤回也能工作
        self._recall_by_time: dict[int, int] = {}

    # ------------------------------------------------------------------ #
    # 底层传输
    # ------------------------------------------------------------------ #
    def call(self, action: str, **params: Any) -> Any:
        """向 OneBot HTTP 端点 POST 一个接口，返回应答里的 ``data``。

        ``retcode`` 非 0 时抛 :class:`QQBotError`。
        """
        url = f"{self.base_url}/{action}"
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            response = self._session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise QQBotError(action, -1, f"网络错误：{exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise QQBotError(action, response.status_code,
                             response.text[:300]) from exc

        retcode = body.get("retcode")
        if retcode not in (0, None):
            raise QQBotError(action, int(retcode or 0),
                             body.get("message") or body.get("wording") or "")
        return body.get("data")

    def call_raw(self, action: str, **params: Any) -> dict:
        """与 :meth:`call` 相同，但返回完整应答（status / retcode / data）。"""
        url = f"{self.base_url}/{action}"
        payload = {k: v for k, v in params.items() if v is not None}
        response = self._session.post(url, json=payload, timeout=self.timeout)
        try:
            return response.json()
        except ValueError:
            return {"status": "failed", "retcode": response.status_code,
                    "message": response.text[:300], "data": None}

    # ------------------------------------------------------------------ #
    # 撤回辅助
    # ------------------------------------------------------------------ #
    def _register_recall(self, message_id: Any) -> tuple[int, int, int]:
        """查一次 ``get_msg``，登记 (time, random, req) 三元组。"""
        mid = int(message_id)
        try:
            info = self.call("get_msg", message_id=mid) or {}
        except QQBotError:
            info = {}
        t = int(info.get("time") or 0)
        seq = int(info.get("message_seq") or mid)
        real = int(info.get("real_id") or mid)
        self._recall_index[(t, seq, real)] = mid
        if t:
            self._recall_by_time[t] = mid
        return t, seq, real

    def resolve_message_id(
        self,
        time: int = 0,
        random: int = 0,
        req: int = 0,
        message_id: int = 0,
    ) -> int:
        """解析出 ``delete_msg`` 真正需要的 ``message_id``。

        空字符串（``send_friend_msg`` 失败时的返回值）会被当成 0，
        这样调用方可以直接把发送结果原样传进来，不用先判断。
        """
        time = int(time or 0)
        random = int(random or 0)
        req = int(req or 0)

        if message_id:
            return int(message_id)
        hit = self._recall_index.get((time, random, req))
        if hit:
            return hit
        # 只给 time 的情况：同一秒内的 unix 时间戳实际上唯一
        hit = self._recall_by_time.get(time)
        if hit:
            return hit
        return int(random or req or 0)

    def recall(
        self,
        time: int = 0,
        random: int = 0,
        req: int = 0,
        message_id: int = 0,
    ) -> bool:
        """按三元组或 message_id 撤回消息，成功返回 True。"""
        mid = self.resolve_message_id(time, random, req, message_id)
        if not mid:
            return False
        try:
            self.call("delete_msg", message_id=mid)
        except QQBotError:
            return False
        self._recall_index.pop((int(time or 0), int(random or 0), int(req or 0)), None)
        self._recall_by_time.pop(int(time or 0), None)
        return True
'''

# ---- message-sending methods get the E-language shape (Ref out-params) ----
MESSAGE_ACTIONS = {
    'send_private_msg': ('send_friend_msg', 'user_id', 'friend_qq'),
    'send_group_msg': ('send_group_msg', 'group_id', 'group_id'),
}

body_parts = [header]

for action in sorted(by_action):
    if action in SKIP:
        continue
    info = by_action[action]
    fields = info['fields'] or []

    # message sends: drop the generic schema noise, keep the real knobs
    if action in MESSAGE_ACTIONS:
        method, id_key, id_arg = MESSAGE_ACTIONS[action]
        other = [f for f in fields
                 if f['name'] not in ('message_type', id_key, 'message')
                 and f['name'] not in ('user_id', 'group_id')]
        other = [f for f in other if f['name'] in ('auto_escape', 'timeout')]

        params = ['self', f'{id_arg}: int', 'message: Any']
        params += ['random: Ref | None = None', 'req: Ref | None = None']
        for f in other:
            params.append(f"{f['name']}: {annot(f)} = {py_default(f)}")

        doc = [
            '"""' + (info.get('summary') or FALLBACK_SUMMARY.get(action) or action)
            + '。',
            '',
            f'OneBot 接口：``{action}``',
            '',
            '成功时返回消息的 ``time``（字符串形式），用于撤回；失败返回空文本 ``""``。',
            '``random``（message_seq）与 ``req``（real_id）会写回传入的 :class:`Ref` 对象。',
            '"""',
        ]

        lines = [f'    def {method}(', ]
        for p in params:
            lines.append(f'        {p},')
        lines.append('    ) -> str:')
        lines.extend('        ' + d for d in doc)
        lines.append(f'        try:')
        lines.append(f'            data = self.call(')
        lines.append(f'                {action!r},')
        lines.append(f'                {id_key}={id_arg},')
        lines.append(f'                message=message,')
        for f in other:
            lines.append(f'                {f["name"]}={f["name"]},')
        lines.append(f'            ) or {{}}')
        lines.append(f'        except QQBotError:')
        lines.append(f'            if random is not None:')
        lines.append(f'                random.value = 0')
        lines.append(f'            if req is not None:')
        lines.append(f'                req.value = 0')
        lines.append(f'            return ""')
        lines.append(f'')
        lines.append(f'        mid = (data or {{}}).get("message_id")')
        lines.append(f'        if not mid:')
        lines.append(f'            if random is not None:')
        lines.append(f'                random.value = 0')
        lines.append(f'            if req is not None:')
        lines.append(f'                req.value = 0')
        lines.append(f'            return ""')
        lines.append(f'')
        lines.append(f'        t, seq, real = self._register_recall(mid)')
        lines.append(f'        if random is not None:')
        lines.append(f'            random.value = seq')
        lines.append(f'        if req is not None:')
        lines.append(f'            req.value = real')
        lines.append(f'        return str(t)')
        body_parts.append('\n'.join(lines))
        continue

    # generic method
    method = snake(action)
    params, required, optional = signature(action, fields)

    doc = build_doc(action, info, required, optional)

    lines = ['    def ' + method + '(']
    for p in params:
        lines.append(f'        {p},')
    lines.append('    ) -> Any:')
    lines.extend('        ' + d for d in doc)
    lines.append('        return self.call(')
    lines.append(f'            {action!r},')
    for f in fields:
        lines.append(f'            {f["name"]}={f["name"]},')
    lines.append('        )')
    body_parts.append('\n'.join(lines))

# recall wrapper appended last
body_parts.append('''    # ------------------------------------------------------------------ #
    # 易语言风格的撤回包装
    # ------------------------------------------------------------------ #
    def recall_friend_msg(self, time: int, random: int = 0, req: int = 0) -> bool:
        """按 :meth:`send_friend_msg` 返回的三元组撤回。"""
        return self.recall(time=time, random=random, req=req)

    def recall_group_msg(self, time: int, random: int = 0, req: int = 0) -> bool:
        """按 :meth:`send_group_msg` 返回的三元组撤回。"""
        return self.recall(time=time, random=random, req=req)
''')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(body_parts))
    f.write('\n')

n_methods = sum(1 for p in body_parts if '    def ' in p)
print(f'wrote {OUT}')
print(f'methods emitted: {n_methods}')
