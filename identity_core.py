"""Deterministic metadata-only identity core; no SDK, storage, network or model calls."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import md5
from threading import RLock
from time import monotonic
from typing import Callable
import re
import secrets

ALIAS = re.compile(r"m[a-z2-7]{6}\Z")

def token(value):
    return isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= 512

def session_digest(platform, account_id, scope, uid, group_id=None):
    """Pinned Host 1.3.12 SessionUtils algorithm, tested against actual source."""
    route = [f"account:{account_id}"]
    if scope is not None:
        route.append(f"scope:{scope}")
    parts = [platform, *route, group_id] if group_id else [platform, *route, uid, "private"]
    return md5("_".join(parts).encode()).hexdigest()

@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    mode: str = "explicit_binding"
    binding_semantics_confirmed: bool = False
    native_single_sender_confirmed: bool = False
    single_source_confirmed: bool = False
    platform: str = ""
    account_id: str = ""
    scope: str = ""
    allow_missing_scope: bool = False
    creator_uid: str = ""
    allowed_session_ids: tuple[str, ...] = ()
    all_sessions: bool = False
    ttl_seconds: int = 600
    capacity: int = 2048
    creator_name: str = ""

    def problem(self):
        if not self.enabled:
            return "disabled"
        if self.mode != "explicit_binding":
            return "invalid_mode"
        if not all(token(v) for v in (self.platform, self.account_id, self.creator_uid)):
            return "binding_incomplete"
        if (not self.all_sessions and not self.allowed_session_ids) or not all(token(v) for v in self.allowed_session_ids):
            return "session_allowlist_missing"
        if not self.single_source_confirmed or not self.native_single_sender_confirmed:
            return "source_assumptions_unconfirmed"
        if self.scope == "" and not self.allow_missing_scope:
            return "scope_unbound"
        if self.scope != "" and not token(self.scope):
            return "invalid_scope"
        if not (1 <= self.ttl_seconds <= 3600 and 1 <= self.capacity <= 10000):
            return "invalid_cache_limits"
        if self.mode == "explicit_binding" and not self.binding_semantics_confirmed:
            return "binding_semantics_unconfirmed"
        return None

@dataclass(frozen=True)
class Entry:
    platform: str
    account_id: str
    scope: str | None
    session_id: str
    message_id: str
    uid: str | None
    received_at: float
    epoch: int
    reference: str
    reason: str = "cached"
    is_group: bool = False

@dataclass(frozen=True)
class Verdict:
    creator_verified: bool = False
    reason: str = "unverified"
    subject_message_ref: str | None = None
    target_verified: bool = False
    focus_verified: bool = False
    focus_scope: str | None = None
    creator_name: str | None = None
    focus_name: str | None = None

    def payload(self):
        return {"schema_version": 1, "subject_kind": "reply_target_sender",
                "subject_message_ref": self.subject_message_ref,
                "creator_verified": self.creator_verified, "reason": self.reason,
                "creator_name": (self.creator_name or None) if self.creator_verified else None,
                "focus_name": (self.focus_name or None) if self.focus_verified else None,
                "authorization": "relationship_only", "target_verified": self.target_verified,
                "focus_verified": self.focus_verified, "focus_scope": self.focus_scope}

class IdentityEngine:
    """No recent-speaker/alias index. Operations are synchronous and locked."""
    def __init__(self, settings=Settings(), clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._lock = RLock()
        self.epoch = 0
        self.settings = settings
        self._entries = OrderedDict()
        self._quarantine_until = 0.0
        self.attention_enabled = True
        self.attention_names = {}

    def configure(self, settings, *, attention_enabled=None, attention_qq_numbers=None, attention_names=None):
        with self._lock:
            self.epoch += 1
            self.settings = settings
            if attention_enabled is not None:
                self.attention_enabled = attention_enabled
            if attention_names is not None:
                self.attention_names = dict(attention_names)
            elif attention_qq_numbers is not None:
                self.attention_names = {q: "" for q in attention_qq_numbers}
            self._entries.clear()
            self._quarantine_until = 0.0

    def clear(self):
        self.configure(Settings(), attention_enabled=False, attention_qq_numbers=())

    def _prune(self, now):
        for key, entry in list(self._entries.items()):
            if now - entry.received_at >= self.settings.ttl_seconds or entry.epoch != self.epoch:
                del self._entries[key]

    def _put(self, route, sid, mid, uid, reason, now, is_group=False):
        key = (*route, sid, mid)
        old = self._entries.get(key)
        if old:
            if old.uid != uid or old.reason != reason or old.is_group != is_group:
                self._entries[key] = Entry(*route, sid, mid, None, old.received_at,
                                           self.epoch, old.reference, "duplicate_conflict")
            return
        if len(self._entries) >= self.settings.capacity:
            self._entries.clear()
            self._quarantine_until = now + self.settings.ttl_seconds
            return
        self._entries[key] = Entry(*route, sid, mid, uid, now, self.epoch,
                                   "target-" + secrets.token_hex(12), reason, is_group)

    def capture(self, message):
        with self._lock:
            cfg = self.settings
            if cfg.problem():
                return cfg.problem()
            now = self._clock()
            self._prune(now)
            if now < self._quarantine_until:
                return "capacity_quarantine"
            if not isinstance(message, dict):
                return "metadata_missing"
            platform, account, scope = (message.get(k) for k in ("platform", "account_id", "scope"))
            sid, mid = message.get("session_id"), message.get("message_id")
            if not all(token(v) for v in (platform, account, sid, mid)) or "scope" not in message:
                return "metadata_missing"
            if scope is not None and not token(scope):
                return "metadata_missing"
            route = (platform, account, scope)
            info = message.get("message_info")
            user = info.get("user_info") if isinstance(info, dict) else None
            uid = user.get("user_id") if isinstance(user, dict) else None
            additional = info.get("additional_config") if isinstance(info, dict) else None
            kind = additional.get("napcat_message_type") if isinstance(additional, dict) else None
            group = info.get("group_info") if isinstance(info, dict) else None
            gid = group.get("group_id") if isinstance(group, dict) else None
            reason = "cached"
            if not token(uid):
                reason = "sender_missing"
            elif message.get("is_notify") is not False or uid == account:
                reason = "nonhuman_or_self"
            elif kind not in ("group", "private"):
                reason = "sender_type_unproven"
            elif (kind == "group" and not token(gid)) or (kind == "private" and group is not None):
                reason = "target_metadata_invalid"
            elif any(additional.get(k) for k in ("merged", "is_merged", "merged_message_ids", "sender_ids", "synthetic")):
                reason = "merged_or_ambiguous"
            elif message.get("sender_type", "human") != "human" or message.get("is_system", False) is not False:
                reason = "nonhuman_or_self"
            elif session_digest(platform, account, scope, uid, gid) != sid:
                reason = "session_route_mismatch"
            # Inspect only segment TYPE, never data/text/forwarded sender payloads.
            segments = message.get("raw_message")
            safe_types = {"text", "image", "picture", "face", "emoji", "at", "reply", "record", "voice", "video", "file"}
            if not isinstance(segments, list) or not segments or any(
                not isinstance(x, dict) or x.get("type") not in safe_types for x in segments
            ):
                reason = "merged_or_ambiguous"
            self._put(route, sid, mid, uid if reason == "cached" else None, reason, now, kind == "group")
            return reason

    def verify(self, session_id, reply_message_id, reply_tool_args=None):
        with self._lock:
            cfg = self.settings
            problem = cfg.problem()
            if problem:
                return Verdict(reason=problem)
            if not token(session_id) or (not cfg.all_sessions and session_id not in cfg.allowed_session_ids):
                return Verdict(reason="session_not_allowed")
            if not token(reply_message_id):
                return Verdict(reason="target_missing")
            if ALIAS.fullmatch(reply_message_id):
                return Verdict(reason="alias_unverifiable")
            if reply_tool_args is not None and not isinstance(reply_tool_args, dict):
                return Verdict(reason="target_arguments_invalid")
            args = reply_tool_args or {}
            if any(k in args for k in ("reply_message_ids", "message_ids", "targets", "reply_targets")):
                return Verdict(reason="multiple_targets")
            if "reply_to" in args and args["reply_to"] != reply_message_id:
                return Verdict(reason="target_mismatch")
            now = self._clock()
            self._prune(now)
            if now < self._quarantine_until:
                return Verdict(reason="capacity_quarantine")
            expected_route = (cfg.platform, cfg.account_id, cfg.scope or None)
            candidates = [e for e in self._entries.values()
                          if e.session_id == session_id and e.message_id == reply_message_id]
            if len(candidates) != 1:
                return Verdict(reason="target_ambiguous" if candidates else "cache_miss")
            entry = candidates[0]
            if (entry.platform, entry.account_id, entry.scope) != expected_route:
                return Verdict(reason="route_mismatch")
            if entry.uid is None:
                return Verdict(reason=entry.reason)
            if entry.epoch != self.epoch:
                return Verdict(reason="epoch_mismatch")
            focus = bool(self.attention_enabled and entry.is_group and cfg.platform == "qq"
                         and entry.uid in self.attention_names)
            return Verdict(entry.uid == cfg.creator_uid,
                           "binding_match" if entry.uid == cfg.creator_uid else "uid_not_bound", entry.reference,
                           target_verified=True, focus_verified=focus,
                           focus_scope="group_reply_target_this_request" if focus else None,
                           creator_name=(cfg.creator_name or None) if entry.uid == cfg.creator_uid else None,
                           focus_name=(self.attention_names.get(entry.uid) or None) if focus else None)
