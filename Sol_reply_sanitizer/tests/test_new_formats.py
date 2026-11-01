"""2026-10-28 现场格式回归；不访问网络或发送消息。"""
import importlib
import sys
import unittest
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
module = importlib.import_module('Sol_reply_sanitizer.plugin')
from Sol_reply_sanitizer.sanitizer import sanitize


def clean(text, **options):
    return sanitize(text, strip_emoji=True, strip_private_use=True, **options)[0]


class NewFormatsTests(unittest.TestCase):
    def test_observed_edges(self):
        for text in ('[::ethoughts ::]你好', '[[::]你好', '[[[[]]你好',
                     '你好[::-]', '[::ethoughts ::]你好[::-]', '⌊⌊你好⌉⌉',
                     '🫖⌊⌊你好⌉⌉', '[::ethoughts ::]⌊⌊你好⌉⌉[::-]'):
            with self.subTest(text=text):
                self.assertEqual(clean(text), '你好')

    def test_normal_text_and_code(self):
        for text in ('  今天正常聊天。  ', '他说[::ethoughts ::]是个标记。',
                     '请用[[链接]]和[标题](https://example.com)格式。',
                     '⌊正文⌉；⌊⌊中间⌉⌉还有后文', 'a → b <= c，(｡･ω･｡)ﾉ', '从 A 🡆 B 🡢 C',
                     '分析过程：先将两边同除以 2，可得 x=3。',
                     '`🫖 [::ethoughts ::]`', '例子：`⌊⌊正文⌉⌉`',
                     '```text\n🫖\n思考过程：这是代码\n最终回复：例子\n[::-]\n```',
                     '```text\n示例未闭合\n[::-]'):
            with self.subTest(text=text):
                output, report = sanitize(text, strip_emoji=True, strip_private_use=True)
                self.assertEqual(output, text)
                self.assertFalse(report.changed)

    def test_chinese_analysis_no_guessing(self):
        for heading in ('思考过程', '思想过程', '思维链'):
            for text in (f'{heading}：分析内容。\n构思：给出一句话。',
                         f'**{heading}：**分析内容', f'### {heading}: 分析内容'):
                with self.subTest(text=text):
                    self.assertEqual(clean(text, preamble_mode='off'), '')
        self.assertEqual(clean('🫧思考过程：分析\n构思：看起来像正文'), '')
        self.assertEqual(clean('思想过程：' + '很长的分析' * 1000), '')

    def test_explicit_final_boundary(self):
        self.assertEqual(clean('思考过程：秘密。最终回复：你好'), '你好')
        self.assertEqual(clean('你好❤☺☀✌'), '你好')
        self.assertEqual(clean('思考过程：分析\n最终回复：你好'), '你好')
        self.assertEqual(clean('思想过程：分析\n**正式回复：**你好🫖'), '你好')
        self.assertEqual(clean('思考过程：分析\n```\n最终回复：仍在分析里的代码\n```'), '')
        self.assertEqual(clean('思考过程：分析\n```\n最终回复：代码\n```\n最终回答：你好'), '你好')
        self.assertEqual(clean('思考过程：分析\n最终回复：思考过程：还是分析'), '')

    def test_symbols_and_sequences(self):
        for emoji in ('🫖', '😄', '👩🏽\u200d💻', '👨\u200d👩\u200d👧\u200d👦',
                      '🏳️\u200d🌈', '🇨🇳', '1️⃣', '#️⃣', '❤️', '👍🏿',
                      '🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f'):
            with self.subTest(emoji=emoji):
                self.assertEqual(clean('你好' + emoji + '呀'), '你好呀')
        self.assertEqual(clean('你\uf604好\U000f1234呀\U00101234'), '你好呀')
        self.assertEqual(clean('🫖'), '')
        self.assertEqual(clean('→ © 1 # * 中文'), '→ © 1 # * 中文')
        self.assertEqual(clean('🫖`🫖`'), '`🫖`')

    def test_new_switches_independent(self):
        text = '[::ethoughts ::]你好[::-]'
        self.assertEqual(sanitize(text, strip_artifacts=False)[0], text)
        text = '思考过程：分析\n构思：草稿'
        self.assertEqual(sanitize(text, strip_chinese_analysis=False)[0], text)
        self.assertEqual(sanitize('你好🫖', strip_emoji=False, strip_private_use=False)[0], '你好🫖')
        self.assertEqual(sanitize('你好🫖', strip_emoji=True, strip_private_use=False)[0], '你好')
        self.assertEqual(sanitize('你好🫖', strip_emoji=False, strip_private_use=True)[0], '你好🫖')

    def test_idempotent(self):
        for text in ('[::ethoughts ::]⌊⌊你好⌉⌉[::-]', '🫖⌊思考过程⌉分析⌈你好',
                     '思考过程：分析\n最终回复：你好🫖', '思考过程：分析\n构思：草稿'):
            with self.subTest(text=text):
                self.assertEqual(clean(clean(text)), clean(text))


class NewHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = module.create_plugin()
        self.plugin.set_plugin_config(module.Config().model_dump())

    async def test_real_defaults_and_empty_suppression_contract(self):
        extra = {'output_items': [{'opaque': 'preserve'}], 'enable_splitter': False,
                 'skip_post_process': True, 'future_field': [1, 2]}
        original = deepcopy(extra)
        for hook in (self.plugin.clean_model_response, self.plugin.strip_thinking):
            result = await hook(response='🫧思考过程：分析\n构思：草稿', **extra)
            self.assertEqual(result['modified_kwargs'], {**original, 'response': ''})
        self.assertEqual(extra, original)

    async def test_new_history_rules_not_applied(self):
        data = {'item_schema_version': 1, 'items': [
            {'item_type': 'AssistantMessageItem', 'parts': [{'type': 'text', 'text':
             '[::ethoughts ::]思考过程：历史🫖'}]}]}
        self.assertEqual(await self.plugin.clean_replyer_history(**data), {'action': 'continue'})

    async def test_old_config_uses_new_defaults_and_live_toggle(self):
        old = module.Config().model_dump()
        for name in ('strip_artifacts', 'strip_chinese_analysis', 'strip_emoji', 'strip_private_use'):
            old['strip'].pop(name)
        self.plugin.set_plugin_config(old)
        result = await self.plugin.strip_thinking(response='你好🫖')
        self.assertEqual(result['modified_kwargs']['response'], '你好')
        old['strip'].update(strip_emoji=False, strip_private_use=False)
        await self.plugin.on_config_update('self', old, 'offline')
        self.assertEqual(await self.plugin.strip_thinking(response='你好🫖'), {'action': 'continue'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
