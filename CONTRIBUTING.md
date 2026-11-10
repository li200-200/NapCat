# 贡献指南

## 代码来源

`napcat/api.py` 和 `napcat/events.py` 是**自动生成**的，不要手工编辑。

改动请走生成器：

```bash
# 修改 tools/_gen.py 或 tools/_gen_events.py
python tools/_gen.py
python tools/_gen_events.py
```

生成器的输入是 `tools/_actions.json` 和 `tools/_events.json`，这两个文件由 `tools/_extract*.py` 从 NapCat 的 `napcat.mjs` 抽取。

## NapCat 升级后

1. 确认 `C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ\napcat.mjs` 存在
2. 依次重跑抽取和生成脚本
3. 跑测试，确认没退化

```bash
python tools/_extract.py
python tools/_gen.py
python tools/_extract_events.py
python tools/_gen_events.py
python tests/test_qqbot_en.py
python tests/test_qqbot_events.py
```

## 测试

```bash
python tests/test_qqbot_en.py              # API 模块
python tests/test_qqbot_events.py          # 事件模块
python examples/demo_events.py --offline   # 离线全链路
```

前两个不需要 NapCat 在跑（用假 session）。第三个也不需要。

## 抽取器的已知脆弱点

改 `tools/_extract*.py` 时注意这三点，都是实际踩过的：

1. **actionName 的枚举名不是类名。** 要按 `actionName = ne.XXX` 出现的位置反查所在 class，不能用枚举名当类名。

2. **payloadSchema 会沿 `extends` 继承。** 必须递归回溯父类。

3. **const 声明有链式形态。** `}), Kwe = l.Object({...})` 这种要一并匹配。

4. **类体边界不能用大括号计数。** 打包产物里字符串和正则字面量含大量 `{}`，用「下一个顶层 `class `」作边界。

5. **post_type 是枚举引用。** `Fl.NOTICE` 要解析 `var Fl = ((t) => (t.NOTICE = "notice", ...))` 才能拿到字面值。

## 提交规范

- commit message 用中文或英文都可以，说明改了什么、为什么
- 改了生成器要同时提交重新生成的文件
- 不要提交 `messages.jsonl`、`__pycache__` 等运行时产物（已在 `.gitignore`）
