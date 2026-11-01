"""开头裸推理词、英文计划前言与方括号标记的回归。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR.parent))

from Sol_reply_sanitizer.sanitizer import sanitize  # noqa: E402


def run(text: str, **kwargs):
    return sanitize(text, **kwargs)


class LeadingReasonWordTests(unittest.TestCase):
    def test_emoji_then_blank_line_then_word(self):
        cleaned, report = run("🧠\n\nthought\n\n你好，今天过得怎么样？")
        self.assertEqual(cleaned, "你好，今天过得怎么样？")
        self.assertEqual(report.reason, "reason_word_removed")
        self.assertEqual(report.reason_words_removed, 1)
        self.assertTrue(report.changed)

    def test_word_on_own_line(self):
        cleaned, report = run("thought\n\n你来了。")
        self.assertEqual(cleaned, "你来了。")
        self.assertEqual(report.reason_words_removed, 1)

    def test_emoji_glued_to_word(self):
        cleaned, _ = run("🧠thought 大上午十一点就道晚安了")
        self.assertEqual(cleaned, "大上午十一点就道晚安了")

    def test_word_then_space_then_chinese(self):
        cleaned, _ = run("thought 前半句听着还挺让人感动的")
        self.assertEqual(cleaned, "前半句听着还挺让人感动的")

    def test_colon_variant(self):
        cleaned, _ = run("Analysis：今天这局打得不错")
        self.assertEqual(cleaned, "今天这局打得不错")

    def test_english_sentence_is_preserved(self):
        for text in ("Thought you'd like this.", "Thoughtful reply.", "Think about it later."):
            cleaned, report = run(text)
            self.assertEqual(cleaned, text)
            self.assertFalse(report.changed)

    def test_bare_word_without_body_is_preserved(self):
        cleaned, report = run("thought")
        self.assertEqual(cleaned, "thought")
        self.assertFalse(report.changed)

    def test_reason_word_not_in_word_list(self):
        text = "Reason why I left: 太吵了"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_switch_off_keeps_word(self):
        text = "thought\n\n你来了。"
        cleaned, report = run(text, strip_reason_words=False)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_reason_word_inside_body_is_preserved(self):
        text = "我觉得 thought 这个词挺好用"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)

    def test_idempotent(self):
        once, _ = run("🧠\n\nthought\n\n你来了。")
        twice, report = run(once)
        self.assertEqual(once, twice)
        self.assertFalse(report.changed)


class PlanPreambleTests(unittest.TestCase):
    """模型把英文思考与中文正文写在同一段时的切分。

    真实语料来自 gemini-4-argon 的 10 条泄漏回复，这里抽成脱敏样本。
    """

    def test_marker_then_plan_then_reply(self):
        cleaned, report = run(
            "thought Let's reply casually to 安. "
            '"小爪子都伸到屏幕跟前了，可惜隔着网线。"'
        )
        self.assertEqual(cleaned, "小爪子都伸到屏幕跟前了，可惜隔着网线。")
        self.assertEqual(report.reason_words_removed, 1)

    def test_plan_without_marker_word(self):
        cleaned, report = run(
            "Let's reply casually.\n"
            '"抢个毛毯卷还得从椅子上站起来拔刀。" -> keep it shorter: '
            "抢个毛毯卷还得站起来拔刀是吧。"
        )
        self.assertEqual(cleaned, "抢个毛毯卷还得站起来拔刀是吧。")
        self.assertEqual(report.reason_words_removed, 1)

    def test_last_revision_wins(self):
        cleaned, _ = run(
            "thought Let's reply naturally to -1587852571 (\"不是我的那不炸了\"). "
            "Wait: it means either way messed up. Let's make it playful. "
            "刚才还在塑料椅上摆好拔刀架势。"
        )
        self.assertEqual(cleaned, "刚才还在塑料椅上摆好拔刀架势。")

    def test_break_then_plan_then_reply(self):
        cleaned, _ = run(
            "thought\nThe user wants a short reply. Draft: \"刚开箱的宵暗妖怪。\" "
            "刚开箱的宵暗妖怪还被透明袋子封印着呢。"
        )
        self.assertEqual(cleaned, "刚开箱的宵暗妖怪还被透明袋子封印着呢。")

    def test_closing_quote_of_dropped_draft_is_removed(self):
        cleaned, _ = run(
            "thought Let's reply casually to 安. \"爪子伸到屏幕跟前了。\""
        )
        self.assertEqual(cleaned, "爪子伸到屏幕跟前了。")
        self.assertNotIn('"', cleaned)

    def test_normal_english_sentence_is_kept(self):
        text = "Thought you'd like this. 这是我上次说的图。"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertEqual(report.reason, "clean")

    def test_short_english_reply_is_kept(self):
        for text in ("Let's go. 我们出发吧。", "Let me think about it. 我再想想。"):
            with self.subTest(text=text):
                cleaned, _ = run(text)
                self.assertEqual(cleaned, text)

    def test_plain_chinese_reply_is_untouched(self):
        text = "正常中文回复，不带任何前缀。"
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertEqual(report.reason, "clean")

    def test_strip_reason_words_off_keeps_everything(self):
        text = "thought Let's reply casually to 安. \"爪子伸到屏幕跟前了。\""
        cleaned, report = run(text, strip_reason_words=False)
        self.assertEqual(cleaned, text)
        self.assertEqual(report.reason_words_removed, 0)


class LeadingSymbolPrefixTests(unittest.TestCase):
    """推理标签词前面带别的符号/emoji 时也要认出来（线上出现过 🫧thought）。"""

    def test_bubble_emoji_before_thought(self):
        cleaned, report = run("🫧thought\n桌面直接垒起一堵胶墙了啊。")
        self.assertEqual(cleaned, "桌面直接垒起一堵胶墙了啊。")
        self.assertEqual(report.reason_words_removed, 1)

    def test_bubble_emoji_blank_line_before_thought(self):
        cleaned, _ = run("🫧\n\nthought\n\n这次堆得更高了。")
        self.assertEqual(cleaned, "这次堆得更高了。")

    def test_dot_prefix_before_analysis(self):
        cleaned, _ = run("· analysis：这局打得不错")
        self.assertEqual(cleaned, "这局打得不错")

    def test_bubble_config_bare_decoration(self):
        cleaned, report = run("🫧 你好呀")
        self.assertEqual(cleaned, "你好呀")
        self.assertGreaterEqual(report.decor_chars_removed, 1)

    def test_quoted_thought_is_kept(self):
        text = "\"thought\" you'd like this."
        cleaned, report = run(text)
        self.assertEqual(cleaned, text)
        self.assertEqual(report.reason_words_removed, 0)

    def test_prefix_without_reply_body_is_kept(self):
        text = "（笑）thought"
        cleaned, _ = run(text)
        self.assertEqual(cleaned, text)

    def test_long_symbol_run_is_kept(self):
        text = "————————thought 你好"
        cleaned, _ = run(text)
        self.assertEqual(cleaned, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
