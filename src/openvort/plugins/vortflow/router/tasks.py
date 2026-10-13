import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select, delete as sa_delete, or_

from openvort.db.engine import get_session_factory
from openvort.web.app import require_auth
from openvort.plugins.vortflow.router.helpers import (
    _apply_state_change,
    _parse_dt,
    _task_dict,
    _log_event,
    _apply_sort,
    _parse_json_list,
    resolve_project_ids,
    _resolve_task_story_and_parent,
    _attach_task_links,
    _attach_project_names,
    _attach_task_progress,
    _calc_task_progress,
    normalize_priority_score,
    estimate_hours_to_priority_score_default,
)
from openvort.plugins.vortflow.router.schemas import (
    TaskCreate,
    TaskReorder,
    TaskUpdate,
    TransitionBody,
)
from openvort.plugins.vortflow.models import (
    FlowTask,
    FlowBug,
    FlowStory,
    FlowIterationTask,
    FlowWorkItemLink,
    FlowComment,
    FlowTestCaseWorkItem,
)
from openvort.plugins.vortflow.engine import (
    TASK_DONE_STATES,
    TASK_TRANSITIONS,
    TaskState,
)
from openvort.plugins.vortflow.notifier import notifier as _notifier, schedule_notification

sub_router = APIRouter()


# ============ Task CRUD + Transition ============

@sub_router.get("/tasks")
async def list_tasks(
    story_id: str = Query("", description="按需求过滤"),
    parent_id: str | None = Query(None, description="按父任务过滤，root 表示仅顶层任务"),
    state: str = Query("", description="按状态过滤"),
    task_type: str = Query("", description="按类型过滤"),
    assignee_id: str = Query("", description="按负责人过滤"),
    keyword: str = Query("", description="关键词搜索"),
    project_id: str = Query("", description="按项目过滤（通过关联需求，单个）"),
    project_ids: str = Query("", description="按项目过滤（逗号分隔多选，优先于 project_id）"),
    creator_id: str = Query("", description="按创建者过滤"),
    participant_id: str = Query(
        "",
        description=(
            "按参与者过滤；与「成员关注」卡片口径一致：负责人||协作者。"
            "**不含创建人**——若需按创建维度过滤，请使用 creator_id。"
        ),
    ),
    iteration_id: str = Query("", description="按迭代过滤"),
    archived: bool = Query(False, description="是否查看已归档"),
    include_archived: bool = Query(
        False,
        description="是否同时包含已归档（为 True 时忽略 archived，返回归档+未归档）",
    ),
    sort_by: str = Query("", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    sf = get_session_factory()
    async with sf() as session:
        if not sort_by:
            # 默认按手动排序键升序，与需求列表保持一致
            stmt = select(FlowTask).order_by(
                FlowTask.sort_order.asc().nulls_last(),
                FlowTask.created_at.desc(),
                FlowTask.id.desc(),
            )
        elif sort_by in ("priority", "priority_score"):
            stmt = select(FlowTask).order_by(
                FlowTask.priority_score.desc().nulls_last(),
                FlowTask.updated_at.desc(),
                FlowTask.id.desc(),
            )
        else:
            stmt = _apply_sort(
                select(FlowTask), FlowTask, sort_by, sort_order, FlowTask.priority_score
            )
        count_stmt = select(func.count()).select_from(FlowTask)
        # include_archived=True 时返回归档+未归档，不加归档过滤条件。
        if not include_archived:
            archived_cond = FlowTask.is_archived.is_(True) if archived else FlowTask.is_archived.is_not(True)
            stmt = stmt.where(archived_cond)
            count_stmt = count_stmt.where(archived_cond)
        if iteration_id == "__unplanned__":
            planned_ids = select(FlowIterationTask.task_id)
            stmt = stmt.where(~FlowTask.id.in_(planned_ids))
            count_stmt = count_stmt.where(~FlowTask.id.in_(planned_ids))
        elif iteration_id:
            iter_task_ids = select(FlowIterationTask.task_id).where(FlowIterationTask.iteration_id == iteration_id)
            stmt = stmt.where(FlowTask.id.in_(iter_task_ids))
            count_stmt = count_stmt.where(FlowTask.id.in_(iter_task_ids))
        pids = resolve_project_ids(project_id, project_ids)
        if pids:
            project_story_ids = select(FlowStory.id).where(FlowStory.project_id.in_(pids))
            project_cond = or_(
                FlowTask.project_id.in_(pids),
                FlowTask.story_id.in_(project_story_ids),
            )
            stmt = stmt.where(project_cond)
            count_stmt = count_stmt.where(project_cond)
        if story_id:
            stmt = stmt.where(FlowTask.story_id == story_id)
            count_stmt = count_stmt.where(FlowTask.story_id == story_id)
        if parent_id == "root":
            stmt = stmt.where(FlowTask.parent_id.is_(None))
            count_stmt = count_stmt.where(FlowTask.parent_id.is_(None))
        elif parent_id:
            stmt = stmt.where(FlowTask.parent_id == parent_id)
            count_stmt = count_stmt.where(FlowTask.parent_id == parent_id)
        if state:
            states = [s.strip() for s in state.split(",") if s.strip()]
            if len(states) == 1:
                stmt = stmt.where(FlowTask.state == states[0])
                count_stmt = count_stmt.where(FlowTask.state == states[0])
            elif states:
                stmt = stmt.where(FlowTask.state.in_(states))
                count_stmt = count_stmt.where(FlowTask.state.in_(states))
        if task_type:
            stmt = stmt.where(FlowTask.task_type == task_type)
            count_stmt = count_stmt.where(FlowTask.task_type == task_type)
        if assignee_id:
            stmt = stmt.where(FlowTask.assignee_id == assignee_id)
            count_stmt = count_stmt.where(FlowTask.assignee_id == assignee_id)
        if creator_id:
            stmt = stmt.where(FlowTask.creator_id == creator_id)
            count_stmt = count_stmt.where(FlowTask.creator_id == creator_id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(FlowTask.title.ilike(like))
            count_stmt = count_stmt.where(FlowTask.title.ilike(like))
        if participant_id:
            like_p = f'%"{participant_id}"%'
            participant_cond = or_(
                FlowTask.assignee_id == participant_id,
                FlowTask.collaborators_json.like(like_p),
            )
            stmt = stmt.where(participant_cond)
            count_stmt = count_stmt.where(participant_cond)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()
        task_ids = [row.id for row in rows]
        child_count_map: dict[str, int] = {}
        if task_ids:
            child_count_rows = await session.execute(
                select(FlowTask.parent_id, func.count())
                .where(FlowTask.parent_id.in_(task_ids))
                .group_by(FlowTask.parent_id)
            )
            child_count_map = {
                parent_task_id: child_count
                for parent_task_id, child_count in child_count_rows.all()
                if parent_task_id
            }
        items = [{**_task_dict(r), "children_count": child_count_map.get(r.id, 0)} for r in rows]
        await _attach_task_links(session, items)
        await _attach_task_progress(session, items)
        await _attach_project_names(session, items)
    return {
        "total": total,
        "items": items,
    }

@sub_router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    sf = get_session_factory()
    async with sf() as session:
        r = await session.get(FlowTask, task_id)
        if not r:
            raise HTTPException(status_code=404, detail="任务不存在")
        children_count = (await session.execute(
            select(func.count()).select_from(FlowTask).where(FlowTask.parent_id == task_id)
        )).scalar_one()
        item = {**_task_dict(r), "children_count": children_count}
        computed = await _calc_task_progress(session, task_id)
        if computed is not None:
            item["progress"] = computed
        items = await _attach_task_links(session, [item])
    return items[0]

@sub_router.post("/tasks")
async def create_task(body: TaskCreate, request: Request):
    payload = require_auth(request)
    member_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        resolved_story_id, normalized_parent_id, parent_error = await _resolve_task_story_and_parent(
            session,
            story_id=body.story_id,
            parent_id=body.parent_id,
        )
        if parent_error:
            raise HTTPException(status_code=400, detail=parent_error)
        project_id = body.project_id or None
        if not project_id and resolved_story_id:
            story = await session.get(FlowStory, resolved_story_id)
            if story:
                project_id = story.project_id
        if not project_id and normalized_parent_id:
            parent = await session.get(FlowTask, normalized_parent_id)
            if parent and parent.project_id:
                project_id = parent.project_id
        if body.priority_score is not None:
            init_score = normalize_priority_score(body.priority_score)
        else:
            init_score = estimate_hours_to_priority_score_default(body.estimate_hours)
        # sort_order 初值：同 (story_id, parent_id, project_id) 分组下当前最大值 +1024
        max_order_stmt = select(func.max(FlowTask.sort_order))
        if project_id:
            max_order_stmt = max_order_stmt.where(FlowTask.project_id == project_id)
        if resolved_story_id:
            max_order_stmt = max_order_stmt.where(FlowTask.story_id == resolved_story_id)
        else:
            max_order_stmt = max_order_stmt.where(FlowTask.story_id.is_(None))
        if normalized_parent_id:
            max_order_stmt = max_order_stmt.where(FlowTask.parent_id == normalized_parent_id)
        else:
            max_order_stmt = max_order_stmt.where(FlowTask.parent_id.is_(None))
        current_max = (await session.execute(max_order_stmt)).scalar()
        initial_sort_order = (float(current_max) if current_max is not None else 0.0) + 1024.0
        t = FlowTask(
            project_id=project_id,
            story_id=resolved_story_id, parent_id=normalized_parent_id,
            sort_order=initial_sort_order, title=body.title,
            description=body.description, task_type=body.task_type,
            assignee_id=body.assignee_id, creator_id=member_id or body.creator_id,
            priority_score=init_score,
            estimate_hours=body.estimate_hours,
            tags_json=json.dumps(body.tags or [], ensure_ascii=False),
            collaborators_json=json.dumps(body.collaborators or [], ensure_ascii=False),
            attachments_json=json.dumps(body.attachments or [], ensure_ascii=False),
            plan_start=_parse_dt(body.plan_start),
            deadline=_parse_dt(body.deadline),
            start_at=_parse_dt(body.start_at),
            end_at=_parse_dt(body.end_at),
            repo_id=body.repo_id or None,
            branch=body.branch or "",
        )
        session.add(t)
        await session.flush()
        await _log_event(
            session,
            "task",
            t.id,
            "created",
            {"title": body.title, "story_id": resolved_story_id, "parent_id": normalized_parent_id},
            actor_id=member_id,
        )
        await session.commit()
        await session.refresh(t)
    schedule_notification(_notifier.notify_item_created(
        "task", t.id, t.title, project_id or "", member_id,
        assignee_id=body.assignee_id,
        collaborator_ids=body.collaborators,
    ))
    return _task_dict(t)

@sub_router.put("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate, request: Request):
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        t = await session.get(FlowTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
        if getattr(t, "is_archived", False):
            raise HTTPException(status_code=409, detail="操作失败，当前工作项已归档！")
        old_assignee_id = t.assignee_id
        old_collaborators = _parse_json_list(t.collaborators_json)
        old_deadline = str(t.deadline) if t.deadline else None
        old_priority_score = getattr(t, "priority_score", None)
        changes = {}
        if body.project_id is not None:
            old_val = t.project_id
            t.project_id = body.project_id or None
            changes["project_id"] = {"from": old_val, "to": body.project_id}
        if body.priority_score is not None:
            new_score = normalize_priority_score(body.priority_score)
            if new_score != (old_priority_score or 0):
                changes["priority_score"] = {"from": old_priority_score, "to": new_score}
                t.priority_score = new_score
        # state 单独走状态机 helper：维护 start_at / end_at + 写 state_changed
        # 事件 + 后续 schedule notify。lenient 模式下不做 transition 表校验，
        # 与前端"状态下拉"行内编辑的跨段切换习惯保持兼容。
        state_change_old: str | None = None
        if body.state is not None and body.state != t.state:
            ok, error, _af, state_change_old = await _apply_state_change(
                session,
                kind="task",
                obj=t,
                new_state=body.state,
                actor_id=actor_id,
                strict=False,
            )
            if not ok:
                raise HTTPException(status_code=400, detail=error)
            changes["state"] = {"from": state_change_old, "to": body.state}
        for field in ["title", "description", "task_type", "assignee_id", "estimate_hours", "actual_hours"]:
            val = getattr(body, field)
            if val is not None:
                old_val = getattr(t, field)
                changes[field] = {"from": old_val, "to": val}
                setattr(t, field, val)
        if body.tags is not None:
            old_tags = _parse_json_list(t.tags_json)
            t.tags_json = json.dumps(body.tags, ensure_ascii=False)
            changes["tags"] = {"from": old_tags, "to": body.tags}
        if body.collaborators is not None:
            t.collaborators_json = json.dumps(body.collaborators, ensure_ascii=False)
            changes["collaborators"] = {"from": old_collaborators, "to": body.collaborators}
        if body.attachments is not None:
            old_attachments = _parse_json_list(t.attachments_json)
            t.attachments_json = json.dumps(body.attachments, ensure_ascii=False)
            changes["attachments"] = {"from": old_attachments, "to": body.attachments}
        if body.plan_start is not None:
            old_val = str(t.plan_start) if t.plan_start else None
            t.plan_start = _parse_dt(body.plan_start)
            changes["plan_start"] = {"from": old_val, "to": body.plan_start}
        if body.deadline is not None:
            t.deadline = _parse_dt(body.deadline)
            changes["deadline"] = {"from": old_deadline, "to": body.deadline}
        if body.start_at is not None:
            old_val = str(t.start_at) if t.start_at else None
            t.start_at = _parse_dt(body.start_at)
            changes["start_at"] = {"from": old_val, "to": body.start_at}
        if body.end_at is not None:
            old_val = str(t.end_at) if t.end_at else None
            t.end_at = _parse_dt(body.end_at)
            changes["end_at"] = {"from": old_val, "to": body.end_at}
        if body.repo_id is not None:
            old_val = t.repo_id
            t.repo_id = body.repo_id or None
            changes["repo_id"] = {"from": old_val, "to": body.repo_id}
        if body.branch is not None:
            old_val = t.branch
            t.branch = body.branch
            changes["branch"] = {"from": old_val, "to": body.branch}
        if body.progress is not None:
            old_val = t.progress
            t.progress = max(0, min(100, body.progress))
            changes["progress"] = {"from": old_val, "to": t.progress}
        if changes:
            await _log_event(session, "task", task_id, "updated", changes, actor_id=actor_id)
        await session.commit()
        await session.refresh(t)
        project_id = t.project_id or ""
        collaborators = _parse_json_list(t.collaborators_json)
    if state_change_old is not None and state_change_old != t.state:
        schedule_notification(_notifier.notify_state_change(
            "task", task_id, t.title, actor_id,
            state_change_old, t.state,
            assignee_id=t.assignee_id,
            collaborator_ids=collaborators,
            creator_id=t.creator_id,
            project_id=project_id,
        ))
    if body.assignee_id and body.assignee_id != old_assignee_id:
        schedule_notification(_notifier.notify_assignment(
            "task", task_id, t.title, actor_id, body.assignee_id,
            project_id=project_id,
        ))
    if body.collaborators is not None:
        new_ids = [c for c in body.collaborators if c not in old_collaborators]
        if new_ids:
            schedule_notification(_notifier.notify_collaborator_added(
                "task", task_id, t.title, project_id, actor_id, new_ids,
            ))
    field_changes: dict[str, tuple] = {}
    if "deadline" in changes and str(body.deadline) != old_deadline:
        field_changes["deadline"] = (old_deadline, body.deadline)
    if field_changes:
        schedule_notification(_notifier.notify_field_changes(
            "task", task_id, t.title, project_id, actor_id, field_changes,
            assignee_id=t.assignee_id, creator_id=t.creator_id,
            collaborator_ids=collaborators,
        ))
    return _task_dict(t)

@sub_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    sf = get_session_factory()
    async with sf() as session:
        t = await session.get(FlowTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
        child_task_ids = list(
            (await session.execute(select(FlowTask.id).where(FlowTask.parent_id == task_id))).scalars().all()
        )
        all_task_ids = [task_id, *child_task_ids]

        # clean up iteration associations
        await session.execute(sa_delete(FlowIterationTask).where(FlowIterationTask.task_id.in_(all_task_ids)))
        # nullify bug.task_id references
        await session.execute(
            FlowBug.__table__.update().where(FlowBug.task_id.in_(all_task_ids)).values(task_id=None)
        )
        # clean up work item links, comments, test case associations
        await session.execute(sa_delete(FlowWorkItemLink).where(
            or_(FlowWorkItemLink.source_id.in_(all_task_ids), FlowWorkItemLink.target_id.in_(all_task_ids))
        ))
        await session.execute(sa_delete(FlowComment).where(
            FlowComment.entity_type == "task", FlowComment.entity_id.in_(all_task_ids),
        ))
        await session.execute(sa_delete(FlowTestCaseWorkItem).where(
            FlowTestCaseWorkItem.entity_id.in_(all_task_ids),
        ))

        if child_task_ids:
            await session.execute(sa_delete(FlowTask).where(FlowTask.parent_id == task_id))
        await session.delete(t)
        await _log_event(
            session,
            "task",
            task_id,
            "deleted",
            {"title": t.title, "deleted_children": len(child_task_ids)},
        )
        await session.commit()
    return {"ok": True}

@sub_router.post("/tasks/{task_id}/reorder")
async def reorder_task(task_id: str, body: TaskReorder, request: Request):
    """拖拽排序：同 story 内调序、跨 story 移动、嵌入为另一任务的子任务。

    参数语义：
    - before_id: source 落到该任务之前（按 sort_order 升序 source < before）
    - after_id:  source 落到该任务之后
    - story_id:  显式指定所属需求（嵌入到需求下时）
    - parent_id: 显式指定父任务；null 表示顶层任务
    锚点优先级：anchor.story_id + anchor.parent_id > body 显式 > source 原值
    """
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        source = await session.get(FlowTask, task_id)
        if not source:
            raise HTTPException(status_code=404, detail="任务不存在")
        if getattr(source, "is_archived", False):
            raise HTTPException(status_code=409, detail="已归档的任务不能拖拽")

        before = None
        after = None
        if body.before_id:
            before = await session.get(FlowTask, body.before_id)
            if not before:
                raise HTTPException(status_code=400, detail="目标锚点不存在（before）")
            if before.id == task_id:
                raise HTTPException(status_code=400, detail="不能拖到自身")
        if body.after_id:
            after = await session.get(FlowTask, body.after_id)
            if not after:
                raise HTTPException(status_code=400, detail="目标锚点不存在（after）")
            if after.id == task_id:
                raise HTTPException(status_code=400, detail="不能拖到自身")

        for anchor in (before, after):
            if anchor is not None and anchor.project_id != source.project_id:
                raise HTTPException(status_code=400, detail="不能跨项目拖拽")

        anchor_for_ctx = before or after
        if anchor_for_ctx is not None:
            target_story_id_raw = anchor_for_ctx.story_id
            target_parent_id_raw = anchor_for_ctx.parent_id
        else:
            target_story_id_raw = body.story_id if body.story_id is not None else source.story_id
            target_parent_id_raw = body.parent_id if body.parent_id is not None else source.parent_id

        normalized_story_id, normalized_parent_id, err = await _resolve_task_story_and_parent(
            session,
            story_id=target_story_id_raw or None,
            parent_id=target_parent_id_raw or None,
        )
        if err:
            raise HTTPException(status_code=400, detail=err)
        if normalized_parent_id == task_id:
            raise HTTPException(status_code=400, detail="父任务不能是自身")

        STEP = 1024.0
        before_so = before.sort_order if before is not None else None
        after_so = after.sort_order if after is not None else None
        if before is not None and before_so is None:
            before_so = STEP
        if after is not None and after_so is None:
            after_so = 0.0

        if before is not None and after is not None:
            new_sort_order = (after_so + before_so) / 2.0
        elif before is not None:
            new_sort_order = before_so - STEP
        elif after is not None:
            new_sort_order = after_so + STEP
        else:
            max_order_stmt = select(func.max(FlowTask.sort_order)).where(
                FlowTask.project_id == source.project_id
            )
            if normalized_story_id is None:
                max_order_stmt = max_order_stmt.where(FlowTask.story_id.is_(None))
            else:
                max_order_stmt = max_order_stmt.where(FlowTask.story_id == normalized_story_id)
            if normalized_parent_id is None:
                max_order_stmt = max_order_stmt.where(FlowTask.parent_id.is_(None))
            else:
                max_order_stmt = max_order_stmt.where(FlowTask.parent_id == normalized_parent_id)
            current_max = (await session.execute(max_order_stmt)).scalar()
            new_sort_order = (float(current_max) if current_max is not None else 0.0) + STEP

        changes: dict = {}
        if normalized_story_id != source.story_id:
            changes["story_id"] = {"from": source.story_id, "to": normalized_story_id}
            source.story_id = normalized_story_id
        if normalized_parent_id != source.parent_id:
            changes["parent_id"] = {"from": source.parent_id, "to": normalized_parent_id}
            source.parent_id = normalized_parent_id
        if new_sort_order != source.sort_order:
            changes["sort_order"] = {"from": source.sort_order, "to": new_sort_order}
            source.sort_order = new_sort_order

        if changes:
            await _log_event(session, "task", task_id, "reordered", changes, actor_id=actor_id)
        await session.commit()
        await session.refresh(source)
    return _task_dict(source)


@sub_router.post("/tasks/{task_id}/transition")
async def transition_task(task_id: str, body: TransitionBody, request: Request):
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        t = await session.get(FlowTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
        if getattr(t, "is_archived", False):
            raise HTTPException(status_code=409, detail="操作失败，当前工作项已归档！")
        ok, error, _auto_fields, old_state = await _apply_state_change(
            session,
            kind="task",
            obj=t,
            new_state=body.target_state,
            actor_id=actor_id,
            strict=True,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=error)
        new_state = t.state
        collaborators = _parse_json_list(t.collaborators_json)
        await session.commit()
        await session.refresh(t)
    if new_state != old_state:
        schedule_notification(_notifier.notify_state_change(
            "task", task_id, t.title, actor_id,
            old_state, new_state,
            assignee_id=t.assignee_id,
            collaborator_ids=collaborators,
            creator_id=t.creator_id,
            project_id=t.project_id or "",
        ))
    return _task_dict(t)

@sub_router.post("/tasks/{task_id}/copy")
async def copy_task(task_id: str, request: Request):
    payload = require_auth(request)
    member_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        src = await session.get(FlowTask, task_id)
        if not src:
            raise HTTPException(status_code=404, detail="任务不存在")
        new_task = FlowTask(
            project_id=src.project_id,
            story_id=src.story_id,
            parent_id=src.parent_id,
            title=f"{src.title} (副本)",
            description=src.description,
            task_type=src.task_type,
            assignee_id=src.assignee_id,
            creator_id=member_id or src.creator_id,
            priority_score=getattr(src, "priority_score", None),
            estimate_hours=src.estimate_hours,
            tags_json=src.tags_json,
            collaborators_json=src.collaborators_json,
            attachments_json=src.attachments_json,
            deadline=src.deadline,
        )
        session.add(new_task)
        await session.flush()

        iter_row = (await session.execute(
            select(FlowIterationTask.iteration_id)
            .where(FlowIterationTask.task_id == task_id)
            .limit(1)
        )).scalar()
        if iter_row:
            session.add(FlowIterationTask(iteration_id=iter_row, task_id=new_task.id))

        await _log_event(session, "task", new_task.id, "created",
                         {"title": new_task.title, "copied_from": task_id}, actor_id=member_id)
        await session.commit()
        await session.refresh(new_task)
    return _task_dict(new_task)

@sub_router.get("/tasks/{task_id}/transitions")
async def get_task_transitions(task_id: str):
    sf = get_session_factory()
    async with sf() as session:
        t = await session.get(FlowTask, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")
    try:
        current = TaskState(t.state)
    except ValueError:
        return {"transitions": []}
    allowed = TASK_TRANSITIONS.get(current, [])
    return {"current": t.state, "transitions": [s.value for s in allowed]}
