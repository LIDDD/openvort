"""VortCert plugin — SSL/TLS certificate management for OpenVort."""

import asyncio
from pathlib import Path

from openvort.plugin.base import BasePlugin, BaseTool
from openvort.utils.logging import get_logger

log = get_logger("plugins.vortcert")

PATROL_JOB_ID = "vortcert_patrol"
DEFAULT_PATROL_CRON = "0 8 * * *"
ALERT_STATUSES = {"warning", "critical", "expired"}


class VortCertPlugin(BasePlugin):
    """SSL/TLS 证书管理插件 — 域名监控、证书签发、到期预警"""

    name = "vortcert"
    display_name = "VortCert 证书管理"
    description = "SSL/TLS 证书全生命周期管理：域名监控、Let's Encrypt 签发、到期预警"
    version = "0.1.0"

    _acme_email: str = ""
    _patrol_cron: str = DEFAULT_PATROL_CRON
    _patrol_enabled: bool = True
    _scheduler = None
    _ws_manager = None

    def __init__(self):
        try:
            from openvort.web.ws import manager as ws_manager
            self._ws_manager = ws_manager
        except ImportError:
            pass
        asyncio.create_task(self._init_patrol())

    async def _init_patrol(self):
        """Delayed init: give DB time to be fully ready, then register patrol job."""
        await asyncio.sleep(3)
        try:
            await self._migrate_certificate_data()
        except Exception as exc:
            log.warning("VortCert one-shot data migration failed: %s", exc)
        try:
            from openvort.core.services.scheduler import Scheduler
            self._scheduler = Scheduler()
            self._scheduler.start()
            self._sync_patrol_job()
            log.info("VortCert patrol service initialized")
        except Exception as exc:
            log.warning("Failed to initialize patrol service: %s", exc)

    async def _migrate_certificate_data(self) -> None:
        """One-shot, idempotent data fixup.

        1. Backfill `cert_certificates.expires_at` for rows where it is NULL — this
           covers certificates issued before the parse-expiry bug was fixed.
        2. Re-derive `cert_domains.last_check_status / expires_at / issuer` for
           every domain from its latest active certificate.

        Safe to run on every startup: rows that already have non-NULL `expires_at`
        are skipped, and `refresh_domain_status` is itself idempotent.
        """
        from sqlalchemy import select

        from openvort.db.engine import get_session_factory
        from openvort.plugins.vortcert.cert_inspector import parse_certificate
        from openvort.plugins.vortcert.crypto import decrypt_value
        from openvort.plugins.vortcert.models import CertCertificate, CertDomain
        from openvort.plugins.vortcert.router import refresh_domain_status

        sf = get_session_factory()
        backfilled = 0
        unparseable = 0

        async with sf() as session:
            result = await session.execute(
                select(CertCertificate).where(CertCertificate.expires_at.is_(None))
            )
            rows = result.scalars().all()
            for cert in rows:
                if not cert.cert_pem:
                    continue
                try:
                    info = parse_certificate(decrypt_value(cert.cert_pem))
                except Exception as exc:
                    log.debug("Cert pem decrypt failed during backfill (id=%s): %s", cert.id, exc)
                    unparseable += 1
                    continue
                if info.ok and info.not_after is not None:
                    cert.expires_at = info.not_after
                    backfilled += 1
                else:
                    unparseable += 1
            if rows:
                await session.commit()

        if backfilled or unparseable:
            log.info(
                "VortCert backfill cert_certificates.expires_at: backfilled=%d, unparseable=%d",
                backfilled, unparseable,
            )

        async with sf() as session:
            result = await session.execute(select(CertDomain))
            domains = result.scalars().all()
            for d in domains:
                try:
                    await refresh_domain_status(session, d.id)
                except Exception as exc:
                    log.warning("Failed to refresh status for %s: %s", d.domain, exc)
            if domains:
                await session.commit()
                log.info("VortCert refreshed status for %d domain(s)", len(domains))

    def _sync_patrol_job(self) -> None:
        if not self._scheduler:
            return
        self._scheduler.remove(PATROL_JOB_ID)
        if self._patrol_enabled and self._patrol_cron:
            self._scheduler.add_cron(PATROL_JOB_ID, self.run_patrol, self._patrol_cron)
            log.info("VortCert patrol registered: %s", self._patrol_cron)

    # ---- Patrol execution ----

    async def run_patrol(self) -> None:
        """Refresh certificate status for all domains and emit alerts for expiring / expired ones.

        Source of truth: `cert_certificates` table. We re-derive each domain's
        `last_check_status / expires_at / issuer` from its latest active certificate,
        then notify responsible members about warning/critical/expired states.
        """
        import uuid
        from datetime import datetime, timezone

        from sqlalchemy import select

        from openvort.db.engine import get_session_factory
        from openvort.plugins.vortcert.models import CertCheckLog, CertDomain
        from openvort.plugins.vortcert.router import refresh_domain_status

        def _utcnow_naive():
            return datetime.now(timezone.utc).replace(tzinfo=None)

        log.info("VortCert patrol started")

        sf = get_session_factory()
        async with sf() as session:
            result = await session.execute(select(CertDomain))
            domains = result.scalars().all()

        if not domains:
            log.info("No domains to patrol")
            return

        now = _utcnow_naive()
        alert_entries: list[dict] = []
        summary: dict[str, int] = {}

        async with sf() as session:
            for d in domains:
                derived = await refresh_domain_status(session, d.id)
                if not derived.get("ok"):
                    continue

                domain_obj = await session.get(CertDomain, d.id)
                if not domain_obj:
                    continue

                status = derived.get("status") or ""
                summary[status or "unchecked"] = summary.get(status or "unchecked", 0) + 1

                log_entry = CertCheckLog(
                    id=uuid.uuid4().hex,
                    domain_id=d.id,
                    domain=domain_obj.domain,
                    checked_at=now,
                    expires_at=domain_obj.expires_at,
                    issuer=domain_obj.issuer or "",
                    status=status,
                    error_message="",
                    serial_number="",
                    source="derived",
                )
                session.add(log_entry)

                if status in ALERT_STATUSES:
                    alert_entries.append({
                        "domain": domain_obj.domain,
                        "status": status,
                        "days_remaining": derived.get("days_remaining"),
                        "responsible_member_id": domain_obj.responsible_member_id,
                    })

            await session.commit()

        log.info("VortCert patrol done: %s", summary)

        if alert_entries:
            await self._send_alerts(alert_entries)

    async def _send_alerts(self, entries: list[dict]) -> None:
        lines: list[str] = []
        notify_members: set[str] = set()

        for e in entries:
            status_label = {"warning": "即将到期", "critical": "紧急", "expired": "已过期"}.get(e["status"], e["status"])
            days = e["days_remaining"]
            if days is not None and days >= 0:
                lines.append(f"  {e['domain']} — {status_label}（剩余 {days} 天）")
            else:
                lines.append(f"  {e['domain']} — {status_label}")
            if e.get("responsible_member_id"):
                notify_members.add(e["responsible_member_id"])

        title = f"VortCert 巡检预警：{len(entries)} 个域名证书异常"
        body = "\n".join(lines)

        if self._ws_manager:
            try:
                await self._ws_manager.broadcast({
                    "type": "vortcert_alert",
                    "title": title,
                    "summary": body[:500],
                    "count": len(entries),
                })
            except Exception as exc:
                log.warning("WebSocket broadcast failed: %s", exc)

        if not notify_members:
            return
        try:
            from openvort.core.services.notification import get_notification_center
            nc = get_notification_center()
            if not nc:
                return
            for mid in notify_members:
                member_lines = [
                    ln for ln, e in zip(lines, entries)
                    if e.get("responsible_member_id") == mid
                ]
                member_body = "\n".join(member_lines) if member_lines else body
                await nc.schedule_notify(
                    recipient_id=mid,
                    source="vortcert",
                    source_id="patrol",
                    title=title,
                    summary=member_body[:300],
                    delay_seconds=0,
                    severity="error" if any(
                        e["status"] in ("critical", "expired")
                        for e in entries if e.get("responsible_member_id") == mid
                    ) else "warning",
                )
                await asyncio.sleep(0.3)
        except Exception as exc:
            log.warning("IM notification failed: %s", exc)

    # ---- Tools / Prompts ----

    def get_tools(self) -> list[BaseTool]:
        from openvort.plugins.vortcert.tools import CertIssueTool, CertManageTool, CertQueryTool

        return [
            CertQueryTool(),
            CertIssueTool(),
            CertManageTool(),
        ]

    def get_prompts(self) -> list[str]:
        prompts_dir = Path(__file__).parent / "prompts"
        prompts = []
        for f in sorted(prompts_dir.glob("*.md")):
            try:
                prompts.append(f.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"Failed to read prompt file {f.name}: {e}")
        return prompts

    def get_permissions(self) -> list[dict]:
        return [
            {"code": "vortcert.read", "display_name": "VortCert 查看证书状态"},
            {"code": "vortcert.write", "display_name": "VortCert 管理域名和签发证书"},
        ]

    def get_roles(self) -> list[dict]:
        return [
            {
                "name": "vortcert_user",
                "display_name": "VortCert 用户",
                "permissions": ["vortcert.read", "vortcert.write"],
            },
        ]

    def validate_credentials(self) -> bool:
        return True

    # ---- Config ----

    def get_config_schema(self) -> list[dict]:
        return [
            {
                "key": "acme_email",
                "label": "ACME 注册邮箱",
                "type": "string",
                "required": True,
                "secret": False,
                "placeholder": "admin@example.com",
                "description": "Let's Encrypt 证书签发所需的邮箱地址",
            },
            {
                "key": "patrol_enabled",
                "label": "定时巡检",
                "type": "boolean",
                "required": False,
                "secret": False,
                "description": "是否启用定时证书巡检，巡检发现异常会通知域名负责人",
            },
            {
                "key": "patrol_cron",
                "label": "巡检时间（cron）",
                "type": "string",
                "required": False,
                "secret": False,
                "placeholder": "0 8 * * *",
                "description": "巡检 cron 表达式（分 时 日 月 周），默认每天 08:00",
            },
        ]

    def get_current_config(self) -> dict:
        return {
            "acme_email": self._acme_email,
            "patrol_enabled": self._patrol_enabled,
            "patrol_cron": self._patrol_cron,
        }

    def apply_config(self, config: dict) -> None:
        if "acme_email" in config:
            self._acme_email = config["acme_email"]

        need_resync = False
        if "patrol_enabled" in config:
            val = config["patrol_enabled"]
            if isinstance(val, str):
                val = val.lower() not in ("false", "0", "")
            new_enabled = bool(val)
            if new_enabled != self._patrol_enabled:
                self._patrol_enabled = new_enabled
                need_resync = True

        if "patrol_cron" in config:
            new_cron = config["patrol_cron"].strip() or DEFAULT_PATROL_CRON
            if new_cron != self._patrol_cron:
                self._patrol_cron = new_cron
                need_resync = True

        if need_resync:
            self._sync_patrol_job()

    def get_ui_extensions(self) -> dict | None:
        return {
            "menus": [
                {
                    "label": "VortCert",
                    "icon": "shield-check",
                    "path": "/vortcert",
                    "position": "sidebar",
                    "children": [
                        {"label": "证书总览", "path": "/vortcert/overview", "icon": "shield-check"},
                        {"label": "域名管理", "path": "/vortcert/domains", "icon": "globe"},
                        {"label": "DNS 配置", "path": "/vortcert/dns-providers", "icon": "server"},
                        {"label": "部署目标", "path": "/vortcert/deploy-targets", "icon": "rocket"},
                    ],
                }
            ],
        }

    def get_api_router(self):
        from openvort.plugins.vortcert.router import router

        return router
