"""Manual notification endpoint — remind / urge work item participants."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from openvort.web.app import require_auth
from openvort.plugins.vortflow.notifier import notifier as _notifier, schedule_notification
from openvort.utils.logging import get_logger

log = get_logger("plugins.vortflow.router.notify")

sub_router = APIRouter()


class NotifyRequest(BaseModel):
    entity_type: str  # story / task / bug
    entity_id: str
    title: str
    project_id: str = ""
    notify_type: str = "remind"  # remind / urge
    recipient_ids: list[str] = []
    message: str = ""


@sub_router.post("/notify")
async def send_notify(body: NotifyRequest, request: Request):
    """Send a manual reminder or urge notification to specified recipients."""
    payload = require_auth(request)
    actor_id = payload.get("sub") or payload.get("member_id", "")

    if not body.recipient_ids:
        raise HTTPException(status_code=400, detail="recipient_ids is empty")
    if body.notify_type not in ("remind", "urge"):
        raise HTTPException(status_code=400, detail="notify_type must be remind or urge")

    effective = [r for r in body.recipient_ids if r and r != actor_id]
    if not effective:
        raise HTTPException(status_code=400, detail="cannot_notify_self")

    schedule_notification(
        _notifier.notify_manual(
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            title=body.title,
            project_id=body.project_id,
            actor_id=actor_id,
            recipient_ids=body.recipient_ids,
            notify_type=body.notify_type,
            custom_message=body.message,
        )
    )

    return {"success": True}


class NotifyMemberRequest(BaseModel):
    """Payload for the member-watchlist 'remind workload' notification.

    Unlike the work-item notify endpoint, this is not bound to any specific
    work item — it nudges a single member to look at their pending workload
    snapshot. The optional counters are echoed in the IM message body so the
    receiver gets concrete numbers without opening the app.
    """

    recipient_id: str
    notify_type: str = "remind"  # remind / urge
    message: str = ""
    project_id: str = ""
    pending_total: int = 0
    overdue: int = 0
    due_soon: int = 0
    stale_count: int = 0


@sub_router.post("/notify/member")
async def send_notify_member(body: NotifyMemberRequest, request: Request):
    """Send a remind/urge notification about a member's overall pending workload."""
    payload = require_auth(request)
    actor_id = payload.get("sub") or payload.get("member_id", "")

    if not body.recipient_id:
        raise HTTPException(status_code=400, detail="recipient_id is empty")
    if body.notify_type not in ("remind", "urge"):
        raise HTTPException(status_code=400, detail="notify_type must be remind or urge")
    if body.recipient_id == actor_id:
        raise HTTPException(status_code=400, detail="cannot notify yourself")

    schedule_notification(
        _notifier.notify_member_workload(
            actor_id=actor_id,
            recipient_id=body.recipient_id,
            notify_type=body.notify_type,
            custom_message=body.message,
            project_id=body.project_id,
            pending_total=body.pending_total,
            overdue=body.overdue,
            due_soon=body.due_soon,
            stale_count=body.stale_count,
        )
    )

    return {"success": True}
