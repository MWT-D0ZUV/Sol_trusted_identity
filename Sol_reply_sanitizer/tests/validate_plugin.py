"""Sol_reply_sanitizer 装载前自检：SDK 导入、配置模型、默认配置一致性、钩子注册。

用法（在插件目录内）：
    python tests/validate_plugin.py
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
sys.path.insert(0, str(PLUGINS_ROOT))

FAILS: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILS.append(message)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[attr-defined]
        except Exception:
            pass

    module = importlib.import_module("Sol_reply_sanitizer.plugin")

    # ---- 配置模型默认值与 config.toml 保持一致
    config = module.Config()
    raw = tomllib.loads((PLUGIN_DIR / "config.toml").read_text(encoding="utf-8"))

    check(config.plugin.enabled is raw["plugin"]["enabled"], "plugin.enabled 与 config.toml 不一致")
    check(
        config.plugin.config_version == raw["plugin"]["config_version"],
        "plugin.config_version 与 config.toml 不一致",
    )
    for name in (
        "strip_tags",
        "strip_decorations",
        "decoration_chars",
        "leading_markers",
        "strip_reason_words",
        "strip_artifacts", "strip_chinese_analysis", "strip_emoji", "strip_private_use",
    ):
        check(
            getattr(config.strip, name) == raw["strip"][name],
            f"strip.{name} 与 config.toml 不一致",
        )
    for name in ("mode", "min_cjk_ratio", "max_cut_chars"):
        check(
            getattr(config.preamble, name) == raw["preamble"][name],
            f"preamble.{name} 与 config.toml 不一致",
        )
    check(config.log.enabled is raw["log"]["enabled"], "log.enabled 与 config.toml 不一致")

    # ---- 钩子与插件契约
    plugin = module.create_plugin()
    check(module.HOOK_BEFORE_POST_PROCESS == "maisaka.reply.before_post_process", "钩子名不符")
    check(getattr(plugin, "config_model", None) is module.Config, "config_model 未绑定")
    handler = getattr(plugin, "strip_thinking", None)
    check(handler is not None, "缺少 strip_thinking 钩子处理函数")
    hooks = {c["metadata"]["hook"] for c in plugin.get_components()}
    check(
        hooks == {
            "maisaka.replyer.after_response",
            "maisaka.reply.before_post_process",
            "maisaka.planner.before_request",
            "maisaka.replyer.before_model_request",
        },
        f"钩子集合不符：{sorted(hooks)}",
    )

    # ---- 钩子返回值契约
    import asyncio

    plugin.set_plugin_config(config.model_dump())

    result = asyncio.run(
        plugin.strip_thinking(
            response="<thought>推理</thought>你好呀",
            session_id="test",
            skip_post_process=False,
            enable_splitter=True,
            enable_chinese_typo=False,
        )
    )
    check(result.get("action") == "continue", "钩子 action 应为 continue")
    modified = result.get("modified_kwargs") or {}
    check(modified.get("response") == "你好呀", f"净化结果不符：{modified.get('response')!r}")
    check(modified.get("enable_splitter") is True, "enable_splitter 必须原样透传")
    check(modified.get("skip_post_process") is False, "skip_post_process 必须原样透传")
    check(modified.get("enable_chinese_typo") is False, "enable_chinese_typo 必须原样透传")

    # 干净文本不应产生 modified_kwargs
    clean = asyncio.run(plugin.strip_thinking(response="你好呀", skip_post_process=False))
    check(clean.get("action") == "continue", "干净文本 action 应为 continue")
    check("modified_kwargs" not in clean, "干净文本不应返回 modified_kwargs")

    # 开头单独成词的推理标签词
    bare = asyncio.run(plugin.strip_thinking(response="🧠\n\nthought\n\n你好呀", skip_post_process=False))
    bare_modified = bare.get("modified_kwargs") or {}
    check(bare_modified.get("response") == "你好呀", f"开头推理词未剥离：{bare_modified.get('response')!r}")

    if FAILS:
        print(f"FAILED {len(FAILS)} 项：")
        for item in FAILS:
            print(" -", item)
        return 1
    print("OK 全部自检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
