"""测试模块树查询 + 测试用例与工作项关联解析。"""

from sqlalchemy import select

from openvort.plugins.vortflow.models import (
    FlowBug,
    FlowStory,
    FlowTask,
    FlowTestCase,
    FlowTestCaseWorkItem,
    FlowTestModule,
)


async def _get_descendant_module_ids(session, parent_id: str) -> list[str]:
    """Recursively get all descendant module IDs."""
    result = await session.execute(
        select(FlowTestModule.id).where(FlowTestModule.parent_id == parent_id)
    )
    child_ids = [r[0] for r in result.all()]
    all_ids = list(child_ids)
    for cid in child_ids:
        all_ids.extend(await _get_descendant_module_ids(session, cid))
    return all_ids


async def _build_module_path(session, module: FlowTestModule) -> str:
    """Build full path like 'root/child/leaf'."""
    parts = [module.name]
    current = module
    while current.parent_id:
        parent = await session.get(FlowTestModule, current.parent_id)
        if not parent:
            break
        parts.insert(0, parent.name)
        current = parent
    return "/".join(parts)


async def _resolve_linked_entity(session, link: FlowTestCaseWorkItem) -> dict:
    """Resolve the full info for a link record."""
    from openvort.contacts.models import Member

    base = {
        "link_id": link.id,
        "test_case_id": link.test_case_id,
        "entity_type": link.entity_type,
        "entity_id": link.entity_id,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }

    tc = await session.get(FlowTestCase, link.test_case_id)
    if tc:
        base["test_case_title"] = tc.title
        base["test_case_priority"] = tc.priority
        base["test_case_case_type"] = tc.case_type
        base["test_case_review_result"] = tc.review_result
        if tc.maintainer_id:
            member = await session.get(Member, tc.maintainer_id)
            base["test_case_maintainer"] = member.name if member else ""
        else:
            base["test_case_maintainer"] = ""

    entity_model = {"story": FlowStory, "task": FlowTask, "bug": FlowBug}.get(link.entity_type)
    if entity_model:
        entity = await session.get(entity_model, link.entity_id)
        if entity:
            base["entity_title"] = entity.title
            base["entity_state"] = entity.state

    return base
