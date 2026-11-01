"""独立的回复净化器：保护 Markdown 示例，删除明确的思考块与推理前言。

仅在有规则命中时改变文本；净化为空表示没有可见正文，不能恢复泄漏原文。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TAG_ALIASES: tuple[str, ...] = (
    "think", "thinking", "thought", "thoughts", "reasoning", "analysis",
    "scratchpad", "thought_process", "think_aloud", "reason",
)
_TAG_ALT = "|".join(re.escape(name) for name in TAG_ALIASES)
# 属性值里的 > 不结束标签；名称后必须是空白或 / >，不匹配 <analysis-result>。
_TOKEN_RE = re.compile(
    # 已观测的空畸形块：开标签漏掉 >，但紧接同名闭合标签；只吞标记，不吞正文。
    rf"(?P<empty_malformed><\s*(?P<empty_name>{_TAG_ALT})\s+</\s*(?P=empty_name)\s*>)"
    rf"|<\s*(?P<close>/\s*)?(?:{_TAG_ALT})(?=\s|/?>)"
    r"(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^'\">])*)>"
    r"|(?P<code>`+|~{3,})",
    re.IGNORECASE,
)
_DEFAULT_DECOR = "🧠💭🫧"
# 模型偶尔在正文开头写出的方括号占位标记，如 "[::]"；只在句首删除。
_DEFAULT_LEADING_MARKERS = "[::]"
_MAX_MARKER_LEN = 32
# 单独成词出现在正文开头的推理标签词；不含 "reason"，避免误伤以 Reason 开头的正常英文。
_LEADING_REASON_WORDS = (
    "thought_process", "think_aloud", "scratchpad", "reasoning", "analysis",
    "thinking", "thoughts", "thought", "think",
)
_LEADING_REASON_RE = re.compile(
    # 开头允许有一段「非文字符号」前缀（emoji、圆点、括号等），
    # 例如 "🫧thought"、"· analysis："；只在前缀后面确实紧跟推理标签词时才吃掉。
    r"^(?P<decor>[^\w\u3400-\u4dbf\u4e00-\u9fff]{0,6}[ \t]*)?"
    r"(?P<word>"
    + "|".join(re.escape(word) for word in _LEADING_REASON_WORDS)
    + r")(?![0-9A-Za-z_])[ \t:：\-—–]*"
    r"(?:(?P<break>\r?\n)[ \t]*)?",
    re.IGNORECASE,
)
# 自定义去除/替换的规模上限，避免超长配置拖慢每次回复。
# 词表命中后可能残留在句首的孤立标点，只在原本没有时清理。
_ORPHAN_PUNCT = "，,、。；;：:！!？?　 \t"
_JOINERS = {"\ufe0f", "\ufe0e", "\u200d", "\u200b"}
_DECOR_SEPARATORS = set(" \t\r\n:：-—–·|,，.。>》]】)）")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 需要完整的自我指令或对话分析结构；单个“用户/分析/让我”不作为删除依据。
_REASONING_RE = re.compile(
    r"^(?:"
    r"(?:let\s+me\s+(?:think|analy[sz]e|consider)|"
    r"i\s+(?:need\s+to|have\s+to|should|must|will)\s+(?:first\s+)?"
    r"(?:think|analy[sz]e|consider|respond|reply|answer|craft|keep|maintain)|"
    r"(?:the\s+)?user\s+(?:is|has|asks?|said|says|wants?|requested)\b)|"
    r"(?:analysis|reasoning|thought\s+process)\s*[:：]|"
    r"(?:用户|对方)(?:刚才|现在|这次)?(?:说|问|想要|希望|提到|发来).{0,500}"
    r"(?:应该|需要|可以|安慰|回应|回复|怎么)|"
    r"我(?:需要|应该|必须|得|要)(?:先)?(?:思考|考虑|分析|判断|组织).{0,200}"
    r"(?:回复|回应|回答|语气|角色|设定)|"
    r"(?:想想|想一想|思考一下)(?:(?:该|要|如何|怎么)(?:回|说|答)|\s*$)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_FINAL_LABEL_RE = re.compile(r"^(?:最终(?:回复|回答)|final\s+(?:answer|response))\s*[:：]\s*", re.I)
# 模型把英文思考与中文正文写在同一段时，正文起点是“句末标点 + 可选引号 + 中文”。
# 只用于开头已命中推理标签词的文本，避免动到正常中英混排。
_PLAN_TAIL_RE = re.compile(
    r"[.。!！?？;；:：]\s*[\"“”'「『]?\s*(?=[\u3400-\u4dbf\u4e00-\u9fff])"
)
# 英文思考段的判定下限：字母数量与思考证据。
# 语料里最短的思考段是 "Let's reply casually to 安. "（19 个字母），所以下限取 12；
# 单独的 "Thought you'd like this." 只有 12 个字母且没有中文草稿，不会被当成思考段。
_PLAN_MIN_LETTERS = 12
# 没有中文草稿时，只有整段英文计划长到这个程度才算思考前言。
_PLAN_LONG_LETTERS = 60
# 思考段里被引号包住的中文草稿或被引用的原消息。
_QUOTED_CJK_RE = re.compile(r"[\"“”「『][^\"“”「」『』\n]{0,300}[\"“”」』]")
# 思考段一般以“计划下一步怎么回”的句式开头；没有这个句式就不切，
# 避免把 "Thought you'd like this." 这类正常英文当成思考段删掉。
_PLAN_HEAD_RE = re.compile(
    r"^\s*(?:let'?s|let\s+me|let\s+us|the\s+user|we\s+(?:should|need|can|must)|"
    r"i\s+(?:need|should|will|must|have|'ll|can))\b",
    re.IGNORECASE,
)


# 限定为观测到的控制标记，不匹配任意方括号内容。
_ARTIFACT_RE = re.compile(r"\[+(?:::ethoughts[ \t]*::|::-)\]+|\[{2,}::\]+|\[{3,}\]{2,}", re.I)
_EMPTY_THOUGHT_MARKER_RE = re.compile(r"\[_thought[ \t\r\n]*_\]", re.I)
_CODE_MARK_RE = re.compile(r"(?P<code>`+|~{3,})")
_CHINESE_ANALYSIS_RE = re.compile(
    r"^(?:\*\*|\#{1,6}[ \t]+)?(?:思考过程|思想过程|思维链)"
    r"(?:\*\*)?[ \t]*[:：](?:\*\*)?[ \t]*"
)
_EXPLICIT_FINAL_RE = re.compile(
    r"(?:^|(?<=[。！？；]))[ \t]*(?:\*\*|\#{1,6}[ \t]+)?(?:最终回复|正式回复|最终回答|final\s+(?:answer|response))"
    r"(?:\*\*)?[ \t]*[:：](?:\*\*)?[ \t]*", re.I | re.M,
)
# 默认 emoji 呈现字符，以及显式带 VS16 的文本符号；不删除普通箭头/数学符号。
_EMOJI_BASE = (
    r"[\U0001F004\U0001F0CF\U0001F1E6-\U0001F1FF\U0001F300-\U0001F64F\U0001F680-\U0001F6FF\U0001F900-\U0001FAFF\u231A-\u231B\u23E9-\u23F3\u23F8-\u23FA"
    r"\u25FD-\u25FE\u2614-\u2615\u2648-\u2653\u267F\u2693\u26A1\u26AA-\u26AB"
    r"\u26BD-\u26BE\u26C4-\u26C5\u26CE\u26D4\u26EA\u26F2-\u26F3\u26F5"
    r"\u26FA\u26FD\u2705\u270A-\u270B\u2728\u274C\u274E\u2753-\u2755"
    r"\u2757\u2795-\u2797\u27B0\u27BF\u2B1B-\u2B1C\u2B50\u2B55]"
    r"|[\u2600-\u2604\u263A\u270C\u2763-\u2764]"
    r"|[\u00A9\u00AE\u203C\u2049\u2122\u2139\u2194-\u2199\u21A9-\u21AA"
    r"\u2328\u23CF\u23ED-\u23EF\u23F1-\u23F2\u24C2\u25AA-\u25AB\u25B6"
    r"\u25C0\u25FB-\u25FC\u2600-\u2604\u260E\u2611\u2618\u261D\u2620"
    r"\u2622-\u2623\u2626\u262A\u262E-\u262F\u2638-\u263A\u2640\u2642"
    r"\u265F-\u2660\u2663\u2665-\u2666\u2668\u267B\u267E\u2692\u2694-\u2697"
    r"\u2699\u269B-\u269C\u26A0\u26A7\u26B0-\u26B1\u26C8\u26CF\u26D1"
    r"\u26D3\u26E9\u26F0-\u26F1\u26F4\u26F7-\u26F9\u2702\u2708-\u2709"
    r"\u270C-\u270D\u270F\u2712\u2714\u2716\u271D\u2721\u2733-\u2734"
    r"\u2744\u2747\u2763-\u2764\u27A1\u2934-\u2935\u2B05-\u2B07\u3030"
    r"\u303D\u3297\u3299]\uFE0F"
)
_EMOJI_UNIT = rf"(?:{_EMOJI_BASE})[\uFE0F\uFE0E]?[\U0001F3FB-\U0001F3FF]?"
_EMOJI_RE = re.compile(
    rf"[#*0-9]\uFE0F?\u20E3|(?:{_EMOJI_UNIT})(?:\u200D(?:{_EMOJI_UNIT}))*"
    r"[\U000E0020-\U000E007E]*\U000E007F?"
)
_PRIVATE_RE = re.compile(r"[\uE000-\uF8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]")


def _code_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    position = 0
    while (match := _CODE_MARK_RE.search(text, position)) is not None:
        position = _code_end(text, match)
        if position > match.end():
            spans.append((match.start(), position))
    return spans


def _strip_artifact_edges(text: str) -> tuple[str, int]:
    original = text
    while True:
        before = text
        stripped = text.strip()
        if stripped.startswith('⌊⌊') and stripped.endswith('⌉⌉'):
            text = stripped[2:-2]
            continue
        # 仅清理句首的精确空伪标记；不把其中的 thought 扩大为内容关键词。
        match = _EMPTY_THOUGHT_MARKER_RE.match(stripped)
        if match:
            text = stripped[match.end():]
            continue
        match = _ARTIFACT_RE.match(stripped)
        if match:
            text = stripped[match.end():]
            continue
        matches = list(_ARTIFACT_RE.finditer(stripped))
        if matches and matches[-1].end() == len(stripped) and matches[-1].group() != '[::]':
            last = matches[-1]
            if not any(a <= last.start() < b for a, b in _code_spans(stripped)):
                text = stripped[:last.start()]
        if text == before:
            break
    return text, len(original) - len(text)


def _strip_visible_symbols(text: str, emoji: bool, private: bool) -> tuple[str, int, int]:
    pieces = []
    cursor = emoji_removed = private_removed = 0

    def clean(segment: str) -> str:
        nonlocal emoji_removed, private_removed
        if private:
            segment, count = _PRIVATE_RE.subn('', segment)
            private_removed += count
        if emoji:
            segment, count = _EMOJI_RE.subn('', segment)
            emoji_removed += count
        return segment

    for start, end in _code_spans(text):
        pieces.extend((clean(text[cursor:start]), text[start:end]))
        cursor = end
    pieces.append(clean(text[cursor:]))
    return ''.join(pieces), emoji_removed, private_removed


def _strip_chinese_analysis(text: str) -> tuple[str, int]:
    """明确分析标题后，只有显式最终回复标签解除隐藏；构思不是正文。"""
    stripped = text.lstrip()
    heading = _CHINESE_ANALYSIS_RE.match(stripped)
    if heading is None:
        return text, 0
    spans = _code_spans(stripped)
    for match in _EXPLICIT_FINAL_RE.finditer(stripped, heading.end()):
        if not any(a <= match.start() < b for a, b in spans):
            body = stripped[match.end():]
            return body, len(text) - len(body)
    return '', len(text)


@dataclass
class SanitizeReport:
    tags_removed: int = 0
    decor_chars_removed: int = 0
    reason_words_removed: int = 0
    marker_chars_removed: int = 0
    preamble_cut_chars: int = 0
    incomplete_blocks: int = 0
    emoji_sequences_removed: int = 0
    private_chars_removed: int = 0
    analysis_cut_chars: int = 0
    reason: str = "clean"
    changed: bool = False

    def as_dict(self) -> dict[str, object]:
        return dict(vars(self))


def _code_end(text: str, match: re.Match[str]) -> int:
    """找到当前 Markdown 代码区末尾；无合法代码区则返回记号末尾。"""
    marker = match.group("code")
    start, end = match.span()
    line_prefix = text[text.rfind("\n", 0, start) + 1:start]
    if len(marker) >= 3 and len(line_prefix) <= 3 and not line_prefix.strip(" "):
        line_end = text.find("\n", end)
        if line_end < 0:
            return len(text)
        closing = re.compile(
            rf"^[ ]{{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*\r?$", re.M,
        ).search(text, line_end + 1)
        return closing.end() if closing else len(text)
    if marker.startswith("`"):
        closing = re.compile(rf"(?<!`)`{{{len(marker)}}}(?!`)").search(text, end)
        if closing:
            return closing.end()
    return end


def _strip_tags(text: str) -> tuple[str, int, int]:
    """按深度删除嵌套/异名思考块，未闭合块一直隐藏到末尾。

    Markdown 代码区只在思考块之外受到保护，不能用代码围栏暴露块内推理。
    """
    parts: list[str] = []
    position = cursor = depth = removed = 0
    while (match := _TOKEN_RE.search(text, position)) is not None:
        position = match.end()
        if match.group("code"):
            if depth == 0:
                position = _code_end(text, match)
            continue
        if match.group("empty_malformed"):
            if depth == 0:
                parts.append(text[cursor:match.start()])
                cursor = position
                removed += 1
            continue
        closing = bool(match.group("close"))
        self_closing = match.group("attrs").rstrip().endswith("/")
        if closing:
            if depth:
                depth -= 1
                if depth == 0:
                    cursor = position
                    removed += 1
            else:
                # 单独的闭合记号没有明确的隐藏起点，只移除记号本身。
                parts.append(text[cursor:match.start()])
                cursor = position
                removed += 1
        elif self_closing:
            if depth == 0:
                parts.append(text[cursor:match.start()])
                cursor = position
                removed += 1
        else:
            if depth == 0:
                parts.append(text[cursor:match.start()])
            depth += 1
    incomplete = int(depth > 0)
    if incomplete:
        removed += 1
    else:
        parts.append(text[cursor:])
    return "".join(parts), removed, incomplete


_CORNER_OPEN = "⌊思考过程⌉"
_CORNER_TOKEN_RE = re.compile(r"⌊思考过程⌉|⌈")


def _strip_corner_thought(text: str) -> tuple[str, int, int]:
    """删除句首明确的角括号思考块；不碰代码示例和正文中的标记引用。

    ⌈ 是此输出格式的正文分界。缺少分界时隐藏整块，不能只删标题。
    嵌套及连续块按深度处理，不依据具体推理内容或长度猜测正文。
    """
    removed = 0
    while text.lstrip().startswith(_CORNER_OPEN):
        stripped = text.lstrip()
        depth = 1
        for token in _CORNER_TOKEN_RE.finditer(stripped, len(_CORNER_OPEN)):
            depth += 1 if token.group() == _CORNER_OPEN else -1
            if depth == 0:
                text = stripped[token.end():]
                removed += 1
                break
        else:
            return "", removed + 1, 1
    return text, removed, 0


def _strip_leading_decor(text: str, decor: str) -> tuple[str, int]:
    decor_only = {char for char in decor if not char.isspace()}
    if not decor_only:
        return text, 0
    usable = decor_only | _JOINERS
    index = 0
    while index < len(text) and (text[index] in usable or text[index].isspace()):
        index += 1
    if not any(char in decor_only for char in text[:index]):
        return text, 0
    while index < len(text) and (
        text[index] in usable or text[index].isspace() or text[index] in _DECOR_SEPARATORS
    ):
        index += 1
    return text[index:], index


def _parse_leading_markers(spec: str) -> tuple[str, ...]:
    """把逗号分隔的标记配置解析为元组；过长的项直接忽略，避免误删正文。"""
    markers: list[str] = []
    for raw in str(spec or "").split(","):
        marker = raw.strip()
        if marker and len(marker) <= _MAX_MARKER_LEN and marker not in markers:
            markers.append(marker)
    return tuple(markers)


def _strip_leading_markers(text: str, markers: tuple[str, ...]) -> tuple[str, int]:
    """反复删除出现在正文开头的标记；正文中间的同名片段一律不动。"""
    if not markers:
        return text, 0
    removed = 0
    while True:
        stripped = text.lstrip()
        lead = len(text) - len(stripped)
        for marker in markers:
            if stripped.startswith(marker):
                text = stripped[len(marker):]
                removed += lead + len(marker)
                break
        else:
            break
    return text, removed


def _has_drafting_evidence(text: str) -> bool:
    """思考段里出现过被引号包住的中文草稿（或引用的原消息），或本身就是一大段英文计划。"""
    for quote in _QUOTED_CJK_RE.finditer(text):
        if len(_CJK_RE.findall(quote.group())) >= 2:
            return True
    letters = sum(1 for char in text if char.isascii() and char.isalpha())
    return letters >= _PLAN_LONG_LETTERS


def _reason_plan_tail(rest: str) -> str | None:
    """从“英文思考 + 中文正文”同段文本里切出中文正文；证据不足时返回 None。

    要求开头是“计划怎么回”的英文句式，且思考段里留有中文草稿或被引用的原消息，
    才会按最后一个“句末标点 + 中文”边界切开。
    """
    last = None
    for match in _PLAN_TAIL_RE.finditer(rest):
        last = match
    if last is None:
        return None
    head = rest[: last.end()]
    if _PLAN_HEAD_RE.match(head) is None:
        return None
    letters = sum(1 for char in head if char.isascii() and char.isalpha())
    if letters < _PLAN_MIN_LETTERS or not _has_drafting_evidence(rest):
        return None
    tail = rest[last.end():].lstrip(" \t\"'“”「」『』（）()…")
    if len(_CJK_RE.findall(tail)) < 2:
        return None
    # 切点吃掉了思考段末尾的开引号；正文自带的闭引号此时落单，一并去掉。
    if tail.count('"') % 2:
        stripped = tail.rstrip()
        if stripped.endswith('"'):
            tail = stripped[:-1].rstrip()
    return tail


def _strip_leading_reason_word(text: str) -> tuple[str, int]:
    """删除正文开头的推理标签词，并切掉同一段里的英文思考。

    同一行内直接接中文时整词删除；标签词后先跟英文思考、后面才是中文正文时，
    按最后一个“句末标点 + 中文”边界切到正文，避免把思考整段发出去。
    """
    stripped = text.lstrip()
    if not stripped:
        return text, 0
    match = _LEADING_REASON_RE.match(stripped)
    if match is None:
        return text, 0
    rest = stripped[match.end():]
    if not rest.strip():
        return text, 0
    if _CJK_RE.match(rest.lstrip()):
        return rest, 1
    tail = _reason_plan_tail(rest)
    if tail is not None:
        return tail, 1
    if match.group("break") is not None:
        return rest, 1
    return text, 0


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"\r?\n[ \t]*\r?\n", text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    spans = [(start, end) for start, end in spans if text[start:end].strip()]
    if len(spans) > 1:
        return spans
    return [(match.start(), match.end()) for match in re.finditer(r"[^\r\n]+", text) if match.group().strip()]


def _cut_preamble(text: str, min_cjk_ratio: float, max_cut_chars: int) -> tuple[str, int]:
    """只切连续且明确的推理段落；保留普通英文问候与普通中文首段。"""
    if max_cut_chars <= 0:
        return text, 0
    spans = _paragraph_spans(text)
    head_count = 0
    for start, end in spans:
        if not _REASONING_RE.search(text[start:end].strip()):
            break
        head_count += 1
    if not head_count:
        return text, 0
    cut = spans[head_count][0] if head_count < len(spans) else len(text)
    if cut > max_cut_chars:
        return text, 0
    if head_count == len(spans):
        return "", cut
    body = text[cut:]
    first_body = text[spans[head_count][0]:spans[head_count][1]].strip()
    label = _FINAL_LABEL_RE.match(first_body)
    ratio = len(_CJK_RE.findall(first_body)) / max(len(first_body), 1)
    if not label and ratio < min_cjk_ratio:
        return text, 0
    if label:
        # first_body 只去掉了首尾空白，匹配位置需要加回首部空白。
        extra = len(body) - len(body.lstrip()) + label.end()
        cut += extra
        body = body[extra:]
    return body, cut


def sanitize(
    text: str,
    *,
    strip_tags: bool = True,
    strip_decorations: bool = True,
    decoration_chars: str = _DEFAULT_DECOR,
    leading_markers: str = _DEFAULT_LEADING_MARKERS,
    strip_reason_words: bool = True,
    preamble_mode: str = "heuristic",
    min_cjk_ratio: float = 0.5,
    max_cut_chars: int = 1500,
    strip_artifacts: bool = True,
    strip_chinese_analysis: bool = True,
    strip_emoji: bool = False,
    strip_private_use: bool = False,
) -> tuple[str, SanitizeReport]:
    """返回净化文本与报告。空文本为无正文，调用方应停止发送，禁止回退原文。

    heuristic 需要标签/装饰证据；always 不要求标记，但仍要求明确的推理句式；
    off 关闭前言处理。代码示例有意保留，其中的标签不会成为前言处理依据。
    """
    mode = (preamble_mode or "heuristic").strip().lower()
    if mode not in {"off", "heuristic", "always"}:
        raise ValueError(f"无效的 preamble_mode: {mode!r}")
    original = str(text or "")
    report = SanitizeReport()
    if not original.strip():
        report.reason = "empty"
        return original, report
    working = original
    if strip_tags:
        working, report.tags_removed, report.incomplete_blocks = _strip_tags(working)
    markers = _parse_leading_markers(leading_markers)
    if (strip_tags or strip_decorations or markers or strip_reason_words
            or strip_artifacts or strip_chinese_analysis or strip_emoji or strip_private_use):
        # 装饰 emoji、方括号及角括号思考块可能交替出现，循环到稳定。
        while True:
            before = working
            if strip_artifacts:
                working, removed = _strip_artifact_edges(working)
                report.marker_chars_removed += removed
            if strip_tags:
                working, removed, incomplete = _strip_corner_thought(working)
                report.tags_removed += removed
                report.incomplete_blocks += incomplete
            if strip_decorations:
                working, removed = _strip_leading_decor(working, decoration_chars)
                report.decor_chars_removed += removed
            if markers:
                working, removed = _strip_leading_markers(working, markers)
                report.marker_chars_removed += removed
            if strip_reason_words:
                working, hits = _strip_leading_reason_word(working)
                report.reason_words_removed += hits
                # 标签词已被模型省掉、但英文计划仍留在开头时，同样切到中文正文。
                plan_tail = _reason_plan_tail(working.lstrip())
                if plan_tail is not None and plan_tail != working:
                    working = plan_tail
                    report.reason_words_removed += 1
            if strip_chinese_analysis:
                working, removed = _strip_chinese_analysis(working)
                report.analysis_cut_chars += removed
            if strip_emoji or strip_private_use:
                working, emoji_count, private_count = _strip_visible_symbols(working, strip_emoji, strip_private_use)
                report.emoji_sequences_removed += emoji_count
                report.private_chars_removed += private_count
            if working == before:
                break
    marker_found = (
        report.tags_removed > 0
        or report.decor_chars_removed > 0
        or report.reason_words_removed > 0
    )
    if mode != "off" and (mode == "always" or marker_found):
        working, report.preamble_cut_chars = _cut_preamble(working, min_cjk_ratio, max_cut_chars)
    # 没有命中规则时连首尾空白也保持不变，避免破坏代码或格式。
    if not (
        marker_found
        or report.marker_chars_removed
        or report.preamble_cut_chars
        or report.analysis_cut_chars
        or report.emoji_sequences_removed
        or report.private_chars_removed
    ):
        return original, report
    working = working.strip()
    report.changed = working != original
    if not working:
        report.reason = "no_visible_body"
    elif report.analysis_cut_chars:
        report.reason = "chinese_analysis_cut"
    elif report.preamble_cut_chars:
        report.reason = "preamble_cut"
    elif report.incomplete_blocks:
        report.reason = "unclosed_tags_removed"
    elif report.tags_removed:
        report.reason = "tags_removed"
    elif report.reason_words_removed:
        report.reason = "reason_word_removed"
    elif report.marker_chars_removed:
        report.reason = "marker_removed"
    elif report.emoji_sequences_removed:
        report.reason = "emoji_removed"
    elif report.private_chars_removed:
        report.reason = "private_use_removed"
    elif report.decor_chars_removed:
        report.reason = "decor_removed"
    else:
        report.reason = "custom_rules"
    return working, report
