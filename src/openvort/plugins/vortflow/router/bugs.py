import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import and_, delete, func, or_, select

from openvort.db.engine import get_session_factory
from openvort.web.app import require_auth
from openvort.plugins.vortflow.router.helpers import (
    _apply_state_change,
    _parse_dt,
    _bug_dict,
    _log_event,
    _apply_sort,
    _parse_json_list,
    resolve_project_ids,
    _attach_bug_links,
    _attach_project_names,
    normalize_priority_score,
    priority_score_range_for_level,
    score_to_priority_level,
    severity_to_priority_score,
)
from openvort.plugins.vortflow.router.schemas import (
    BugCreate,
    BugReorder,
    BugUpdate,
    TransitionBody,
)
from openvort.plugins.vortflow.models import (
    FlowBug,
    FlowStory,
    FlowTask,
    FlowIterationStory,
    FlowIterationBug,
    FlowVersionBug,
    FlowWorkItemLink,
    FlowComment,
    FlowTestCaseWorkItem,
)
from openvort.plugins.vortflow.engine import (
    BUG_CLOSED_STATES,
    BUG_TRANSITIONS,
    BugState,
)
from openvort.plugins.vortflow.notifier import notifier as _notifier, schedule_notification

sub_router = APIRouter()


# ============ Bug CRUD + Transition ============

@sub_router.get("/bugs")
async def list_bugs(
    story_id: str = Query("", description="按需求过滤"),
    state: str = Query("", description="按状态过滤"),
    severity: int = Query(0, description="按严重程度过滤"),
    assignee_id: str = Query("", description="按指派人过滤"),
    keyword: str = Query("", description="关键词搜索"),
    project_id: str = Query("", description="按项目过滤（通过关联需求，单个）"),
    project_ids: str = Query("", description="按项目过滤（逗号分隔多选，优先于 project_id）"),
    reporter_id: str = Query("", description="按报告者过滤"),
    participant_id: str = Query(
        "",
        description=(
            "按参与者过滤；与「成员关注」卡片口径完全一致（fallback 语义）："
            "负责人 OR (负责人为空 → 开发者) OR 协作者。"
            "**不含报告人**——若需按报告人过滤，请使用 reporter_id。"
        ),
    ),
    iteration_id: str = Query("", description="按迭代过滤（通过迭代关联的需求）"),
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
            # Bug tracking defaults to newest-first (created_at desc).
            # Unlike stories/tasks, bugs are almost never manually reordered;
            # sorting by sort_order asc pushed freshly reported bugs (largest
            # sort_order) to the last pages, burying them behind old suspended ones.
            stmt = select(FlowBug).order_by(
                FlowBug.created_at.desc(),
                FlowBug.id.desc(),
            )
        elif sort_by in ("priority", "priority_score"):
            stmt = select(FlowBug).order_by(
                FlowBug.priority_score.desc().nulls_last(),
                FlowBug.updated_at.desc(),
                FlowBug.id.desc(),
            )
        else:
            stmt = _apply_sort(
                select(FlowBug), FlowBug, sort_by, sort_order, FlowBug.priority_score
            )
        count_stmt = select(func.count()).select_from(FlowBug)
        # include_archived=True 时返回归档+未归档，不加归档过滤条件。
        if not include_archived:
            archived_cond = FlowBug.is_archived.is_(True) if archived else FlowBug.is_archived.is_not(True)
            stmt = stmt.where(archived_cond)
            count_stmt = count_stmt.where(archived_cond)
        if iteration_id == "__unplanned__":
            planned_story_ids = select(FlowIterationStory.story_id)
            planned_bug_ids = select(FlowIterationBug.bug_id)
            unplanned_cond = or_(
                FlowBug.story_id.is_(None),
                FlowBug.story_id == "",
                ~FlowBug.story_id.in_(planned_story_ids),
            )
            stmt = stmt.where(unplanned_cond, ~FlowBug.id.in_(planned_bug_ids))
            count_stmt = count_stmt.where(unplanned_cond, ~FlowBug.id.in_(planned_bug_ids))
        elif iteration_id:
            iter_story_ids = select(FlowIterationStory.story_id).where(FlowIterationStory.iteration_id == iteration_id)
            direct_bug_ids = select(FlowIterationBug.bug_id).where(FlowIterationBug.iteration_id == iteration_id)
            iter_cond = or_(
                FlowBug.story_id.in_(iter_story_ids),
                FlowBug.id.in_(direct_bug_ids),
            )
            stmt = stmt.where(iter_cond)
            count_stmt = count_stmt.where(iter_cond)
        pids = resolve_project_ids(project_id, project_ids)
        if pids:
            project_story_ids = select(FlowStory.id).where(FlowStory.project_id.in_(pids))
            project_cond = or_(
                FlowBug.project_id.in_(pids),
                FlowBug.story_id.in_(project_story_ids),
            )
            stmt = stmt.where(project_cond)
            count_stmt = count_stmt.where(project_cond)
        if story_id:
            stmt = stmt.where(FlowBug.story_id == story_id)
            count_stmt = count_stmt.where(FlowBug.story_id == story_id)
        if state:
            states = [s.strip() for s in state.split(",") if s.strip()]
            if len(states) == 1:
                stmt = stmt.where(FlowBug.state == states[0])
                count_stmt = count_stmt.where(FlowBug.state == states[0])
            elif states:
                stmt = stmt.where(FlowBug.state.in_(states))
                count_stmt = count_stmt.where(FlowBug.state.in_(states))
        if severity:
            smin, smax = priority_score_range_for_level(int(severity))
            sev_cond = or_(
                FlowBug.priority_score.between(smin, smax),
                (FlowBug.priority_score.is_(None)) & (FlowBug.severity == severity),
            )
            stmt = stmt.where(sev_cond)
            count_stmt = count_stmt.where(sev_cond)
        if assignee_id:
            # 前端"负责人"列显示 assignee_id || developer_id，此处按相同语义过滤：
            # 优先匹配 assignee_id；当 assignee_id 为空时回退匹配 developer_id。
            effective_owner_cond = or_(
                FlowBug.assignee_id == assignee_id,
                (FlowBug.assignee_id.is_(None)) & (FlowBug.developer_id == assignee_id),
            )
            stmt = stmt.where(effective_owner_cond)
            count_stmt = count_stmt.where(effective_owner_cond)
        if reporter_id:
            stmt = stmt.where(FlowBug.reporter_id == reporter_id)
            count_stmt = count_stmt.where(FlowBug.reporter_id == reporter_id)
        if participant_id:
            # fallback 语义：developer 仅在 assignee 为空时回退命中，与 /members/workload 对齐。
            like_p = f'%"{participant_id}"%'
            participant_cond = or_(
                FlowBug.assignee_id == participant_id,
                and_(
                    or_(FlowBug.assignee_id.is_(None), FlowBug.assignee_id == ""),
                    FlowBug.developer_id == participant_id,
                ),
                FlowBug.collaborators_json.like(like_p),
            )
            stmt = stmt.where(participant_cond)
            count_stmt = count_stmt.where(participant_cond)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(FlowBug.title.ilike(like))
            count_stmt = count_stmt.where(FlowBug.title.ilike(like))
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()
        items = [_bug_dict(r) for r in rows]
        await _attach_bug_links(session, items)
        await _attach_project_names(session, items)

    return {"total": total, "items": items}

@sub_router.get("/bugs/{bug_id}")
async def get_bug(bug_id: str):
    sf = get_session_factory()
    async with sf() as session:
        r = await session.get(FlowBug, bug_id)
        if not r:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        items = await _attach_bug_links(session, [_bug_dict(r)])
    return items[0]

@sub_router.post("/bugs")
async def create_bug(body: BugCreate, request: Request):
    payload = require_auth(request)
    member_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        project_id = body.project_id or None
        if not project_id and body.story_id:
            story = await session.get(FlowStory, body.story_id)
            if story:
                project_id = story.project_id
        if body.priority_score is not None:
            score = normalize_priority_score(body.priority_score)
            severity_val = score_to_priority_level(score) or body.severity
        else:
            severity_val = body.severity
            score = severity_to_priority_score(severity_val)
        # 历史上 developer_id 与 assignee_id 双轨；统一以 assignee_id 为权威，
        # 创建时若调用方未显式传 developer_id 则同步为 assignee_id，避免新数据继续分叉。
        owner_id = body.assignee_id or None
        developer_id = body.developer_id or owner_id
        # sort_order 初值：同 (story_id, task_id, project_id) 分组下当前最大值 +1024
        max_order_stmt = select(func.max(FlowBug.sort_order))
        if project_id:
            max_order_stmt = max_order_stmt.where(FlowBug.project_id == project_id)
        if body.story_id:
            max_order_stmt = max_order_stmt.where(FlowBug.story_id == body.story_id)
        else:
            max_order_stmt = max_order_stmt.where(FlowBug.story_id.is_(None))
        if body.task_id:
            max_order_stmt = max_order_stmt.where(FlowBug.task_id == body.task_id)
        else:
            max_order_stmt = max_order_stmt.where(FlowBug.task_id.is_(None))
        current_max = (await session.execute(max_order_stmt)).scalar()
        initial_sort_order = (float(current_max) if current_max is not None else 0.0) + 1024.0
        b = FlowBug(
            project_id=project_id,
            story_id=body.story_id, task_id=body.task_id,
            sort_order=initial_sort_order,
            title=body.title, description=body.description,
            severity=severity_val,
            priority_score=score,
            reporter_id=member_id or None,
            assignee_id=owner_id,
            developer_id=developer_id,
            plan_start=_parse_dt(body.plan_start) if body.plan_start else None,
            deadline=_parse_dt(body.deadline) if body.deadline else None,
            start_at=_parse_dt(body.start_at) if body.start_at else None,
            end_at=_parse_dt(body.end_at) if body.end_at else None,
            repo_id=body.repo_id or None,
            branch=body.branch or "",
            tags_json=json.dumps(body.tags or [], ensure_ascii=False),
            collaborators_json=json.dumps(body.collaborators or [], ensure_ascii=False),
            attachments_json=json.dumps(body.attachments or [], ensure_ascii=False),
        )
        session.add(b)
        await session.flush()
        await _log_event(session, "bug", b.id, "created", {"title": body.title}, actor_id=member_id)
        await session.commit()
        await session.refresh(b)
    schedule_notification(_notifier.notify_item_created(
        "bug", b.id, b.title, project_id or "", member_id,
        assignee_id=body.assignee_id,
        collaborator_ids=body.collaborators,
    ))
    return _bug_dict(b)

@sub_router.put("/bugs/{bug_id}")
async def update_bug(bug_id: str, body: BugUpdate, request: Request):
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        b = await session.get(FlowBug, bug_id)
        if not b:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        if getattr(b, "is_archived", False):
            raise HTTPException(status_code=409, detail="操作失败，当前工作项已归档！")
        old_assignee_id = b.assignee_id
        old_severity = b.severity
        old_priority_score = getattr(b, "priority_score", None)
        old_collaborators = _parse_json_list(b.collaborators_json)
        old_deadline = str(b.deadline) if b.deadline else None
        changes = {}
        if body.project_id is not None:
            old_val = b.project_id
            b.project_id = body.project_id or None
            changes["project_id"] = {"from": old_val, "to": body.project_id}
        if body.priority_score is not None:
            new_score = normalize_priority_score(body.priority_score)
            if new_score != (old_priority_score or 0):
                changes["priority_score"] = {"from": old_priority_score, "to": new_score}
                b.priority_score = new_score
            new_sev = score_to_priority_level(new_score)
            if new_sev not in (1, 2, 3, 4):
                new_sev = 4
            if body.severity is not None:
                new_sev = body.severity
            if new_sev != old_severity:
                changes["severity"] = {"from": old_severity, "to": new_sev}
                b.severity = new_sev
        elif body.severity is not None:
            new_sev = body.severity
            new_score = severity_to_priority_score(new_sev)
            if new_sev != old_severity:
                changes["severity"] = {"from": old_severity, "to": new_sev}
                b.severity = new_sev
            if new_score != (old_priority_score or 0):
                changes["priority_score"] = {"from": old_priority_score, "to": new_score}
                b.priority_score = new_score
        # state 单独走状态机 helper：维护 start_at / end_at + 写 state_changed
        # 事件 + 后续 schedule notify。lenient 模式下不做 transition 表校验，
        # 与前端"状态下拉"行内编辑的跨段切换习惯保持兼容。
        state_change_old: str | None = None
        if body.state is not None and body.state != b.state:
            ok, error, _af, state_change_old = await _apply_state_change(
                session,
                kind="bug",
                obj=b,
                new_state=body.state,
                actor_id=actor_id,
                strict=False,
            )
            if not ok:
                raise HTTPException(status_code=400, detail=error)
            changes["state"] = {"from": state_change_old, "to": body.state}
        for field in ["title", "description", "assignee_id", "developer_id", "estimate_hours", "actual_hours"]:
            val = getattr(body, field)
            if val is not None:
                old_val = getattr(b, field)
                changes[field] = {"from": old_val, "to": val}
                setattr(b, field, val)
        if body.tags is not None:
            old_tags = _parse_json_list(b.tags_json)
            b.tags_json = json.dumps(body.tags, ensure_ascii=False)
            changes["tags"] = {"from": old_tags, "to": body.tags}
        if body.collaborators is not None:
            b.collaborators_json = json.dumps(body.collaborators, ensure_ascii=False)
            changes["collaborators"] = {"from": old_collaborators, "to": body.collaborators}
        if body.attachments is not None:
            old_attachments = _parse_json_list(b.attachments_json)
            b.attachments_json = json.dumps(body.attachments, ensure_ascii=False)
            changes["attachments"] = {"from": old_attachments, "to": body.attachments}
        if body.plan_start is not None:
            old_val = str(b.plan_start) if b.plan_start else None
            b.plan_start = _parse_dt(body.plan_start)
            changes["plan_start"] = {"from": old_val, "to": body.plan_start}
        if body.deadline is not None:
            b.deadline = _parse_dt(body.deadline)
            changes["deadline"] = {"from": old_deadline, "to": body.deadline}
        if body.start_at is not None:
            old_val = str(b.start_at) if b.start_at else None
            b.start_at = _parse_dt(body.start_at)
            changes["start_at"] = {"from": old_val, "to": body.start_at}
        if body.end_at is not None:
            old_val = str(b.end_at) if b.end_at else None
            b.end_at = _parse_dt(body.end_at)
            changes["end_at"] = {"from": old_val, "to": body.end_at}
        if body.repo_id is not None:
            old_val = b.repo_id
            b.repo_id = body.repo_id or None
            changes["repo_id"] = {"from": old_val, "to": body.repo_id}
        if body.branch is not None:
            old_val = b.branch
            b.branch = body.branch
            changes["branch"] = {"from": old_val, "to": body.branch}
        if changes:
            await _log_event(session, "bug", bug_id, "updated", changes, actor_id=actor_id)
        await session.commit()
        await session.refresh(b)
        project_id = b.project_id or ""
        collaborators = _parse_json_list(b.collaborators_json)
    if state_change_old is not None and state_change_old != b.state:
        schedule_notification(_notifier.notify_state_change(
            "bug", bug_id, b.title, actor_id,
            state_change_old, b.state,
            assignee_id=b.assignee_id,
            collaborator_ids=collaborators,
            creator_id=b.reporter_id,
            project_id=project_id,
        ))
    if body.assignee_id and body.assignee_id != old_assignee_id:
        schedule_notification(_notifier.notify_assignment(
            "bug", bug_id, b.title, actor_id, body.assignee_id,
            project_id=project_id,
        ))
    if body.collaborators is not None:
        new_ids = [c for c in body.collaborators if c not in old_collaborators]
        if new_ids:
            schedule_notification(_notifier.notify_collaborator_added(
                "bug", bug_id, b.title, project_id, actor_id, new_ids,
            ))
    field_changes: dict[str, tuple] = {}
    sev_change = changes.get("severity")
    if sev_change and sev_change.get("from") != sev_change.get("to"):
        field_changes["severity"] = (sev_change["from"], sev_change["to"])
    if "deadline" in changes and str(body.deadline) != old_deadline:
        field_changes["deadline"] = (old_deadline, body.deadline)
    if field_changes:
        schedule_notification(_notifier.notify_field_changes(
            "bug", bug_id, b.title, project_id, actor_id, field_changes,
            assignee_id=b.assignee_id, creator_id=b.reporter_id,
            collaborator_ids=collaborators,
        ))
    return _bug_dict(b)

@sub_router.delete("/bugs/{bug_id}")
async def delete_bug(bug_id: str):
    sf = get_session_factory()
    async with sf() as session:
        b = await session.get(FlowBug, bug_id)
        if not b:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        await session.execute(delete(FlowIterationBug).where(FlowIterationBug.bug_id == bug_id))
        await session.execute(delete(FlowVersionBug).where(FlowVersionBug.bug_id == bug_id))
        # clean up work item links, comments, test case associations
        await session.execute(delete(FlowWorkItemLink).where(
            or_(FlowWorkItemLink.source_id == bug_id, FlowWorkItemLink.target_id == bug_id)
        ))
        await session.execute(delete(FlowComment).where(
            FlowComment.entity_type == "bug", FlowComment.entity_id == bug_id,
        ))
        await session.execute(delete(FlowTestCaseWorkItem).where(
            FlowTestCaseWorkItem.entity_id == bug_id,
        ))
        await session.delete(b)
        await _log_event(session, "bug", bug_id, "deleted", {"title": b.title})
        await session.commit()
    return {"ok": True}

@sub_router.post("/bugs/{bug_id}/reorder")
async def reorder_bug(bug_id: str, body: BugReorder, request: Request):
    """拖拽排序：缺陷在同分组（story_id, task_id）内调序，或跨需求/任务移动。

    参数：
    - before_id / after_id: 锚点缺陷
    - story_id / task_id:   显式指定挂载点（嵌入到需求或任务下）
    锚点优先级：anchor.story_id + anchor.task_id > body 显式 > source 原值
    """
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        source = await session.get(FlowBug, bug_id)
        if not source:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        if getattr(source, "is_archived", False):
            raise HTTPException(status_code=409, detail="已归档的缺陷不能拖拽")

        before = None
        after = None
        if body.before_id:
            before = await session.get(FlowBug, body.before_id)
            if not before:
                raise HTTPException(status_code=400, detail="目标锚点不存在（before）")
            if before.id == bug_id:
                raise HTTPException(status_code=400, detail="不能拖到自身")
        if body.after_id:
            after = await session.get(FlowBug, body.after_id)
            if not after:
                raise HTTPException(status_code=400, detail="目标锚点不存在（after）")
            if after.id == bug_id:
                raise HTTPException(status_code=400, detail="不能拖到自身")

        for anchor in (before, after):
            if anchor is not None and anchor.project_id != source.project_id:
                raise HTTPException(status_code=400, detail="不能跨项目拖拽")

        anchor_for_ctx = before or after
        if anchor_for_ctx is not None:
            target_story_id_raw = anchor_for_ctx.story_id
            target_task_id_raw = anchor_for_ctx.task_id
        else:
            target_story_id_raw = body.story_id if body.story_id is not None else source.story_id
            target_task_id_raw = body.task_id if body.task_id is not None else source.task_id

        normalized_story_id = (target_story_id_raw or "").strip() or None
        normalized_task_id = (target_task_id_raw or "").strip() or None

        # 校验 story_id 存在且同项目
        if normalized_story_id:
            story = await session.get(FlowStory, normalized_story_id)
            if not story:
                raise HTTPException(status_code=400, detail="关联需求不存在")
            if story.project_id != source.project_id:
                raise HTTPException(status_code=400, detail="缺陷不能跨项目")
        # 校验 task_id 存在 + task.story_id 一致
        if normalized_task_id:
            task = await session.get(FlowTask, normalized_task_id)
            if not task:
                raise HTTPException(status_code=400, detail="关联任务不存在")
            if task.project_id != source.project_id:
                raise HTTPException(status_code=400, detail="缺陷不能跨项目")
            # 任务的 story_id 必须与缺陷的 story_id 一致
            if normalized_story_id and task.story_id and normalized_story_id != task.story_id:
                raise HTTPException(status_code=400, detail="缺陷与所属任务必须属于同一个需求")
            normalized_story_id = normalized_story_id or task.story_id

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
            max_order_stmt = select(func.max(FlowBug.sort_order)).where(
                FlowBug.project_id == source.project_id
            )
            if normalized_story_id is None:
                max_order_stmt = max_order_stmt.where(FlowBug.story_id.is_(None))
            else:
                max_order_stmt = max_order_stmt.where(FlowBug.story_id == normalized_story_id)
            if normalized_task_id is None:
                max_order_stmt = max_order_stmt.where(FlowBug.task_id.is_(None))
            else:
                max_order_stmt = max_order_stmt.where(FlowBug.task_id == normalized_task_id)
            current_max = (await session.execute(max_order_stmt)).scalar()
            new_sort_order = (float(current_max) if current_max is not None else 0.0) + STEP

        changes: dict = {}
        if normalized_story_id != source.story_id:
            changes["story_id"] = {"from": source.story_id, "to": normalized_story_id}
            source.story_id = normalized_story_id
        if normalized_task_id != source.task_id:
            changes["task_id"] = {"from": source.task_id, "to": normalized_task_id}
            source.task_id = normalized_task_id
        if new_sort_order != source.sort_order:
            changes["sort_order"] = {"from": source.sort_order, "to": new_sort_order}
            source.sort_order = new_sort_order

        if changes:
            await _log_event(session, "bug", bug_id, "reordered", changes, actor_id=actor_id)
        await session.commit()
        await session.refresh(source)
    return _bug_dict(source)


@sub_router.post("/bugs/{bug_id}/transition")
async def transition_bug(bug_id: str, body: TransitionBody, request: Request):
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        b = await session.get(FlowBug, bug_id)
        if not b:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        if getattr(b, "is_archived", False):
            raise HTTPException(status_code=409, detail="操作失败，当前工作项已归档！")
        ok, error, _auto_fields, old_state = await _apply_state_change(
            session,
            kind="bug",
            obj=b,
            new_state=body.target_state,
            actor_id=actor_id,
            strict=True,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=error)
        new_state = b.state
        collaborators = _parse_json_list(b.collaborators_json)
        await session.commit()
        await session.refresh(b)
    if new_state != old_state:
        schedule_notification(_notifier.notify_state_change(
            "bug", bug_id, b.title, actor_id,
            old_state, new_state,
            assignee_id=b.assignee_id,
            collaborator_ids=collaborators,
            creator_id=b.reporter_id,
            project_id=b.project_id or "",
        ))
    return _bug_dict(b)

@sub_router.post("/bugs/{bug_id}/copy")
async def copy_bug(bug_id: str, request: Request):
    payload = require_auth(request)
    member_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        src = await session.get(FlowBug, bug_id)
        if not src:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        new_bug = FlowBug(
            project_id=src.project_id,
            story_id=src.story_id,
            task_id=src.task_id,
            title=f"{src.title} (副本)",
            description=src.description,
            severity=src.severity,
            priority_score=getattr(src, "priority_score", None),
            assignee_id=src.assignee_id,
            developer_id=src.developer_id,
            reporter_id=member_id or None,
            tags_json=src.tags_json,
            collaborators_json=src.collaborators_json,
            attachments_json=src.attachments_json,
            plan_start=src.plan_start,
            deadline=src.deadline,
        )
        session.add(new_bug)
        await session.flush()

        iter_row = (await session.execute(
            select(FlowIterationBug.iteration_id)
            .where(FlowIterationBug.bug_id == bug_id)
            .limit(1)
        )).scalar()
        if iter_row:
            session.add(FlowIterationBug(iteration_id=iter_row, bug_id=new_bug.id))

        await _log_event(session, "bug", new_bug.id, "created",
                         {"title": new_bug.title, "copied_from": bug_id}, actor_id=member_id)
        await session.commit()
        await session.refresh(new_bug)
    return _bug_dict(new_bug)

@sub_router.get("/bugs/{bug_id}/transitions")
async def get_bug_transitions(bug_id: str):
    sf = get_session_factory()
    async with sf() as session:
        b = await session.get(FlowBug, bug_id)
        if not b:
            raise HTTPException(status_code=404, detail="缺陷不存在")
    try:
        current = BugState(b.state)
    except ValueError:
        return {"transitions": []}
    allowed = BUG_TRANSITIONS.get(current, [])
    return {"current": b.state, "transitions": [s.value for s in allowed]}
