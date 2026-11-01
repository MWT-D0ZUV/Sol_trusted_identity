"""Sol_reply_sanitizer.sanitizer 的离线回归测试。

不依赖 MaiBot SDK / 运行中的 Host，直接跑：
    <environment python> tests/test_sanitizer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sanitizer import sanitize  # noqa: E402

CASES: list[tuple[str, str, str]] = []


def case(name: str, text: str, expected: str) -> None:
    CASES.append((name, text, expected))


# ---------------------------------------------------------------- 标签块
case(
    "标准 thought 块",
    "<thought>用户问我吃了吗，应该轻松回一句。</thought>吃啦，你呢？",
    "吃啦，你呢？",
)
case(
    "thinking 块",
    "<thinking>分析语境</thinking>今天有点忙，刚吃完。",
    "今天有点忙，刚吃完。",
)
case(
    "异名配对标签",
    "<thinking>推理中</thought>好的呀～",
    "好的呀～",
)
case(
    "落单闭合标签",
    "在想什么呢？</thought>",
    "在想什么呢？",
)
case(
    "落单开启标签",
    "<reasoning>嗯……那就这样吧。",
    "",
)
case(
    "正文中间的标签块",
    "好的<thought>内部推理</thought>，收到啦",
    "好的，收到啦",
)
case(
    "多段标签块",
    "<thought>a</thought><analysis>b</analysis>结论在这儿",
    "结论在这儿",
)

# ---------------------------------------------------------------- 装饰前缀
case(
    "🧠💭 前缀与冒号",
    "🧠💭：用户说今天很累，应该安慰一下。\n\n辛苦啦，先歇会儿吧。",
    "辛苦啦，先歇会儿吧。",
)
case(
    "带变体选择符的装饰",
    "🧠\ufe0f💭 想想怎么回\n\n我在呢。",
    "我在呢。",
)
case("装饰后直接接正文", "💭好的，我明白了。", "好的，我明白了。")
case("正文中间的装饰不动", "嗯嗯🧠 明白", "嗯嗯🧠 明白")

# ---------------------------------------------------------------- 思考前言
case(
    "英文前言 + 中文正文",
    "🧠💭 Let me think about how to respond to this.\n\n那就一起去看电影吧！",
    "那就一起去看电影吧！",
)
case(
    "无泄漏标记的英文段落保持原样",
    "Good morning!\n\n早上好呀，今天想做什么？",
    "Good morning!\n\n早上好呀，今天想做什么？",
)
case(
    "中文元推理前言（含提示词）",
    "🧠💭用户说今天很累，应该安慰一下。\n\n辛苦啦，先歇会儿吧。",
    "辛苦啦，先歇会儿吧。",
)
case(
    "中文首段但不是元推理",
    "🧠💭今天过得还行。\n\n你呢？",
    "今天过得还行。\n\n你呢？",
)
case(
    "纯英文回复不受影响",
    "Sure, I can help with that.",
    "Sure, I can help with that.",
)
case(
    "多段中文保持原样",
    "第一段说说今天的事。\n\n第二段继续聊。",
    "第一段说说今天的事。\n\n第二段继续聊。",
)
case(
    "正常回复不受影响",
    "我刚看到你的消息，怎么啦？",
    "我刚看到你的消息，怎么啦？",
)
case("空回复保持原样", "", "")
case("纯空白保持原样", "   \n ", "   \n ")


ATTEMPTS = [0]


def expect(name: str, text: str, expected: str, **kwargs) -> str | None:
    ATTEMPTS[0] += 1
    actual, report = sanitize(text, **kwargs)
    if actual != expected:
        return f"{name}:\n  期望 {expected!r}\n  实际 {actual!r}\n  report={report.as_dict()}"
    return None


def main() -> int:
    # Windows 控制台默认 GBK，输出含 emoji 时避免 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[attr-defined]
        except Exception:
            pass
    failures: list[str] = []
    for name, text, expected in CASES:
        problem = expect(name, text, expected)
        if problem:
            failures.append(problem)

    # ---- 参数开关
    problem = expect(
        "off 模式仍剥标签但不切前言",
        "🧠💭 Let me think.\n\n你好",
        "Let me think.\n\n你好",
        preamble_mode="off",
    )
    if problem:
        failures.append(problem)

    problem = expect(
        "always 模式在无标记时也切前言",
        "Let me think about this one first.\n\n你好呀",
        "你好呀",
        preamble_mode="always",
    )
    if problem:
        failures.append(problem)

    problem = expect(
        "max_cut_chars 保护长前言",
        "🧠💭 " + ("analysis " * 400) + "\n\n你好呀",
        ("analysis " * 400) + "\n\n你好呀",
        max_cut_chars=100,
    )
    if problem:
        failures.append(problem)

    problem = expect(
        "关闭标签剥离",
        "<thought>推理</thought>你好",
        "<thought>推理</thought>你好",
        strip_tags=False,
    )
    if problem:
        failures.append(problem)

    problem = expect(
        "自定义装饰字符",
        "🤔：想想怎么回\n\n好啊",
        "好啊",
        decoration_chars="🤔",
    )
    if problem:
        failures.append(problem)

    # ---- 报告字段
    _, report = sanitize("<thought>x</thought>🧠💭 hi")
    if report.tags_removed != 1:
        failures.append(f"报告 tags_removed 期望 1，实际 {report.tags_removed}")
    if not report.changed:
        failures.append("报告 changed 应为 True")

    _, clean_report = sanitize("你好呀")
    if clean_report.changed or clean_report.reason != "clean":
        failures.append(f"干净文本报告异常：{clean_report.as_dict()}")

    # ---- 代码块保护
    fenced = "```python\nprint('hi')\n```"
    problem = expect("代码块开头不改写", fenced, fenced)
    if problem:
        failures.append(problem)

    # ---- 中文正文内嵌少量英文不触发前言切除
    mixed = "🧠💭 用 English 混着说\n\n今天天气不错，出去走走吧。"
    problem = expect(
        "中文为主的段落不当作前言",
        mixed,
        "用 English 混着说\n\n今天天气不错，出去走走吧。",
    )
    if problem:
        failures.append(problem)

    total = ATTEMPTS[0] + 2  # 两次报告字段检查
    if failures:
        print(f"FAILED {len(failures)}/{total}")
        for item in failures:
            print(" -", item)
        return 1

    print(f"OK {total}/{total} 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
