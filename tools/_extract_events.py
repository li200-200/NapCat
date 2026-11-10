"""从 napcat.mjs 抽取全部 OneBot 事件类型 + 字段，产出 _events.json。

事件在 NapCat 里是 class 声明：
    class Sxe extends Qo {
      notice_type = "group_ban";   <- class field 字面量
      operator_id;
      sub_type;                    <- 由 constructor 参数赋值
      constructor(e, r, n, i, o, s) { ... }
    }

难点与处理：
  1. post_type 用枚举引用（Fl.NOTICE），必须解析枚举定义才能得到 "notice"。
  2. sub_type 常是 constructor 参数，真实取值要看实例化处传入的字面量；
     对没有直接字面量的（如 group_ban），按 OneBot 规范列出全部取值。
  3. 基类链（r4 -> na -> Qo ...）提供 time / self_id / group_id / user_id，
     必须沿 extends 回溯合并字段。
"""
import re
import json


from pathlib import Path

# 仓库根目录（tools/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent

SRC = r'C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\napcat.mjs'
OUT = str(ROOT / 'tools' / '_events.json')

src = open(SRC, encoding='utf-8', errors='replace').read()

# ---------------------------------------------------------------- class 边界
class_starts = [(m.start(), m.group(1), m.group(2))
                for m in re.finditer(r'^class\s+([\w$]+)(?:\s+extends\s+([\w$]+))?\s*\{',
                                     src, re.M)]
bounds = {}
for i, (pos, name, parent) in enumerate(class_starts):
    end = class_starts[i + 1][0] if i + 1 < len(class_starts) else len(src)
    bounds[name] = {'parent': parent, 'start': pos, 'end': end}


def class_body(name):
    b = bounds.get(name)
    return src[b['start']:b['end']] if b else ''


# ------------------------------------------------------------ 枚举解析
ENUMS = {}
for m in re.finditer(
        r'\bvar\s+([\w$]+)\s*=\s*/\* @__PURE__ \*/\s*\(\(t\)\s*=>\s*\((.*?)\)\)\(\w+\s*\|\|\s*\{\}\)',
        src, re.S):
    members = dict(re.findall(r't\.([\w$]+)\s*=\s*"([^"]*)"', m.group(2)))
    if members:
        ENUMS[m.group(1)] = members


def resolve_value(expr):
    if not expr:
        return None
    expr = expr.strip()
    m = re.match(r'^([\w$]+)\.([\w$]+)$', expr)
    if m and m.group(1) in ENUMS:
        return ENUMS[m.group(1)].get(m.group(2))
    if expr.startswith('"') or expr.startswith("'"):
        return expr.strip('"\'')
    return None


# ------------------------------------------------ 解析 class field 声明
FIELD_RE = re.compile(r'^\s{2}([A-Za-z_$][\w$]*)\s*(?:=\s*([^;\n]+))?;', re.M)


def parse_fields(name):
    body = class_body(name)
    if not body:
        return []
    ctor = body.find('constructor(')
    head = body[:ctor] if ctor > 0 else body
    nl = head.find('\n')
    head = head[nl + 1:] if nl > 0 else head
    out = []
    for m in FIELD_RE.finditer(head):
        fname = m.group(1)
        if fname == 'constructor':
            continue
        out.append({'name': fname, 'init': (m.group(2) or '').strip() or None})
    return out


def ctor_assignments(name):
    body = class_body(name)
    m = re.search(r'constructor\s*\([^)]*\)\s*\{', body)
    if not m:
        return {}
    start = m.end() - 1
    depth, i = 0, start
    while i < len(body):
        if body[i] == '{':
            depth += 1
        elif body[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    out = {}
    for am in re.finditer(r'this\.([\w$]+)\s*=\s*([\w$]+)\s*[,;]', body[start:i]):
        out[am.group(1)] = am.group(2)
    return out


def all_fields(name, seen=None):
    if seen is None:
        seen = set()
    if name in seen or name not in bounds:
        return []
    seen.add(name)

    by_name = {}
    for f in parse_fields(name):
        by_name[f['name']] = f
    parent = bounds[name]['parent']
    if parent:
        for f in all_fields(parent, seen):
            by_name.setdefault(f['name'], f)
    for fname in ctor_assignments(name):
        by_name.setdefault(fname, {'name': fname, 'init': None})
    return list(by_name.values())


def is_event_class(name):
    cur, depth = name, 0
    while cur and depth < 12:
        if 'post_type = ' in class_body(cur):
            return True
        cur = bounds.get(cur, {}).get('parent')
        depth += 1
    return False


# --------------------------------- 各事件 sub_type 的真实取值（人工核对自实例化处）
# 来源：new Ng(..., "approve"/"invite")、new Qwe(..., i ? "set" : "unset")、
#       new Bwe(..., groupChangDecreseType2String(...))、new Vy(e, wh.CONNECT)
SUBTYPES = {
    ('meta_event', 'lifecycle'): ['connect', 'enable', 'disable'],
    ('notice', 'group_increase'): ['approve', 'invite'],
    ('notice', 'group_decrease'): ['leave', 'kick', 'kick_me'],
    ('notice', 'group_admin'): ['set', 'unset'],
    ('notice', 'group_ban'): ['ban', 'lift_ban'],
    ('notice', 'essence'): ['add', 'delete'],
    ('notice', 'notify'): None,   # notify 靠二级 sub_type 区分，见下
    ('request', 'group'): ['add', 'invite'],
}

# notify 的二级 sub_type
NOTIFY_SUBTYPES = {
    'poke': '戳一戳',
    'title': '群成员荣誉变更',
    'gray_tip': '灰条消息',
    'group_name': '群名变更',
    'input_status': '输入状态',
    'profile_like': '名片点赞',
}


# ------------------------------------------------- 收集事件
events = []
for name in bounds:
    if not is_event_class(name):
        continue

    fields = all_fields(name)
    info = {}
    for f in fields:
        if f['name'] in ('post_type', 'notice_type', 'request_type',
                         'meta_event_type', 'message_type', 'sub_type'):
            info[f['name']] = resolve_value(f['init'])

    if not any(k in info for k in ('notice_type', 'request_type',
                                   'meta_event_type', 'message_type')):
        continue

    key = (info.get('post_type'), info.get('notice_type'),
           info.get('request_type'), info.get('meta_event_type'),
           info.get('message_type'), info.get('sub_type'))

    events.append({
        'class': name,
        'parent': bounds[name]['parent'],
        'post_type': info.get('post_type'),
        'notice_type': info.get('notice_type'),
        'request_type': info.get('request_type'),
        'meta_event_type': info.get('meta_event_type'),
        'message_type': info.get('message_type'),
        'sub_type': info.get('sub_type'),
        'fields': [f['name'] for f in fields],
    })

best = {}
for e in events:
    key = (e['post_type'], e['notice_type'], e['request_type'],
           e['meta_event_type'], e['message_type'], e['sub_type'])
    cur = best.get(key)
    if cur is None or len(e['fields']) > len(cur['fields']):
        best[key] = e

out = sorted(best.values(),
             key=lambda e: tuple(x or '' for x in (
                 e['post_type'], e['notice_type'], e['request_type'],
                 e['meta_event_type'], e['message_type'], e['sub_type'])))

# ------------------------------------------------- 补充：消息事件（非 class 构建）
# 消息事件由 initializeMessage() 返回对象字面量，再被
# handleGroupMessage / handlePrivateMessage / handleTempGroupMessage 补字段，
# 所以不在上面的 class 扫描范围内，这里按源码逐字段手工登记。
_MESSAGE_BASE = [
    'self_id', 'user_id', 'time', 'message_id', 'message_seq', 'real_id',
    'real_seq', 'message_type', 'sender', 'raw_message', 'font', 'sub_type',
    'message', 'message_format', 'post_type',
]
_MESSAGE_SENT_EXTRA = ['message_sent_type', 'emoji_likes_list']

MESSAGE_EVENTS = [
    {
        'class': 'initializeMessage + handlePrivateMessage',
        'parent': None,
        'post_type': 'message',
        'notice_type': None, 'request_type': None, 'meta_event_type': None,
        'message_type': 'private',
        'sub_type': 'friend',
        'fields': _MESSAGE_BASE,
    },
    {
        'class': 'initializeMessage + handleTempGroupMessage',
        'parent': None,
        'post_type': 'message',
        'notice_type': None, 'request_type': None, 'meta_event_type': None,
        'message_type': 'private',
        'sub_type': 'group',          # 临时会话
        'fields': _MESSAGE_BASE + ['group_id', 'temp_source'],
    },
    {
        'class': 'initializeMessage + handleGroupMessage',
        'parent': None,
        'post_type': 'message',
        'notice_type': None, 'request_type': None, 'meta_event_type': None,
        'message_type': 'group',
        'sub_type': 'normal',
        'fields': _MESSAGE_BASE + ['group_id', 'group_name'],
    },
    {
        'class': 'initializeMessage (self) + handlePrivateMessage',
        'parent': None,
        'post_type': 'message_sent',
        'notice_type': None, 'request_type': None, 'meta_event_type': None,
        'message_type': 'private',
        'sub_type': 'friend',
        'fields': _MESSAGE_BASE + _MESSAGE_SENT_EXTRA,
    },
    {
        'class': 'initializeMessage (self) + handleGroupMessage',
        'parent': None,
        'post_type': 'message_sent',
        'notice_type': None, 'request_type': None, 'meta_event_type': None,
        'message_type': 'group',
        'sub_type': 'normal',
        'fields': _MESSAGE_BASE + _MESSAGE_SENT_EXTRA + ['group_id', 'group_name'],
    },
]

out.extend(MESSAGE_EVENTS)
out.sort(key=lambda e: tuple(x or '' for x in (
    e['post_type'], e['notice_type'], e['request_type'],
    e['meta_event_type'], e['message_type'], e['sub_type'])))

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print(f'enums: {list(ENUMS)}')
print(f'event classes: {len(events)}   unique: {len(out)}\n')
for e in out:
    tag = ' / '.join(x for x in (e['post_type'], e['notice_type'],
                                 e['request_type'], e['meta_event_type'],
                                 e['message_type'], e['sub_type']) if x)
    print(f"  {tag:<48} fields={len(e['fields']):>2}  {','.join(e['fields'])}")
