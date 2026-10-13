"""把迭代/版本/活动度信息附加到工作项 dict 列表。

`_attach_xxx_links` 系列在 list 接口中调用，避免每条记录单独 JOIN，
统一一次批量查询填回 iteration_id/iteration_name/version_id/version_name 等字段。
"""

from datetime import datetime

from sqlalchemy import func, select

from openvort.plugins.vortflow.models import (
    FlowComment,
    FlowEvent,
    FlowIteration,
    FlowIterationBug,
    FlowIterationStory,
    FlowIterationTask,
    FlowProject,
    FlowStory,
    FlowVersion,
    FlowVersionStory,
)

from .parsers import _parse_dt


async def _attach_project_names(session, items: list[dict]) -> list[dict]:
    """为工作项列表补齐所属项目 id/名称，供多项目混排时区分归属。

    task/bug 的 ``project_id`` 可能为空（挂在需求下），此时经 story_id 回溯所属项目。
    统一批量查询避免逐条 JOIN。会写回 ``project_id``（补齐后的有效值）与 ``project_name``。
    """
    if not items:
        return items

    # 先经 story_id 回溯出缺失的 project_id
    missing_story_ids = [
        str(item.get("story_id") or "").strip()
        for item in items
        if not item.get("project_id") and item.get("story_id")
    ]
    story_project_map: dict[str, str] = {}
    if missing_story_ids:
        rows = await session.execute(
            select(FlowStory.id, FlowStory.project_id).where(FlowStory.id.in_(missing_story_ids))
        )
        story_project_map = {str(sid): str(pid or "") for sid, pid in rows.all()}

    for item in items:
        if not item.get("project_id"):
            pid = story_project_map.get(str(item.get("story_id") or "").strip(), "")
            if pid:
                item["project_id"] = pid

    project_ids = {str(item.get("project_id") or "").strip() for item in items if item.get("project_id")}
    name_map: dict[str, str] = {}
    if project_ids:
        rows = await session.execute(
            select(FlowProject.id, FlowProject.name).where(FlowProject.id.in_(project_ids))
        )
        name_map = {str(pid): str(name or "") for pid, name in rows.all()}

    for item in items:
        item["project_name"] = name_map.get(str(item.get("project_id") or "").strip(), "")
    return items


async def _attach_story_links(session, items: list[dict]) -> list[dict]:
    story_ids = [str(item.get("id") or "").strip() for item in items if item.get("id")]
    if not story_ids:
        return items

    iteration_rows = await session.execute(
        select(FlowIterationStory.story_id, FlowIteration.id, FlowIteration.name)
        .join(FlowIteration, FlowIteration.id == FlowIterationStory.iteration_id)
        .where(FlowIterationStory.story_id.in_(story_ids))
    )
    story_iteration_map: dict[str, tuple[str, str]] = {}
    for story_id, iteration_id, iteration_name in iteration_rows.all():
        sid = str(story_id or "")
        if sid and sid not in story_iteration_map:
            story_iteration_map[sid] = (str(iteration_id or ""), str(iteration_name or ""))

    version_rows = await session.execute(
        select(FlowVersionStory.story_id, FlowVersion.id, FlowVersion.name)
        .join(FlowVersion, FlowVersion.id == FlowVersionStory.version_id)
        .where(FlowVersionStory.story_id.in_(story_ids))
    )
    story_version_map: dict[str, tuple[str, str]] = {}
    for story_id, version_id, version_name in version_rows.all():
        sid = str(story_id or "")
        if sid and sid not in story_version_map:
            story_version_map[sid] = (str(version_id or ""), str(version_name or ""))

    for item in items:
        sid = str(item.get("id") or "").strip()
        iteration = story_iteration_map.get(sid)
        version = story_version_map.get(sid)
        item["iteration_id"] = iteration[0] if iteration else ""
        item["iteration_name"] = iteration[1] if iteration else ""
        item["version_id"] = version[0] if version else ""
        item["version_name"] = version[1] if version else ""

    await _attach_activity_info(session, items, "story")
    return items


async def _attach_task_links(session, items: list[dict]) -> list[dict]:
    task_ids = [str(item.get("id") or "").strip() for item in items if item.get("id")]
    if not task_ids:
        return items

    iteration_rows = await session.execute(
        select(FlowIterationTask.task_id, FlowIteration.id, FlowIteration.name)
        .join(FlowIteration, FlowIteration.id == FlowIterationTask.iteration_id)
        .where(FlowIterationTask.task_id.in_(task_ids))
    )
    task_iteration_map: dict[str, tuple[str, str]] = {}
    for task_id, iteration_id, iteration_name in iteration_rows.all():
        tid = str(task_id or "")
        if tid and tid not in task_iteration_map:
            task_iteration_map[tid] = (str(iteration_id or ""), str(iteration_name or ""))

    for item in items:
        tid = str(item.get("id") or "").strip()
        iteration = task_iteration_map.get(tid)
        item["iteration_id"] = iteration[0] if iteration else ""
        item["iteration_name"] = iteration[1] if iteration else ""

    await _attach_activity_info(session, items, "task")
    return items


async def _attach_bug_links(session, items: list[dict]) -> list[dict]:
    story_ids = [str(item.get("story_id") or "").strip() for item in items if item.get("story_id")]
    story_map: dict[str, dict] = {}
    if story_ids:
        story_items = [{"id": story_id} for story_id in story_ids]
        # NOTE: 这里只附加迭代/版本信息，避免对内部 stub items 做活动度查询
        await _attach_story_links_basic(session, story_items)
        story_map = {str(item["id"]): item for item in story_items}

    for item in items:
        linked_story = story_map.get(str(item.get("story_id") or "").strip())
        item["iteration_id"] = str((linked_story or {}).get("iteration_id") or "")
        item["iteration_name"] = str((linked_story or {}).get("iteration_name") or "")
        item["version_id"] = str((linked_story or {}).get("version_id") or "")
        item["version_name"] = str((linked_story or {}).get("version_name") or "")

    # 缺陷可不依附需求、直接加入迭代（flow_iteration_bugs）。直接关联优先级高于
    # 经由 story 继承的迭代，需用直接关联覆盖，否则无 story 或 story 未排期的缺陷
    # 在工作墙列表/详情里迭代列将为空。
    bug_ids = [str(item.get("id") or "").strip() for item in items if item.get("id")]
    if bug_ids:
        direct_rows = await session.execute(
            select(FlowIterationBug.bug_id, FlowIteration.id, FlowIteration.name)
            .join(FlowIteration, FlowIteration.id == FlowIterationBug.iteration_id)
            .where(FlowIterationBug.bug_id.in_(bug_ids))
        )
        bug_iteration_map: dict[str, tuple[str, str]] = {}
        for bug_id, iteration_id, iteration_name in direct_rows.all():
            bid = str(bug_id or "")
            if bid and bid not in bug_iteration_map:
                bug_iteration_map[bid] = (str(iteration_id or ""), str(iteration_name or ""))
        for item in items:
            direct = bug_iteration_map.get(str(item.get("id") or "").strip())
            if direct:
                item["iteration_id"] = direct[0]
                item["iteration_name"] = direct[1]

    await _attach_activity_info(session, items, "bug")
    return items


async def _attach_story_links_basic(session, items: list[dict]) -> list[dict]:
    """Attach iteration/version info only (no activity info)."""
    story_ids = [str(item.get("id") or "").strip() for item in items if item.get("id")]
    if not story_ids:
        return items

    iteration_rows = await session.execute(
        select(FlowIterationStory.story_id, FlowIteration.id, FlowIteration.name)
        .join(FlowIteration, FlowIteration.id == FlowIterationStory.iteration_id)
        .where(FlowIterationStory.story_id.in_(story_ids))
    )
    story_iteration_map: dict[str, tuple[str, str]] = {}
    for story_id, iteration_id, iteration_name in iteration_rows.all():
        sid = str(story_id or "")
        if sid and sid not in story_iteration_map:
            story_iteration_map[sid] = (str(iteration_id or ""), str(iteration_name or ""))

    version_rows = await session.execute(
        select(FlowVersionStory.story_id, FlowVersion.id, FlowVersion.name)
        .join(FlowVersion, FlowVersion.id == FlowVersionStory.version_id)
        .where(FlowVersionStory.story_id.in_(story_ids))
    )
    story_version_map: dict[str, tuple[str, str]] = {}
    for story_id, version_id, version_name in version_rows.all():
        sid = str(story_id or "")
        if sid and sid not in story_version_map:
            story_version_map[sid] = (str(version_id or ""), str(version_name or ""))

    for item in items:
        sid = str(item.get("id") or "").strip()
        iteration = story_iteration_map.get(sid)
        version = story_version_map.get(sid)
        item["iteration_id"] = iteration[0] if iteration else ""
        item["iteration_name"] = iteration[1] if iteration else ""
        item["version_id"] = version[0] if version else ""
        item["version_name"] = version[1] if version else ""
    return items


async def _attach_activity_info(session, items: list[dict], entity_type: str) -> list[dict]:
    """Attach last_activity_at = max(updated_at, last FlowEvent.created_at, last FlowComment.created_at).

    停滞标签使用，与成员级 stale_count 口径一致。
    """
    if not items:
        return items
    ids = [str(item.get("id") or "").strip() for item in items if item.get("id")]
    if not ids:
        return items

    event_rows = await session.execute(
        select(FlowEvent.entity_id, func.max(FlowEvent.created_at))
        .where(FlowEvent.entity_type == entity_type, FlowEvent.entity_id.in_(ids))
        .group_by(FlowEvent.entity_id)
    )
    event_map: dict[str, datetime] = {str(eid): ts for eid, ts in event_rows.all() if ts}

    comment_rows = await session.execute(
        select(FlowComment.entity_id, func.max(FlowComment.created_at))
        .where(FlowComment.entity_type == entity_type, FlowComment.entity_id.in_(ids))
        .group_by(FlowComment.entity_id)
    )
    comment_map: dict[str, datetime] = {str(eid): ts for eid, ts in comment_rows.all() if ts}

    for item in items:
        sid = str(item.get("id") or "").strip()
        candidates: list[datetime] = []
        upd = _parse_dt(item.get("updated_at"))
        if upd:
            candidates.append(upd)
        ev = event_map.get(sid)
        if ev:
            candidates.append(ev)
        cm = comment_map.get(sid)
        if cm:
            candidates.append(cm)
        if candidates:
            item["last_activity_at"] = max(candidates).isoformat()
        else:
            item["last_activity_at"] = item.get("updated_at") or None
    return items
