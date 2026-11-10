"""Extract every OneBot action + its full payload parameter list from napcat.mjs.

Approach
--------
Each action is a class in the bundled ESM with `actionName = ne.<EnumName>;`.
The *class* is what carries the schema, so each `actionName` occurrence must be
mapped back to its enclosing class by position (the enum name is not the class
name). `payloadSchema` is either an inline `l.Object({...})` or a reference to a
module-level `const X = l.Object({...})`, and message-sending classes inherit it
from a base class via `extends`, so inheritance is followed.


from pathlib import Path

# 仓库根目录（tools/ 的上一级）
ROOT = Path(__file__).resolve().parent.parent

Class bodies are delimited by the next top-level `class ` line rather than brace
counting, because the bundle contains braces inside string/regex literals.
"""
import re
import json

SRC = r'C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\napcat.mjs'
OUT = str(ROOT / 'tools' / '_actions.json')

src = open(SRC, encoding='utf-8', errors='replace').read()

# ---------------------------------------------------------------- action enum
enum = {}
for m in re.finditer(r'^\s*(\w+):\s*"([a-zA-Z0-9_.]+)",\s*$', src, re.M):
    enum[m.group(1)] = m.group(2)


def match_brace(s, start):
    """Brace matching aware of string / template literals."""
    depth, i, in_str = 0, start, None
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in '"\'`':
            in_str = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level(body):
    parts, cur, depth, in_str, i = [], [], 0, None, 0
    while i < len(body):
        c = body[i]
        if in_str:
            cur.append(c)
            if c == '\\':
                if i + 1 < len(body):
                    cur.append(body[i + 1])
                    i += 2
                    continue
            elif c == in_str:
                in_str = None
        elif c in '"\'`':
            in_str = c
            cur.append(c)
        elif c in '{[(':
            depth += 1
            cur.append(c)
        elif c in '}])':
            depth -= 1
            cur.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = ''.join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def infer_type(expr):
    if 'l.Object' in expr:
        return 'dict'
    if 'l.Array' in expr:
        return 'list'
    if 'l.Null' in expr and 'Union' not in expr:
        return 'None'
    tnames = [t for t in re.findall(r'\bl\.(\w+)', expr)
              if t not in ('Object', 'Array', 'Union', 'Optional', 'Nullable', 'Literal')]
    if tnames:
        return {'number': 'int', 'string': 'str', 'boolean': 'bool',
                'any': 'Any', 'unknown': 'Any'}.get(tnames[0].lower(), 'Any')
    return 'str' if 'l.Literal' in expr else 'Any'


def parse_schema(body):
    fields = []
    for part in split_top_level(body):
        if not part or part.startswith('//'):
            continue
        m = re.match(r'^([\w$]+)\s*:\s*(.+)$', part, re.S)
        if not m:
            continue
        name, expr = m.group(1), m.group(2).strip()

        default = None
        dm = re.search(r'default:\s*([^,}]+)', expr)
        if dm:
            default = dm.group(1).strip()

        desc = None
        sm = re.search(r'description:\s*"([^"]*)"', expr)
        if sm:
            desc = sm.group(1)

        fields.append({
            'name': name,
            'type': infer_type(expr),
            'default': default,
            'desc': desc,
            'optional': 'Optional' in expr or 'Nullable' in expr,
            'literals': re.findall(r'l\.Literal\("([^"]*)"\)', expr),
        })
    return fields


def object_at(text, pos):
    brace = text.find('{', pos)
    if brace < 0:
        return None
    end = match_brace(text, brace)
    if end < 0:
        return None
    return parse_schema(text[brace + 1:end])


# --------------------------------------------------- const ident -> schema map
# Two declaration shapes occur in the bundle:
#   const S_e = l.Object({...})
#   }), Kwe = l.Object({...})          <- chained declarator, no keyword
const_schemas = {}
for m in re.finditer(r'(?:(?:const|var|let)\s+|[,;]\s*)([\w$]+)\s*=\s*l\.Object\(', src):
    f = object_at(src, m.end() - 1)
    if f is not None:
        const_schemas[m.group(1)] = f

# ------------------------------------------------------ class body boundaries
class_starts = [(m.start(), m.group(1), m.group(2))
                for m in re.finditer(r'^class\s+([\w$]+)(?:\s+extends\s+([\w$]+))?\s*\{',
                                     src, re.M)]
class_bounds = {}
for idx, (pos, name, parent) in enumerate(class_starts):
    end = class_starts[idx + 1][0] if idx + 1 < len(class_starts) else len(src)
    class_bounds[name] = {'parent': parent, 'start': pos, 'end': end}


def enclosing_class(pos):
    """Find the class whose body contains absolute offset pos."""
    for name, b in class_bounds.items():
        if b['start'] <= pos < b['end']:
            return name
    return None


# ------------------------------------------------ payloadExample tables
example_params = {}
for m in re.finditer(r'^\s{2}(\w+):\s*\{\s*\n\s*payload:\s*\{([^}]*)\}', src, re.M):
    names = re.findall(r'(\w+)\s*:', m.group(2))
    if names:
        example_params.setdefault(m.group(1), names)


def class_schema(cls, seen=None):
    """Resolve payloadSchema for a class, following `extends` chains."""
    if seen is None:
        seen = set()
    if cls in seen or cls not in class_bounds:
        return None
    seen.add(cls)
    b = class_bounds[cls]
    body = src[b['start']:b['end']]

    pm = re.search(r'payloadSchema\s*=\s*([^;]+);', body)
    if pm:
        rhs = pm.group(1).strip()
        if rhs.startswith('l.Object'):
            got = object_at(body, pm.start() + len('payloadSchema = '))
            if got is not None:
                return got
        else:
            ident = rhs.split('.')[0].strip()
            if ident in const_schemas:
                return const_schemas[ident]
    if b['parent']:
        return class_schema(b['parent'], seen)
    return None


# --------------------------------------------------------- per action results
results = []
for m in re.finditer(r'actionName = ne\.(\w+);', src):
    enum_name = m.group(1)
    cls = enclosing_class(m.start())
    action = enum.get(enum_name, enum_name)
    body = src[class_bounds[cls]['start']:class_bounds[cls]['end']] if cls else ''

    summary = None
    sm = re.search(r'actionSummary\s*=\s*"([^"]*)"', body)
    if sm:
        summary = sm.group(1)

    results.append({
        'class': cls,
        'action': action,
        'summary': summary,
        'fields': class_schema(cls) if cls else [],
        'example': example_params.get(cls) if cls else None,
    })

best = {}
for r in results:
    cur = best.get(r['action'])
    if cur is None or len(r['fields'] or []) > len(cur['fields'] or []):
        best[r['action']] = r

for r in best.values():
    if not r['fields'] and r['example']:
        r['fields'] = [{'name': n, 'type': 'Any', 'default': None, 'desc': None,
                        'optional': True, 'literals': []} for n in r['example']]
    if r['fields'] is None:
        r['fields'] = []

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(list(best.values()), f, ensure_ascii=False, indent=1)

with_fields = [r for r in best.values() if r['fields']]
print(f'actions: {len(best)}   with params: {len(with_fields)}   '
      f'total params: {sum(len(r["fields"]) for r in with_fields)}')

for a in ('send_private_msg', 'send_group_msg', 'send_msg', 'delete_msg',
          'set_group_ban', 'get_group_member_info', 'send_poke', 'get_stranger_info',
          'set_msg_emoji_like', 'get_msg'):
    r = best.get(a)
    if r:
        print(f"\n{a}  [{r['summary']}]  class={r['class']}")
        for fl in r['fields']:
            print(f"   {fl['name']:<22} {fl['type']:<8} "
                  f"default={str(fl['default']):<8} opt={fl['optional']}  {fl['desc']}")
