"""开头占位标记 [::] 的剥离规则回归。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR.parent))

from Sol_reply_sanitizer.sanitizer import sanitize  # noqa: E402


def run(text: str, **kwargs):
    return sanitize(text, **kwargs)


class LeadingMarkerTests(unittest.TestCase):
    def test_strips_single_leading_marker(self):
        cleaned, report = run("[::]这架势，看着挺有意思。")
        self.assertEqual(cleaned, "这架势，看着挺有意思。")
        self.assertEqual(report.reason, "marker_removed")
        self.assertTrue(report.changed)
        self.assertGreater(report.marker_chars_removed, 0)

    def test_strips_repeated_markers(self):
        cleaned, _ = run("[::][::]正文还在。")
        self.assertEqual(cleaned, "正文还在。")

    def test_strips_marker_after_decorations(self):
        cleaned, report = run("🧠💭[::]正文还在。")
        self.assertEqual(cleaned, "正文还在。")
        self.assertTrue(report.changed)

    def test_strips_marker_after_think_block(self):
        cleaned, report = run("<think>内部推理</think>[::]正文。")
        self.assertEqual(cleaned, "正文。")
        self.assertEqual(report.reason, "tags_removed")

    def test_marker_with_leading_whitespace_and_newline(self):
        cleaned, _ = run("\n  [::]\n正文。")
        self.assertEqual(cleaned, "正文。")

    def test_only_marker_leaves_empty_body(self):
        cleaned, report = run("[::]")
        self.assertEqual(cleaned, "")
        self.assertEqual(report.reason, "no_visible_body")

    def test_marker_in_middle_is_preserved(self):
        text = "我说[::]这个不算开头。"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_marker_at_tail_is_preserved(self):
        text = "正文照旧。[::]"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_marker_inside_code_fence_is_preserved(self):
        text = "```\n[::]示例\n```"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_empty_marker_config_disables_rule(self):
        text = "[::]正文还在。"
        cleaned, report = run(text, leading_markers="")
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_custom_marker_list(self):
        cleaned, _ = run("[abc]正文。", leading_markers="[abc],[::]")
        self.assertEqual(cleaned, "正文。")

    def test_overlong_marker_is_ignored(self):
        text = "[" + "x" * 40 + "]正文。"
        cleaned, report = run(text, leading_markers=text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_idempotent(self):
        once, _ = run("[::][::]正文还在。")
        twice, report = run(once)
        self.assertEqual(once, twice)
        self.assertFalse(report.changed)

    def test_marker_does_not_expose_preamble_cutting(self):
        text = "[::]用户问我这个问题，我应该怎么回答呢"
        cleaned, report = run(text)
        self.assertEqual(cleaned, "用户问我这个问题，我应该怎么回答呢")
        self.assertEqual(report.preamble_cut_chars, 0)

    def test_normal_text_untouched(self):
        for text in ("你好呀", "Hello there", "（｡･ω･｡）", "[图片]"):
            cleaned, report = run(text)
            self.assertEqual(cleaned, text)
            self.assertFalse(report.changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
