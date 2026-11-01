"""1.5.3 synthetic regressions; no logs, network or real chat content."""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Sol_reply_sanitizer.sanitizer import TAG_ALIASES, sanitize


def clean(text, **options):
    return sanitize(text, preamble_mode="off", **options)[0]


class EmptyMarkerTests(unittest.TestCase):
    def test_observed_prefix(self):
        for marker in ("[_thought _]", "[_thought\n_]", "[_THOUGHT\t_]"):
            with self.subTest(marker=marker):
                output, report = sanitize(marker + "正文保留。", preamble_mode="off")
                self.assertEqual(output, "正文保留。")
                self.assertEqual(report.reason, "marker_removed")
                self.assertEqual(report.marker_chars_removed, len(marker))

    def test_only_marker(self):
        self.assertEqual(clean("[_thought _]"), "")

    def test_multiple_prefixes(self):
        self.assertEqual(clean(" [_thought _]\n[_thought\n_]正文"), "正文")

    def test_artifact_switch(self):
        text = "[_thought _]正文"
        self.assertEqual(clean(text, strip_artifacts=False), text)

    def test_code_is_preserved(self):
        for text in ("`[_thought _]`", "```text\n[_thought _]正文\n```", "~~~text\n[_thought _]\n~~~"):
            self.assertEqual(clean(text), text)

    def test_quotes_and_body_are_preserved(self):
        for text in ("> [_thought _]", "他说[_thought _]是标记。", '"[_thought _]"是格式。', "'[_thought _]'是格式。", "正文\n[_thought _]"):
            self.assertEqual(clean(text), text)

    def test_nonempty_and_similar_are_preserved(self):
        for text in ("[_thought 内容_]正文", "[_thoughts _]正文", "[_ thought _]正文", "[_thought- _]正文", "[thought]正文", "正常thought用词", "  普通正文  "):
            output, report = sanitize(text, preamble_mode="off")
            self.assertEqual(output, text)
            self.assertFalse(report.changed)

    def test_idempotent(self):
        text = "[_thought\n_]<thought </thought>正文"
        once = clean(text)
        self.assertEqual(once, "正文")
        self.assertEqual(clean(once), once)


class MalformedEmptyTagTests(unittest.TestCase):
    def test_empty_same_name_all_existing_aliases(self):
        for name in TAG_ALIASES:
            for whitespace in (" ", "\n", "\t"):
                with self.subTest(name=name, whitespace=whitespace):
                    output, report = sanitize(f"<{name}{whitespace}</{name}>正文", preamble_mode="off")
                    self.assertEqual(output, "正文")
                    self.assertEqual(report.tags_removed, 1)
                    self.assertEqual(report.incomplete_blocks, 0)

    def test_case_and_spacing(self):
        self.assertEqual(clean("< THOUGHT \n</ thought >正文"), "正文")

    def test_middle_empty_marker(self):
        self.assertEqual(clean("前文<thought </thought>后文"), "前文后文")

    def test_tags_switch(self):
        text = "<thought </thought>正文"
        self.assertEqual(clean(text, strip_tags=False), text)

    def test_code_and_quotes_attribute_preserved(self):
        for text in ("`<thought </thought>`", "```xml\n<thought </thought>\n```", "~~~xml\n<thought </thought>\n~~~"):
            self.assertEqual(clean(text), text)
        self.assertEqual(clean('<thought data=">">内容</thought>正文'), "正文")

    def test_true_open_block_is_still_hidden(self):
        for text in ("<thought>内部分析", "前文<thought>内部分析", "<thought 内部分析</thought>后文", "<thought </analysis>后文"):
            expected = "前文" if text.startswith("前文") else ""
            self.assertEqual(clean(text), expected)

    def test_nested_empty_does_not_close_outer_block(self):
        self.assertEqual(clean("<think>内部<thought </thought>仍是内部</think>正文"), "正文")
        self.assertEqual(clean("<think>内部<thought </thought>仍是内部"), "")
        self.assertEqual(clean("<think>内部<analysis </analysis></think>正文"), "正文")

    def test_existing_well_formed_empty(self):
        self.assertEqual(clean("<thought> </thought>正文"), "正文")
        self.assertEqual(clean("<thought/>正文"), "正文")

    def test_empty_only(self):
        self.assertEqual(clean("<thought </thought>"), "")

    def test_false_prefix_names(self):
        for text in ("<thoughtful </thoughtful>正文", "<analysis-result </analysis-result>正文"):
            self.assertEqual(clean(text), text)


if __name__ == "__main__":
    unittest.main()
