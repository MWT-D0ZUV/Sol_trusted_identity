"""真实 SDK 配置/钩子及已安装分段插件的缓存函数测试；不发消息、不调用 LLM。"""
from __future__ import annotations

import ast
import hashlib
import importlib
import re
import sys
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR.parent))
module = importlib.import_module('Sol_reply_sanitizer.plugin')


def load_installed_cache_functions():
    # 仅载入实际源码中的纯函数；导入整个兄弟插件会启动 Host 日志和配置。
    source = PLUGIN_DIR.parent / 'saberlights_smart-segmentation-plugin' / 'plugin.py'
    names = {
        '_strip_thinking_content', '_normalize_response_text_for_key', '_hash_normalized_text',
        '_prune_expired_prepared_segments', '_store_prepared_segments',
        '_pop_prepared_segments', '_has_prepared_segments',
    }
    tree = ast.parse(source.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise AssertionError('已安装智能分段缓存接口变更，需要重新核查兼容性')
    namespace = {
        're': re, 'hashlib': hashlib, 'time': time, '_prepared_segment_registry': {},
        '_PREPARED_SEGMENT_TTL_SECONDS': 60.0,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return SimpleNamespace(**namespace)


class PluginContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = module.create_plugin()
        self.plugin.set_plugin_config(module.Config().model_dump())
        self.extra = {
            'session_id': 'offline-test', 'skip_post_process': True,
            'enable_splitter': False, 'enable_chinese_typo': False,
            'reply_message_id': 'offline-only', 'reply_tool_args': {'reply_style': '正常回复'},
            'unknown_future_field': {'preserve': [1, 2, 3]},
        }

    async def test_preserves_every_hook_parameter(self):
        before = deepcopy(self.extra)
        result = await self.plugin.strip_thinking(response='<thought>内部</thought>嗯', **self.extra)
        self.assertEqual(result['modified_kwargs'], {**before, 'response': '嗯'})
        self.assertEqual(self.extra, before)

    async def test_only_thought_passes_empty_response(self):
        result = await self.plugin.strip_thinking(response='<thought>内部</thought>', **self.extra)
        self.assertEqual(result['modified_kwargs']['response'], '')
        self.assertIn('enable_splitter', result['modified_kwargs'])

    async def test_unclosed_thought_passes_empty_response(self):
        result = await self.plugin.strip_thinking(response='<thought>内部', **self.extra)
        self.assertEqual(result['modified_kwargs']['response'], '')

    async def test_clean_text_has_no_mutation(self):
        self.assertEqual(await self.plugin.strip_thinking(response='你好'), {'action': 'continue'})

    async def test_disabled_plugin_does_not_mutate(self):
        config = module.Config()
        config.plugin.enabled = False
        await self.plugin.on_config_update('self', config.model_dump(), 'offline')
        self.assertEqual(await self.plugin.strip_thinking(response='<think>保留</think>'), {'action': 'continue'})

    async def test_unload_disables_processing(self):
        await self.plugin.on_unload()
        self.assertEqual(await self.plugin.strip_thinking(response='<think>保留</think>'), {'action': 'continue'})

    async def test_empty_decoration_config_is_respected(self):
        config = module.Config()
        config.strip.decoration_chars = ''
        config.strip.strip_emoji = False
        await self.plugin.on_config_update('self', config.model_dump(), 'offline')
        self.assertEqual(await self.plugin.strip_thinking(response='💭你好'), {'action': 'continue'})

    async def test_invalid_mode_rejected_at_configuration_time(self):
        config = module.Config().model_dump()
        config['preamble']['mode'] = 'typo'
        with self.assertRaises(ValueError):
            self.plugin.set_plugin_config(config)

    async def test_model_hook_preserves_context_items_and_retry_fields(self):
        extra = {**self.extra, 'output_items': [{'kind': 'opaque-test-item'}], 'retry_count': 1, 'retry': False}
        result = await self.plugin.clean_model_response(response='<think>内部</think>好呀', **extra)
        self.assertEqual(result['modified_kwargs'], {**extra, 'response': '好呀'})
        second = await self.plugin.strip_thinking(**result['modified_kwargs'])
        self.assertEqual(second, {'action': 'continue'})

    async def test_hook_registration_order(self):
        components = self.plugin.get_components()
        self.assertEqual(len(components), 4)
        self.assertEqual({c['metadata']['hook'] for c in components}, {
            'maisaka.replyer.after_response', 'maisaka.reply.before_post_process',
            'maisaka.planner.before_request', 'maisaka.replyer.before_model_request',
        })
        by_hook = {c['metadata']['hook']: c['metadata'] for c in components}
        for hook, meta in by_hook.items():
            self.assertEqual(meta['mode'], 'blocking')
            history_hook = hook in {'maisaka.planner.before_request', 'maisaka.replyer.before_model_request'}
            self.assertEqual(meta['order'], 'late' if history_hook else 'early')

    async def test_exception_preserves_chat_availability(self):
        with patch.object(module, 'sanitize', side_effect=RuntimeError('offline injected failure')):
            self.assertEqual(await self.plugin.strip_thinking(response='你好'), {'action': 'continue'})

    @unittest.skipUnless((PLUGIN_DIR.parent / "saberlights_smart-segmentation-plugin" / "plugin.py").is_file(), "optional segmentation integration not installed")
    async def test_actual_installed_segmentation_cache(self):
        segmentation = load_installed_cache_functions()
        early = await self.plugin.clean_model_response(
            response='<think>内部</think>你好呀，今天辛苦了。先休息一下吧。', **self.extra,
        )
        cleaned = early['modified_kwargs']['response']
        segments = ['你好呀，今天辛苦了。', '先休息一下吧。']
        self.assertTrue(segmentation._store_prepared_segments('offline-test', cleaned, segments))
        late = await self.plugin.strip_thinking(response=cleaned, **self.extra)
        self.assertNotIn('modified_kwargs', late)
        self.assertTrue(segmentation._has_prepared_segments('offline-test', cleaned))
        self.assertEqual(segmentation._pop_prepared_segments('offline-test', cleaned), segments)


if __name__ == '__main__':
    unittest.main(verbosity=2)
