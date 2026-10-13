"""审计事件写入辅助。"""

import json

from openvort.plugins.vortflow.models import FlowEvent


async def _log_event(
    session,
    entity_type: str,
    entity_id: str,
    action: str,
    detail: dict | None = None,
    *,
    actor_id: str | None = None,
):
    ev = FlowEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id or None,
        detail=json.dumps(detail or {}, ensure_ascii=False),
    )
    session.add(ev)
