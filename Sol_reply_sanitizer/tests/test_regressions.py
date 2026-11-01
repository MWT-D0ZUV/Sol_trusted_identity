"""初版遗漏的泄漏、误删和 Markdown 边界回归；不调用模型、不发消息。"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sanitizer import TAG_ALIASES, sanitize

class LeakageRegressionTests(unittest.TestCase):
    def test_unclosed_reasoning_is_not_visible(self):
        self.assertEqual(sanitize('<reasoning>用户问候，我需要先组织回复。')[0], '')
    def test_only_reasoning_does_not_fall_back(self):
        self.assertEqual(sanitize('<thought>内部推理</thought>')[0], '')
    def test_one_character_answer_is_kept(self):
        self.assertEqual(sanitize('<think>分析</think>嗯')[0], '嗯')
    def test_visible_prefix_before_unclosed_tag(self):
        self.assertEqual(sanitize('收到。<analysis>内部推理')[0], '收到。')
    def test_nested_same_name_does_not_leak_tail(self):
        self.assertEqual(sanitize('<think>外层<think>内层</think>后半段</think>你好')[0], '你好')
    def test_nested_mixed_name_does_not_leak_tail(self):
        self.assertEqual(sanitize('<think>外层<analysis>内层</analysis>后半段</think>你好')[0], '你好')
    def test_attributes_and_case(self):
        self.assertEqual(sanitize('<THOUGHT class="x" note=\'a>b\'>推理</THOUGHT>好')[0], '好')
    def test_self_closing_tag_does_not_hide_answer(self):
        self.assertEqual(sanitize('<think/>好呀')[0], '好呀')
    def test_fenced_sample_after_prose(self):
        text = '示例：\n```xml\n<thought>这是一段示例</thought>\n```\n结束。'
        self.assertEqual(sanitize(text)[0], text)
    def test_inline_code_sample(self):
        text = '用 `<thought>示例</thought>` 包住它。'
        self.assertEqual(sanitize(text)[0], text)
    def test_code_start_does_not_disable_filter_after_code(self):
        self.assertEqual(sanitize('```python\nprint("hi")\n```\n<thought>内部推理</thought>你好')[0], '```python\nprint("hi")\n```\n你好')
    def test_reasoning_containing_code_stays_hidden(self):
        self.assertEqual(sanitize('<think>内部\n```text\n计划\n```\n继续推理</think>你好')[0], '你好')
    def test_tilde_fence(self):
        text = '示例\n~~~xml\n<thought>示例</thought>\n~~~\n结束'
        self.assertEqual(sanitize(text)[0], text)
    def test_long_fence_with_short_fence_inside(self):
        self.assertEqual(sanitize('````xml\n```\n<think>示例</think>\n````\n<think>秘密</think>好')[0], '````xml\n```\n<think>示例</think>\n````\n好')
    def test_multi_backtick_inline(self):
        text = '示例 ``a`<thought>示例</thought>``。'
        self.assertEqual(sanitize(text)[0], text)
    def test_unclosed_fence_is_preserved(self):
        text = '示例\n```xml\n<thought>示例</thought>'
        self.assertEqual(sanitize(text)[0], text)
    def test_normal_chat_with_common_meta_words(self):
        for word in ('用户', '分析', '语气', '让我', '角色', '对方'):
            with self.subTest(word=word):
                text = f'{word}这个词我记住了。\n\n明天再聊。'
                self.assertEqual(sanitize('🧠💭' + text)[0], text)
    def test_english_greeting_with_emoji(self):
        self.assertEqual(sanitize('💭 Good morning!\n\n早上好呀')[0], 'Good morning!\n\n早上好呀')
    def test_complete_block_does_not_remove_greeting(self):
        self.assertEqual(sanitize('<think>内部</think>Good morning!\n\n早上好呀')[0], 'Good morning!\n\n早上好呀')
    def test_multiple_chinese_reasoning_paragraphs(self):
        self.assertEqual(sanitize('🧠💭用户说很累，应该安慰一下。\n\n我需要先思考如何回复。\n\n辛苦啦，先歇会儿吧。')[0], '辛苦啦，先歇会儿吧。')
    def test_single_reasoning_paragraph_with_marker(self):
        self.assertEqual(sanitize('🧠💭 I should respond warmly to the user.')[0], '')
    def test_decor_only(self):
        self.assertEqual(sanitize('🧠💭：')[0], '')
    def test_normal_whitespace_is_preserved(self):
        text = '  好呀\n\n'
        cleaned, report = sanitize(text)
        self.assertEqual(cleaned, text)
        self.assertFalse(report.changed)
    def test_all_controls_off_preserves_bytes(self):
        text = '  <thought>示例</thought>\n💭 hi\n\n你好  '
        self.assertEqual(sanitize(text, strip_tags=False, strip_decorations=False, preamble_mode='off')[0], text)
    def test_disabling_tags_keeps_unclosed_tag(self):
        self.assertEqual(sanitize('<think>保留', strip_tags=False)[0], '<think>保留')
    def test_empty_decoration_setting_is_respected(self):
        text = '🧠💭你好'
        self.assertEqual(sanitize(text, decoration_chars='')[0], text)
    def test_always_mode_requires_reasoning_evidence(self):
        text = 'Good morning!\n\n早上好呀'
        self.assertEqual(sanitize(text, preamble_mode='always')[0], text)
    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            sanitize('你好', preamble_mode='alwyas')
    def test_empty_report_does_not_claim_clean(self):
        _, report = sanitize('<think>内部</think>')
        self.assertTrue(report.changed)
        self.assertEqual(report.reason, 'no_visible_body')
    def test_sibling_tags_are_removed(self):
        self.assertEqual(sanitize('<think>a</think>好<analysis>b</analysis>呀')[0], '好呀')
    def test_not_a_reasoning_tag(self):
        for text in ('<thinker>普通 XML</thinker>', '<analysis-result>普通 XML</analysis-result>', '&lt;think&gt;示例&lt;/think&gt;'):
            with self.subTest(text=text):
                self.assertEqual(sanitize(text)[0], text)
    def test_every_alias_unclosed_and_closed(self):
        for name in TAG_ALIASES:
            with self.subTest(name=name):
                self.assertEqual(sanitize(f'<{name}>内部</{name}>好')[0], '好')
                self.assertEqual(sanitize(f'<{name}>内部')[0], '')
    def test_idempotence(self):
        for text in ('<think>秘密</think>好', '<think>未完', '💭Let me think about a reply.\n\n你好', '示例：`<think>示例</think>`'):
            with self.subTest(text=text):
                first = sanitize(text)[0]
                self.assertEqual(sanitize(first)[0], first)

if __name__ == '__main__':
    unittest.main(verbosity=2)
