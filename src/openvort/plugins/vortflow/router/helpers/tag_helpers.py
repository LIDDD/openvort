"""标签使用统计、改名/删除替换、自动同步。"""

import json

from sqlalchemy import func, select

from openvort.plugins.vortflow.models import FlowBug, FlowStory, FlowTag, FlowTask

from .parsers import _parse_json_list


async def _count_tag_usage(session, tag_name: str) -> int:
    """Count work items using the given tag name across stories/tasks/bugs."""
    total = 0
    for model in (FlowStory, FlowTask, FlowBug):
        result = await session.execute(
            select(func.count()).select_from(model).where(
                model.tags_json.contains(json.dumps(tag_name, ensure_ascii=False))
            )
        )
        total += result.scalar() or 0
    return total


async def _replace_tag_in_items(session, old_name: str, new_name: str | None):
    """Replace or remove a tag across all work item tables."""
    for model in (FlowStory, FlowTask, FlowBug):
        result = await session.execute(
            select(model).where(
                model.tags_json.contains(json.dumps(old_name, ensure_ascii=False))
            )
        )
        items = result.scalars().all()
        for item in items:
            tags = _parse_json_list(item.tags_json)
            tags = [t for t in tags if t != old_name]
            if new_name and new_name not in tags:
                tags.append(new_name)
            item.tags_json = json.dumps(tags, ensure_ascii=False)


async def _collect_used_tag_names(session) -> set[str]:
    """Collect all distinct tag names used across work items."""
    names: set[str] = set()
    for model in (FlowStory, FlowTask, FlowBug):
        result = await session.execute(
            select(model.tags_json).where(model.tags_json != "[]")
        )
        for (raw,) in result:
            for tag in _parse_json_list(raw):
                if tag:
                    names.add(tag)
    return names


_TAG_AUTO_COLORS = [
    "#ef4444", "#d946ef", "#eab308", "#22c55e",
    "#3b82f6", "#f97316", "#14b8a6", "#8b5cf6",
    "#6366f1", "#0ea5e9", "#ec4899", "#f43f5e",
]


async def _sync_missing_tags(session) -> bool:
    """Auto-create FlowTag rows for tags used in work items but not yet defined.
    Returns True if any tags were created."""
    used = await _collect_used_tag_names(session)
    if not used:
        return False
    result = await session.execute(select(FlowTag.name))
    existing = {row[0] for row in result}
    missing = used - existing

    if not missing:
        return False

    max_order_result = await session.execute(
        select(func.coalesce(func.max(FlowTag.sort_order), 0))
    )
    next_order = (max_order_result.scalar() or 0) + 1

    for idx, name in enumerate(sorted(missing)):
        color = _TAG_AUTO_COLORS[(next_order + idx) % len(_TAG_AUTO_COLORS)]
        session.add(FlowTag(name=name, color=color, sort_order=next_order + idx))
    await session.flush()
    return True
