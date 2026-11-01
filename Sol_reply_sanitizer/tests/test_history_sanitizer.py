import copy
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
module = importlib.import_module('Sol_reply_sanitizer.plugin')


class HistorySanitizerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = module.create_plugin()
        self.plugin.set_plugin_config(module.Config().model_dump())
        self.leak = '⌊思考过程⌉内部分析⌈正式回复'
        self.assistant = {'item_type': 'AssistantMessageItem', 'meta': {'item_id': 'a', 'logical_turn_id': 'turn'},
                          'phase': 'final_answer', 'parts': [{'type': 'text', 'text': self.leak}, {'type': 'image', 'image': 'opaque'}]}
        self.kwargs = {'items': [self.assistant], 'item_schema_version': 1, 'session_id': 'offline',
                       'unknown_field': {'keep': [1]}, 'reply_tool_args': {'keep': True}}

    async def test_both_hooks_copy_only_assistant_text(self):
        for role in ['UserMessageItem', 'SystemMessageItem', 'ToolResultItem', 'ReasoningItem']:
            self.kwargs['items'].append({'item_type': role, 'parts': [{'type': 'text', 'text': self.leak}]})
        original = copy.deepcopy(self.kwargs)
        for hook in [self.plugin.clean_planner_history, self.plugin.clean_replyer_history]:
            result = await hook(**self.kwargs)
            modified = result['modified_kwargs']
            expected = copy.deepcopy(original)
            expected['items'][0]['parts'][0]['text'] = '正式回复'
            self.assertEqual(modified, expected)
            self.assertEqual(self.kwargs, original)
            self.assertEqual(await hook(**modified), {'action': 'continue'})

    async def test_unclosed_history_keeps_empty_item_and_metadata(self):
        self.kwargs['items'][0]['parts'] = [{'type': 'text', 'text': '⌊思考过程⌉无正文'}]
        result = await self.plugin.clean_replyer_history(**self.kwargs)
        item = result['modified_kwargs']['items'][0]
        self.assertEqual(item['parts'], [])
        self.assertEqual(item['meta'], self.assistant['meta'])

    async def test_history_does_not_apply_heuristic_or_decoration_rules(self):
        for text in ['💭普通发言', '[::]正常内容', 'thought\n普通英文', '`⌊思考过程⌉内部⌈正文`']:
            self.kwargs['items'][0]['parts'] = [{'type': 'text', 'text': text}]
            self.assertEqual(await self.plugin.clean_replyer_history(**self.kwargs), {'action': 'continue'})

    async def test_disabled_and_unknown_schema(self):
        for version in [None, 0, 2, True, '1']:
            self.assertEqual(await self.plugin.clean_replyer_history(**{**self.kwargs, 'item_schema_version': version}), {'action': 'continue'})
        config = module.Config()
        config.plugin.enabled = False
        self.plugin.set_plugin_config(config.model_dump())
        self.assertEqual(await self.plugin.clean_replyer_history(**self.kwargs), {'action': 'continue'})
        config.plugin.enabled = True
        config.strip.strip_tags = False
        self.plugin.set_plugin_config(config.model_dump())
        self.assertEqual(await self.plugin.clean_replyer_history(**self.kwargs), {'action': 'continue'})

    async def test_no_splitter_send_path(self):
        extra = {'enable_splitter': False, 'skip_post_process': True, 'enable_chinese_typo': False}
        result = await self.plugin.clean_model_response(response=self.leak, **extra)
        self.assertEqual(result['modified_kwargs'], {**extra, 'response': '正式回复'})
        self.assertEqual(await self.plugin.strip_thinking(**result['modified_kwargs']), {'action': 'continue'})
        fallback = await self.plugin.strip_thinking(response=self.leak, **extra)
        self.assertEqual(fallback['modified_kwargs']['response'], '正式回复')


if __name__ == '__main__':
    unittest.main()
