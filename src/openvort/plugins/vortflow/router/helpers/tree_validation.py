"""Story 父子层级与 Task story/parent 解析的校验辅助。"""

from sqlalchemy import select

from openvort.plugins.vortflow.models import FlowStory, FlowTask


async def _validate_story_parent(
    session,
    *,
    project_id: str,
    parent_id: str | None,
    story_id: str | None = None,
) -> tuple[str | None, str | None]:
    normalized_parent_id = (parent_id or "").strip() or None
    if normalized_parent_id is None:
        return None, None
    if story_id and normalized_parent_id == story_id:
        return None, "父需求不能是自身"

    parent = await session.get(FlowStory, normalized_parent_id)
    if not parent:
        return None, "父需求不存在"
    if parent.project_id != project_id:
        return None, "父需求必须和当前需求属于同一个项目"

    if story_id:
        cursor = parent
        while cursor and cursor.parent_id:
            if cursor.parent_id == story_id:
                return None, "不能将需求移动到自己的子需求下"
            cursor = await session.get(FlowStory, cursor.parent_id)

    return normalized_parent_id, None


async def _collect_story_descendant_ids(session, story_ids: list[str]) -> list[str]:
    pending_ids = [story_id for story_id in story_ids if story_id]
    descendant_ids: list[str] = []
    seen: set[str] = set(pending_ids)
    while pending_ids:
        child_rows = (
            await session.execute(select(FlowStory.id).where(FlowStory.parent_id.in_(pending_ids)))
        ).scalars().all()
        next_ids = [child_id for child_id in child_rows if child_id not in seen]
        if not next_ids:
            break
        descendant_ids.extend(next_ids)
        seen.update(next_ids)
        pending_ids = next_ids
    return descendant_ids


async def _resolve_task_story_and_parent(
    session,
    *,
    story_id: str | None,
    parent_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    normalized_story_id = (story_id or "").strip() or None
    normalized_parent_id = (parent_id or "").strip() or None

    parent_task: FlowTask | None = None
    if normalized_parent_id:
        parent_task = await session.get(FlowTask, normalized_parent_id)
        if not parent_task:
            return None, None, "父任务不存在"
        if parent_task.parent_id:
            return None, None, "父任务不能是子任务"

        if normalized_story_id and parent_task.story_id and normalized_story_id != parent_task.story_id:
            return None, None, "子任务必须和父任务属于同一个需求"
        normalized_story_id = normalized_story_id or parent_task.story_id

    if normalized_story_id:
        story = await session.get(FlowStory, normalized_story_id)
        if not story:
            return None, None, "关联需求不存在"

    return normalized_story_id, normalized_parent_id, None
