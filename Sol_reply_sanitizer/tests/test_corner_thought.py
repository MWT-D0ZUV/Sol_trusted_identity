"""角括号格式及历史污染的离线回归。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sanitizer import sanitize


class CornerThoughtTests(unittest.TestCase):
    def test_live_sample(self):
        body = '诶，你是把图忘在半路啦，还是看着上面那团白乎乎的猫猫看饿了，真当成刚出炉的面包准备咬一口呀？'
        plan = '德佬说“感觉这个面包有点像猫”，其实可能是在说上面云衣裳发的猫猫图。不过按俏皮自然的口吻调侃一句就好。注意不要直接输出思考过程在正文中！'
        for sep in ['\n', ' ', '']:
            with self.subTest(sep=sep):
                clean, report = sanitize('⌊思考过程⌉' + sep + plan + '⌈' + body)
                self.assertEqual(clean, body)
                self.assertTrue(report.changed)
                self.assertEqual(sanitize(clean)[0], clean)

    def test_unclosed_or_empty_body(self):
        for text in ['⌊思考过程⌉内部', '⌊思考过程⌉内部⌈', '⌊思考过程⌉' + '长' * 3000]:
            with self.subTest(length=len(text)):
                self.assertEqual(sanitize(text)[0], '')

    def test_prefix_and_nested_blocks(self):
        for text in ['\n ⌊思考过程⌉内部⌈好呀', '🧠[::]⌊思考过程⌉内部⌈好呀',
                     '⌊思考过程⌉一⌈⌊思考过程⌉二⌈好呀',
                     '⌊思考过程⌉一⌊思考过程⌉二⌈三⌈好呀',
                     '<think>旧格式</think>⌊思考过程⌉内部⌈好呀']:
            with self.subTest(text=text):
                self.assertEqual(sanitize(text)[0], '好呀')

    def test_examples_and_ordinary_text_preserved(self):
        for text in ['`⌊思考过程⌉内部⌈正文`', '```text\n⌊思考过程⌉内部⌈正文\n```',
                     '这个标记是⌊思考过程⌉，后面还有⌈。', '⌈x⌉表示上取整。',
                     '思考过程很重要。', '  普通正文\n']:
            with self.subTest(text=text):
                self.assertEqual(sanitize(text)[0], text)

    def test_disabled_tags_preserve_corner_format(self):
        text = '⌊思考过程⌉内部⌈好呀'
        self.assertEqual(sanitize(text, strip_tags=False)[0], text)


if __name__ == '__main__':
    unittest.main()
