"""父需求 / 父任务的进度自动汇总（按子任务进度均值）。"""

from sqlalchemy import func, select

from openvort.plugins.vortflow.models import FlowStory, FlowTask


async def _calc_task_progress(session, task_id: str) -> int | None:
    """Calculate parent task progress as average of child tasks.
    Returns computed value if children exist, None otherwise."""
    result = await session.execute(
        select(func.avg(FlowTask.progress), func.count())
        .where(FlowTask.parent_id == task_id)
    )
    row = result.one()
    count = row[1] or 0
    if count == 0:
        return None
    return round(row[0] or 0)


async def _calc_story_progress(session, story_id: str) -> int | None:
    """Calculate story progress as average of all related tasks
    (direct tasks + tasks under descendant stories).
    Returns computed value if tasks exist, None otherwise."""
    all_story_ids = [story_id]
    pending = [story_id]
    while pending:
        child_rows = (
            await session.execute(
                select(FlowStory.id).where(FlowStory.parent_id.in_(pending))
            )
        ).scalars().all()
        next_ids = [cid for cid in child_rows if cid not in all_story_ids]
        if not next_ids:
            break
        all_story_ids.extend(next_ids)
        pending = next_ids

    result = await session.execute(
        select(func.avg(FlowTask.progress), func.count())
        .where(FlowTask.story_id.in_(all_story_ids))
    )
    row = result.one()
    count = row[1] or 0
    if count == 0:
        return None
    return round(row[0] or 0)


async def _attach_story_progress(session, items: list[dict]) -> list[dict]:
    """Batch-compute progress for story list items."""
    story_ids = [str(item.get("id") or "") for item in items if item.get("id")]
    if not story_ids:
        return items

    all_story_ids = list(story_ids)
    parent_map: dict[str, str] = {}
    pending = list(story_ids)
    while pending:
        child_rows = (
            await session.execute(
                select(FlowStory.id, FlowStory.parent_id)
                .where(FlowStory.parent_id.in_(pending))
            )
        ).all()
        next_ids = []
        for cid, pid in child_rows:
            if cid not in all_story_ids:
                all_story_ids.append(cid)
                parent_map[cid] = pid
                next_ids.append(cid)
        if not next_ids:
            break
        pending = next_ids

    task_rows = (
        await session.execute(
            select(FlowTask.story_id, FlowTask.progress)
            .where(FlowTask.story_id.in_(all_story_ids))
        )
    ).all()

    def _root_story(sid: str) -> str:
        visited: set[str] = set()
        while sid in parent_map and sid not in visited:
            visited.add(sid)
            sid = parent_map[sid]
        return sid

    story_task_progress: dict[str, list[int]] = {sid: [] for sid in story_ids}
    for task_story_id, task_progress in task_rows:
        root = _root_story(str(task_story_id or ""))
        if root in story_task_progress:
            story_task_progress[root].append(task_progress or 0)

    for item in items:
        sid = str(item.get("id") or "")
        tasks_progress = story_task_progress.get(sid, [])
        if tasks_progress:
            item["progress"] = round(sum(tasks_progress) / len(tasks_progress))

    return items


async def _attach_task_progress(session, items: list[dict]) -> list[dict]:
    """Batch-compute progress for parent tasks in a task list."""
    task_ids = [str(item.get("id") or "") for item in items if item.get("id")]
    if not task_ids:
        return items

    result = (
        await session.execute(
            select(FlowTask.parent_id, func.avg(FlowTask.progress), func.count())
            .where(FlowTask.parent_id.in_(task_ids))
            .group_by(FlowTask.parent_id)
        )
    ).all()

    parent_progress: dict[str, int] = {}
    for parent_id, avg_progress, count in result:
        if count and count > 0:
            parent_progress[str(parent_id)] = round(avg_progress or 0)

    for item in items:
        tid = str(item.get("id") or "")
        if tid in parent_progress:
            item["progress"] = parent_progress[tid]

    return items
