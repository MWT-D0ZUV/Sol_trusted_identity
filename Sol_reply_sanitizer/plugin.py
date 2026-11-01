"""Sol.reply_sanitizer —— 剥离模型漏进回复正文的思考过程。

挂载点：
``maisaka.planner.before_request`` / ``maisaka.replyer.before_model_request``
仅在请求副本中清洗 assistant 历史的明确思考块，不改持久记录或其他角色；
``maisaka.replyer.after_response`` 提前净化以兼容智能分段缓存；
``maisaka.reply.before_post_process`` 在发送前再次检查。
净化只改写 ``response`` 这一个字段，其余 hook 参数（skip_post_process / enable_splitter /
enable_chinese_typo）原样透传，因此不会改变分段与错字策略。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder

from .sanitizer import sanitize

LOG = logging.getLogger("Sol.reply_sanitizer")

HOOK_BEFORE_POST_PROCESS = "maisaka.reply.before_post_process"


def ui(label: str, **extra: Any) -> dict[str, Any]:
    """构造字段的 UI 元信息。"""

    return {"label": label, **extra}


class PluginSection(PluginConfigBase):
    """宿主要求的 [plugin] 保留节。"""

    __ui_label__ = "启用设置"
    __ui_icon__ = "power"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="关闭后插件不再改动任何回复内容。",
        json_schema_extra=ui("启用回复净化"),
    )
    config_version: str = Field(
        default="1.0.0",
        description="内部配置版本，由宿主维护，请勿手动改写。",
        json_schema_extra=ui("内部配置版本", hidden=True),
    )


class StripSection(PluginConfigBase):
    """标签与装饰前缀。"""

    __ui_label__ = "标签与装饰"
    __ui_icon__ = "eraser"
    __ui_order__ = 1

    strip_tags: bool = Field(
        default=True,
        description="移除 <think>/<thinking>/<thought>/<reasoning> 等标签块，连同其中的推理文字。",
        json_schema_extra=ui("剥离思考标签块"),
    )
    strip_decorations: bool = Field(
        default=True,
        description="移除回复开头作为思考标记的 emoji（默认 🧠💭🫧）及其后的冒号、短横等分隔符。",
        json_schema_extra=ui("剥离开头思考标记"),
    )
    decoration_chars: str = Field(
        default="🧠💭🫧",
        description="要移除的装饰字符集合，可自行增删；仅处理句首，正文中间的同字符不受影响。",
        json_schema_extra=ui("装饰字符集合"),
    )
    leading_markers: str = Field(
        default="[::]",
        description="正文开头需要删除的方括号占位标记，多个用英文逗号分隔；留空则关闭。只在句首生效。",
        json_schema_extra=ui("开头占位标记"),
    )
    strip_reason_words: bool = Field(
        default=True,
        description=(
            "删除正文开头单独成词的推理标签词（thought、thinking、analysis 等）。"
            "后接换行，或同一行紧跟中文正文时才删除；正常英文句子保留。"
        ),
        json_schema_extra=ui("剥离开头推理词"),
    )
    strip_artifacts: bool = Field(
        default=True, description="移除回复边缘的已知伪标记及整条双角括号包装，保留正文与代码引用。",
        json_schema_extra=ui("清理异常符号标记"),
    )
    strip_chinese_analysis: bool = Field(
        default=True, description="句首思考过程/思想过程等明确标题只保留显式最终回复；没有分界则阻止整条发送。独立于前言模式。",
        json_schema_extra=ui("拦截中文分析标题"),
    )
    strip_emoji: bool = Field(
        default=True, description="移除新回复正文代码之外的常见 Unicode emoji 序列；保留颜文字、普通箭头及独立表情包图片。",
        json_schema_extra=ui("过滤文本 emoji"),
    )
    strip_private_use: bool = Field(
        default=True, description="移除代码之外的 Unicode 私用区字符，可能同时去掉自定义字体图标；可单独关闭。",
        json_schema_extra=ui("过滤私用区字符"),
    )


class PreambleSection(PluginConfigBase):
    """中文正文之前的推理前言。"""

    __ui_label__ = "思考前言"
    __ui_icon__ = "scissors"
    __ui_order__ = 2

    mode: Literal["off", "heuristic", "always"] = Field(
        default="heuristic",
        description=(
            "off=不切前言；heuristic=有标签或装饰证据时，仅切明确的推理句式（推荐）；"
            "always=没有标记也尝试识别明确推理，仍保留普通中英文段落。"
        ),
        json_schema_extra=ui("前言切除模式", options=["off", "heuristic", "always"]),
    )
    min_cjk_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="判定某一段为「中文正文」所需的中文字符占比。",
        json_schema_extra=ui("中文判定阈值"),
    )
    max_cut_chars: int = Field(
        default=1500,
        ge=0,
        description="允许切掉的前言最大字数；超过则视为正常长回复而放行，防止误伤。",
        json_schema_extra=ui("前言最大长度"),
    )


class LogSection(PluginConfigBase):
    """日志。"""

    __ui_label__ = "日志"
    __ui_icon__ = "file-text"
    __ui_order__ = 3

    enabled: bool = Field(
        default=True,
        description="净化生效时输出一条 INFO 日志，包含剥离类型与字符数，便于核对。",
        json_schema_extra=ui("启用净化日志"),
    )


class Config(PluginConfigBase):
    """插件配置。"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    strip: StripSection = Field(default_factory=StripSection)
    preamble: PreambleSection = Field(default_factory=PreambleSection)
    log: LogSection = Field(default_factory=LogSection)


class ReplySanitizerPlugin(MaiBotPlugin):
    """在回复发送前净化正文。"""

    config_model = Config

    def __init__(self) -> None:
        super().__init__()
        self._enabled = False
        self._strip_tags = True
        self._strip_decorations = True
        self._decoration_chars = "🧠💭🫧"
        self._leading_markers = "[::]"
        self._strip_reason_words = True
        self._strip_artifacts = True
        self._strip_chinese_analysis = True
        self._strip_emoji = True
        self._strip_private_use = True
        self._preamble_mode = "heuristic"
        self._min_cjk_ratio = 0.5
        self._max_cut_chars = 1500
        self._log_enabled = True

    # ------------------------------------------------------------------ 配置

    def set_plugin_config(self, config_data: Any) -> None:
        """宿主注入配置（含运行中更新）。"""

        super().set_plugin_config(config_data)
        self._read_config()

    def _read_config(self) -> None:
        """把配置快照到实例字段，热更新时无锁读取。"""

        try:
            cfg = self.config
        except Exception:  # pragma: no cover - 极端情况下配置未就绪
            LOG.warning("Sol.reply_sanitizer 配置尚未就绪，本次按禁用处理")
            self._enabled = False
            return

        try:
            self._enabled = bool(cfg.plugin.enabled)
            self._strip_tags = bool(cfg.strip.strip_tags)
            self._strip_decorations = bool(cfg.strip.strip_decorations)
            self._decoration_chars = str(cfg.strip.decoration_chars)
            self._leading_markers = str(cfg.strip.leading_markers or "")
            self._strip_reason_words = bool(cfg.strip.strip_reason_words)
            self._strip_artifacts = bool(cfg.strip.strip_artifacts)
            self._strip_chinese_analysis = bool(cfg.strip.strip_chinese_analysis)
            self._strip_emoji = bool(cfg.strip.strip_emoji)
            self._strip_private_use = bool(cfg.strip.strip_private_use)
            self._preamble_mode = str(cfg.preamble.mode or "heuristic")
            self._min_cjk_ratio = float(cfg.preamble.min_cjk_ratio)
            self._max_cut_chars = int(cfg.preamble.max_cut_chars)
            self._log_enabled = bool(cfg.log.enabled)
        except Exception as exc:  # pragma: no cover - 配置结构异常时保守禁用
            LOG.warning("Sol.reply_sanitizer 配置解析失败，暂不生效: %s", exc)
            self._enabled = False

    async def on_load(self) -> None:
        self._read_config()
        LOG.info(
            "Sol.reply_sanitizer v1.5.3 已加载：enabled=%s preamble_mode=%s artifacts=%s chinese_analysis=%s emoji=%s private_use=%s",
            self._enabled,
            self._preamble_mode,
            self._strip_artifacts,
            self._strip_chinese_analysis,
            self._strip_emoji,
            self._strip_private_use,
        )

    async def on_unload(self) -> None:
        self._enabled = False
        LOG.info("Sol.reply_sanitizer 已卸载")

    async def on_config_update(self, scope: str, config_data: Any, version: str) -> None:
        if scope == "self":
            self.set_plugin_config(config_data)
        else:
            self._read_config()
        LOG.info(
            "Sol.reply_sanitizer 配置更新：scope=%s version=%s enabled=%s",
            scope,
            version,
            self._enabled,
        )

    # -------------------------------------------------------------------- 钩子

    def _clean_history(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """只清洗请求副本中的 assistant 历史，不改持久记录或其他角色。"""
        items = kwargs.get("items")
        if (not self._enabled or not self._strip_tags
                or type(kwargs.get("item_schema_version")) is not int
                or kwargs["item_schema_version"] != 1 or not isinstance(items, list)):
            return {"action": "continue"}
        changed_items = []
        changed_parts = 0
        for item in items:
            if not isinstance(item, dict) or item.get("item_type") != "AssistantMessageItem":
                changed_items.append(item)
                continue
            parts = item.get("parts")
            if not isinstance(parts, list):
                changed_items.append(item)
                continue
            new_parts = []
            item_changed = False
            for part in parts:
                if not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str):
                    new_parts.append(part)
                    continue
                cleaned, report = sanitize(
                    part["text"], strip_tags=True, strip_decorations=False,
                    leading_markers="", strip_reason_words=False, preamble_mode="off",
                    strip_artifacts=False, strip_chinese_analysis=False,
                    strip_emoji=False, strip_private_use=False,
                )
                if report.changed:
                    if cleaned:
                        new_parts.append({**part, "text": cleaned})
                    changed_parts += 1
                    item_changed = True
                else:
                    new_parts.append(part)
            changed_items.append({**item, "parts": new_parts} if item_changed else item)
        if not changed_parts:
            return {"action": "continue"}
        if self._log_enabled:
            LOG.info("Sol.reply_sanitizer 已净化请求历史：text_parts=%d", changed_parts)
        return {"action": "continue", "modified_kwargs": {**kwargs, "items": changed_items}}

    @HookHandler(
        "maisaka.planner.before_request", name="reply_sanitizer_planner_history",
        description="隔离规划请求中历史机器人发言的明确思考块",
        mode=HookMode.BLOCKING, order=HookOrder.LATE, error_policy=ErrorPolicy.SKIP,
    )
    async def clean_planner_history(self, **kwargs: Any) -> dict[str, Any]:
        return self._clean_history(kwargs)

    @HookHandler(
        "maisaka.replyer.before_model_request", name="reply_sanitizer_replyer_history",
        description="隔离回复请求中历史机器人发言的明确思考块",
        mode=HookMode.BLOCKING, order=HookOrder.LATE, error_policy=ErrorPolicy.SKIP,
    )
    async def clean_replyer_history(self, **kwargs: Any) -> dict[str, Any]:
        return self._clean_history(kwargs)

    @HookHandler(
        "maisaka.replyer.after_response",
        name="reply_sanitizer_before_segmentation",
        description="模型返回后先净化正文，再交给智能分段预处理",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def clean_model_response(self, response: str = "", **kwargs: Any) -> dict[str, Any]:
        # 透传 output_items 等所有参数；Host 支持仅替换 response 正文投影。
        return await self.strip_thinking(response=response, **kwargs)

    @HookHandler(
        HOOK_BEFORE_POST_PROCESS,
        name="reply_sanitizer_strip_thinking",
        description="剥离回复正文中的思考标签块、开头思考标记与前置推理段落",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def strip_thinking(self, response: str = "", **kwargs: Any) -> dict[str, Any]:
        """在回复进入后处理前净化正文。"""

        if not self._enabled:
            return {"action": "continue"}

        original = str(response or "")
        if not original.strip():
            return {"action": "continue"}

        try:
            cleaned, report = sanitize(
                original,
                strip_tags=self._strip_tags,
                strip_decorations=self._strip_decorations,
                decoration_chars=self._decoration_chars,
                leading_markers=self._leading_markers,
                strip_reason_words=self._strip_reason_words,
                preamble_mode=self._preamble_mode,
                min_cjk_ratio=self._min_cjk_ratio,
                max_cut_chars=self._max_cut_chars,
                strip_artifacts=self._strip_artifacts,
                strip_chinese_analysis=self._strip_chinese_analysis,
                strip_emoji=self._strip_emoji,
                strip_private_use=self._strip_private_use,
            )
        except Exception as exc:
            # 净化失败绝不能吞掉回复，交给宿主原始文本
            LOG.warning("Sol.reply_sanitizer 净化异常，放行原文: %s", exc)
            return {"action": "continue"}

        if not report.changed:
            return {"action": "continue"}

        if self._log_enabled:
            LOG.info(
                "Sol.reply_sanitizer 已净化回复：reason=%s tags=%d decor=%d reason_words=%d "
                "preamble=%d markers=%d chinese_analysis=%d emoji=%d private_use=%d 长度 %d→%d",
                report.reason,
                report.tags_removed,
                report.decor_chars_removed,
                report.reason_words_removed,
                report.preamble_cut_chars,
                report.marker_chars_removed,
                report.analysis_cut_chars,
                report.emoji_sequences_removed,
                report.private_chars_removed,
                len(original),
                len(cleaned),
            )

        # Host 整体替换 modified_kwargs，因此须保留所有输入参数。
        # 空串也必须传递：Host 会停止这次发送，不能恢复泄漏原文。
        modified = dict(kwargs)
        modified["response"] = cleaned
        return {"action": "continue", "modified_kwargs": modified}


def create_plugin() -> ReplySanitizerPlugin:
    """宿主的插件工厂入口。"""

    return ReplySanitizerPlugin()
