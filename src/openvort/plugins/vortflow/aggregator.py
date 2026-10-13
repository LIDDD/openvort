"""VortFlow IM notification aggregator — batches notifications per user to prevent IM spam."""

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass

from openvort.utils.logging import get_logger

log = get_logger("plugins.vortflow.aggregator")

IM_PRIORITY = ["wecom", "dingtalk", "feishu"]


async def send_im_to_member(member_id: str, text: str) -> None:
    """Send IM text to a member via first available channel (lazy resolution)."""
    try:
        from openvort.db.engine import get_session_factory
        from openvort.core.services.notification import get_notification_center

        nc = get_notification_center()
        registry = nc._registry if nc else None
        if not registry:
            # NotificationCenter 未初始化（dev 模式 / 启动失败）—— 任何 VortFlow IM
            # 通知都会从这里默默丢失。打 warning 让运维一眼看出根因。
            log.warning(
                "VortFlow IM skipped (no channel registry): recipient=%s, "
                "NotificationCenter 未初始化，请检查启动日志或确认非 --dev 模式",
                member_id,
            )
            return

        sf = get_session_factory()

        im_priority = IM_PRIORITY
        try:
            from openvort.contacts.models import Member as _Member
            async with sf() as db:
                m = await db.get(_Member, member_id)
                if not m:
                    # member_id 在 members 表里查不到 —— 通常是上游传入了「显示名」而不是
                    # member.id（历史脏数据 collaborators_json 存名字 / 前端 fallback 把
                    # 名字当 ID 等都会触发）。这是必须暴露的链路缺陷。
                    log.warning(
                        "VortFlow IM skipped (unknown recipient): recipient=%r, "
                        "members 表查不到该 ID（可能上游传入了显示名而非 member_id）",
                        member_id,
                    )
                    return
                if m and m.notification_prefs:
                    prefs = json.loads(m.notification_prefs) if isinstance(m.notification_prefs, str) else m.notification_prefs
                    vf_prefs = prefs.get("vortflow", {})
                    if not vf_prefs.get("im", True):
                        log.info(
                            "VortFlow IM skipped (user pref disabled): recipient=%s/%s",
                            member_id, m.name,
                        )
                        return
                    im_priority = prefs.get("im_channel_priority", IM_PRIORITY)
        except Exception as exc:
            log.warning("VortFlow IM prefs load failed for %s: %s", member_id, exc)

        try:
            from sqlalchemy import select as _sel
            from openvort.contacts.models import PlatformIdentity
            async with sf() as db:
                rows = (await db.execute(
                    _sel(PlatformIdentity.platform, PlatformIdentity.platform_user_id)
                    .where(PlatformIdentity.member_id == member_id)
                )).all()
            platform_map = {r[0]: r[1] for r in rows}
        except Exception as exc:
            log.warning("VortFlow IM identities query failed for %s: %s", member_id, exc)
            platform_map = {}

        if not platform_map:
            log.warning(
                "VortFlow IM skipped (no platform binding): recipient=%s, "
                "该成员没有任何 PlatformIdentity 绑定（企微/钉钉/飞书都没绑），"
                "请先到通讯录同步 / 绑定平台账号",
                member_id,
            )
            return

        from openvort.plugin.base import Message as _Msg

        attempted = []
        for channel_name in im_priority:
            platform_uid = platform_map.get(channel_name)
            if not platform_uid:
                continue
            ch = registry.get_channel(channel_name)
            if not ch or not ch.is_configured():
                attempted.append(f"{channel_name}(channel_unavailable)")
                continue
            try:
                await ch.send(platform_uid, _Msg(content=text, channel=channel_name))
                log.info("VortFlow IM sent to %s via %s", member_id, channel_name)
                return
            except Exception as exc:
                attempted.append(f"{channel_name}({exc})")
                log.warning("VortFlow IM send failed via %s: %s", channel_name, exc)
        # 所有可用通道都失败 / 优先级里没有 channel 命中 platform_map
        log.warning(
            "VortFlow IM not delivered to %s. priority=%s, bindings=%s, attempted=%s",
            member_id, im_priority, list(platform_map.keys()), attempted,
        )
    except Exception as exc:
        log.warning("send_im_to_member error for %s: %s", member_id, exc)


@dataclass
class NotificationPayload:
    title: str
    summary: str
    im_text: str = ""
    source_id: str = ""
    entity_type: str = ""
    entity_id: str = ""


class NotificationAggregator:
    """Per-user notification queue with timed batch flush.

    Enqueued notifications are held in memory and flushed every FLUSH_INTERVAL
    seconds.  All pending items for a given user are merged into a single IM
    message to avoid flooding the channel.

    实时通知（如评论、@提及）应使用 ``immediate=True`` 绕过批量窗口，
    以保证用户能第一时间看到，并且 IM 文本里携带的工作项链接不会因聚合
    格式被丢弃。
    """

    FLUSH_INTERVAL = 30  # seconds

    def __init__(self):
        self._buffer: dict[str, list[NotificationPayload]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._channel_sender = None  # callable(member_id, message) -> coroutine

    def set_channel_sender(self, sender):
        """Inject the IM send function. Expected signature: async def sender(member_id: str, text: str)"""
        self._channel_sender = sender

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._flush_loop())
            log.info("VortFlow notification aggregator started (flush every %ds)", self.FLUSH_INTERVAL)

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._flush()  # drain remaining

    async def enqueue(
        self,
        member_id: str,
        payload: NotificationPayload,
        *,
        immediate: bool = False,
    ):
        if immediate:
            await self._send_one(member_id, payload)
            return
        async with self._lock:
            self._buffer[member_id].append(payload)

    async def _flush_loop(self):
        try:
            while True:
                await asyncio.sleep(self.FLUSH_INTERVAL)
                await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self):
        async with self._lock:
            batch = dict(self._buffer)
            self._buffer.clear()

        for member_id, payloads in batch.items():
            if not payloads:
                continue
            text = self._format_batch(payloads)
            if not self._channel_sender:
                log.warning(
                    "Notification flush dropped for %s (channel_sender 未注入，"
                    "VortFlowPlugin 可能未正确初始化)",
                    member_id,
                )
                continue
            try:
                await self._channel_sender(member_id, text)
            except Exception:
                log.warning("Failed to send IM notification to %s", member_id, exc_info=True)

    async def _send_one(self, member_id: str, payload: NotificationPayload):
        text = payload.im_text or f"【{payload.title}】\n{payload.summary}"
        if not self._channel_sender:
            log.warning(
                "Immediate notification dropped for %s (channel_sender 未注入)",
                member_id,
            )
            return
        try:
            await self._channel_sender(member_id, text)
        except Exception:
            log.warning("Failed to send IM notification to %s", member_id, exc_info=True)

    @staticmethod
    def _format_batch(payloads: list[NotificationPayload]) -> str:
        if len(payloads) == 1:
            p = payloads[0]
            return p.im_text or f"【{p.title}】\n{p.summary}"
        lines = [f"你有 {len(payloads)} 条新通知："]
        limit = min(len(payloads), 5)
        for i, p in enumerate(payloads[:limit], 1):
            lines.append("")
            lines.append(f"{i}. {p.im_text or f'【{p.title}】{p.summary}'}")
        if len(payloads) > 5:
            lines.append("")
            lines.append(f"... 还有 {len(payloads) - 5} 条通知")
        return "\n".join(lines)


# Module-level singleton
im_aggregator = NotificationAggregator()
