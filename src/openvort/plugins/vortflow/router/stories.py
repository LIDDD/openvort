import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import and_, func, select, delete as sa_delete, update as sa_update, or_

from openvort.db.engine import get_session_factory
from openvort.web.app import require_auth
from openvort.plugins.vortflow.router.helpers import (
    _apply_state_change,
    _parse_dt,
    _story_dict,
    _log_event,
    _apply_sort,
    _parse_json_list,
    resolve_project_ids,
    _validate_story_parent,
    _collect_story_descendant_ids,
    _attach_story_links,
    _attach_project_names,
    priority_level_to_default_score,
    priority_score_range_for_level,
    normalize_priority_score,
    score_to_priority_level,
)
from openvort.plugins.vortflow.router.schemas import (
    StoryCreate,
    StoryReorder,
    StoryUpdate,
    TransitionBody,
)
from openvort.plugins.vortflow.models import (
    FlowStory,
    FlowTask,
    FlowBug,
    FlowIterationStory,
    FlowIterationTask,
    FlowIterationBug,
    FlowVersionStory,
    FlowVersionBug,
    FlowWorkItemLink,
    FlowComment,
    FlowTestCaseWorkItem,
)
from openvort.plugins.vortflow.engine import (
    STORY_DONE_STATES,
    STORY_TRANSITIONS,
    StoryState,
)
from openvort.plugins.vortflow.notifier import notifier as _notifier, schedule_notification

sub_router = APIRouter()


# ============ Story CRUD + Transition ============

@sub_router.get("/stories")
async def list_stories(
    project_id: str = Query("", description="按项目过滤（单个）"),
    project_ids: str = Query("", description="按项目过滤（逗号分隔多选，优先于 project_id）"),
    state: str = Query("", description="按状态过滤"),
    keyword: str = Query("", description="关键词搜索"),
    priority: int = Query(0, description="按优先级过滤"),
    parent_id: str | None = Query(None, description="按父需求过滤，root 表示仅顶层需求"),
    submitter_id: str = Query("", description="按创建者过滤"),
    assignee_id: str = Query("", description="按负责人过滤"),
    pm_id: str = Query("", description="按产品经理过滤"),
    participant_id: str = Query(
        "",
        description=(
            "按参与者过滤；与「成员关注」卡片口径完全一致（fallback 语义）："
            "负责人 OR (负责人为空 → 产品经理) OR 协作者。"
            "**不含创建人**——若需按创建维度过滤，请使用 submitter_id。"
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
    page_size: int = Query(20, ge=1, le=200),
):
    sf = get_session_factory()
    async with sf() as session:
        # 默认按 sort_order 升序（手动排序）；NULL 落到末尾，再按创建时间倒序兜底。
        # 用户主动选择 priority/priority_score 时统一按 priority_score DESC + updated_at DESC。
        # 老前端传 sort_by=priority + sort_order=asc 也强制走 priority_score 路径，避免反向。
        if not sort_by:
            stmt = select(FlowStory).order_by(
                FlowStory.sort_order.asc().nulls_last(),
                FlowStory.created_at.desc(),
                FlowStory.id.desc(),
            )
        elif sort_by in ("priority", "priority_score"):
            stmt = select(FlowStory).order_by(
                FlowStory.priority_score.desc().nulls_last(),
                FlowStory.updated_at.desc(),
                FlowStory.id.desc(),
            )
        else:
            stmt = _apply_sort(
                select(FlowStory), FlowStory, sort_by, sort_order, FlowStory.priority_score
            )
        count_stmt = select(func.count()).select_from(FlowStory)
        # include_archived=True 时返回归档+未归档，不加归档过滤条件。
        if not include_archived:
            archived_cond = FlowStory.is_archived.is_(True) if archived else FlowStory.is_archived.is_not(True)
            stmt = stmt.where(archived_cond)
            count_stmt = count_stmt.where(archived_cond)
        if iteration_id == "__unplanned__":
            planned_ids = select(FlowIterationStory.story_id)
            stmt = stmt.where(~FlowStory.id.in_(planned_ids))
            count_stmt = count_stmt.where(~FlowStory.id.in_(planned_ids))
        elif iteration_id:
            iter_story_ids = select(FlowIterationStory.story_id).where(FlowIterationStory.iteration_id == iteration_id)
            stmt = stmt.where(FlowStory.id.in_(iter_story_ids))
            count_stmt = count_stmt.where(FlowStory.id.in_(iter_story_ids))
        pids = resolve_project_ids(project_id, project_ids)
        if pids:
            proj_cond = FlowStory.project_id.in_(pids)
            stmt = stmt.where(proj_cond)
            count_stmt = count_stmt.where(proj_cond)
        if state:
            states = [s.strip() for s in state.split(",") if s.strip()]
            if len(states) == 1:
                stmt = stmt.where(FlowStory.state == states[0])
                count_stmt = count_stmt.where(FlowStory.state == states[0])
            elif states:
                stmt = stmt.where(FlowStory.state.in_(states))
                count_stmt = count_stmt.where(FlowStory.state.in_(states))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(FlowStory.title.ilike(like))
            count_stmt = count_stmt.where(FlowStory.title.ilike(like))
        if priority:
            # 按等级过滤时翻译为对应 score 区间，兼容历史数据（priority_score 可能为 NULL）。
            score_min, score_max = priority_score_range_for_level(int(priority))
            level_cond = or_(
                FlowStory.priority_score.between(score_min, score_max),
                (FlowStory.priority_score.is_(None)) & (FlowStory.priority == priority),
            )
            stmt = stmt.where(level_cond)
            count_stmt = count_stmt.where(level_cond)
        if parent_id == "root":
            stmt = stmt.where(FlowStory.parent_id.is_(None))
            count_stmt = count_stmt.where(FlowStory.parent_id.is_(None))
        elif parent_id:
            stmt = stmt.where(FlowStory.parent_id == parent_id)
            count_stmt = count_stmt.where(FlowStory.parent_id == parent_id)
        if submitter_id:
            stmt = stmt.where(FlowStory.submitter_id == submitter_id)
            count_stmt = count_stmt.where(FlowStory.submitter_id == submitter_id)
        if assignee_id:
            # 前端"负责人"列显示 assignee_id || pm_id，此处按相同语义过滤：
            # 优先匹配 assignee_id；当 assignee_id 为空时回退匹配 pm_id。
            effective_owner_cond = or_(
                FlowStory.assignee_id == assignee_id,
                (FlowStory.assignee_id.is_(None)) & (FlowStory.pm_id == assignee_id),
            )
            stmt = stmt.where(effective_owner_cond)
            count_stmt = count_stmt.where(effective_owner_cond)
        if pm_id:
            stmt = stmt.where(FlowStory.pm_id == pm_id)
            count_stmt = count_stmt.where(FlowStory.pm_id == pm_id)
        if participant_id:
            # fallback 语义：pm 仅在 assignee 为空时回退命中，与 /members/workload 对齐。
            like_p = f'%"{participant_id}"%'
            participant_cond = or_(
                FlowStory.assignee_id == participant_id,
                and_(
                    or_(FlowStory.assignee_id.is_(None), FlowStory.assignee_id == ""),
                    FlowStory.pm_id == participant_id,
                ),
                FlowStory.collaborators_json.like(like_p),
            )
            stmt = stmt.where(participant_cond)
            count_stmt = count_stmt.where(participant_cond)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()
        story_ids = [row.id for row in rows]
        child_count_map: dict[str, int] = {}
        task_count_map: dict[str, int] = {}
        if story_ids:
            child_count_rows = await session.execute(
                select(FlowStory.parent_id, func.count())
                .where(FlowStory.parent_id.in_(story_ids))
                .group_by(FlowStory.parent_id)
            )
            child_count_map = {
                parent_story_id: child_count
                for parent_story_id, child_count in child_count_rows.all()
                if parent_story_id
            }
            task_count_rows = await session.execute(
                select(FlowTask.story_id, func.count())
                .where(FlowTask.story_id.in_(story_ids))
                .group_by(FlowTask.story_id)
            )
            task_count_map = {
                sid: cnt for sid, cnt in task_count_rows.all() if sid
            }
        items = [{
            **_story_dict(r),
            "children_count": child_count_map.get(r.id, 0),
            "task_count": task_count_map.get(r.id, 0),
        } for r in rows]
        await _attach_story_links(session, items)
        await _attach_project_names(session, items)
    return {
        "total": total,
        "items": items,
    }

@sub_router.get("/stories/{story_id}")
async def get_story(story_id: str):
    sf = get_session_factory()
    async with sf() as session:
        r = await session.get(FlowStory, story_id)
        if not r:
            raise HTTPException(status_code=404, detail="需求不存在")
        task_count = (await session.execute(
            select(func.count()).select_from(FlowTask).where(FlowTask.story_id == story_id)
        )).scalar_one()
        bug_count = (await session.execute(
            select(func.count()).select_from(FlowBug).where(FlowBug.story_id == story_id)
        )).scalar_one()
        children_count = (await session.execute(
            select(func.count()).select_from(FlowStory).where(FlowStory.parent_id == story_id)
        )).scalar_one()
        item = {
            **_story_dict(r),
            "task_count": task_count,
            "bug_count": bug_count,
            "children_count": children_count,
        }
        items = await _attach_story_links(session, [item])
    return items[0]

@sub_router.post("/stories")
async def create_story(body: StoryCreate, request: Request):
    payload = require_auth(request)
    member_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        normalized_parent_id, parent_error = await _validate_story_parent(
            session,
            project_id=body.project_id,
            parent_id=body.parent_id,
        )
        if parent_error:
            raise HTTPException(status_code=400, detail=parent_error)
        # priority_score 优先；没传则按 priority 等级派生段起始值（紧急 80 / 高 60 / 中 40 / 低 20）。
        if body.priority_score is not None:
            score = normalize_priority_score(body.priority_score)
            level = score_to_priority_level(score) or body.priority
        else:
            level = body.priority
            score = priority_level_to_default_score(level)
        # sort_order 初值：同 parent + 同 project 下最大 sort_order + 1024（默认插到列表末尾）。
        # 步长 1024 让后续 fractional ranking 有足够空间。
        max_order_stmt = select(func.max(FlowStory.sort_order)).where(
            FlowStory.project_id == body.project_id
        )
        if normalized_parent_id is None:
            max_order_stmt = max_order_stmt.where(FlowStory.parent_id.is_(None))
        else:
            max_order_stmt = max_order_stmt.where(FlowStory.parent_id == normalized_parent_id)
        current_max = (await session.execute(max_order_stmt)).scalar()
        initial_sort_order = (float(current_max) if current_max is not None else 0.0) + 1024.0
        s = FlowStory(
            project_id=body.project_id, title=body.title,
            description=body.description, priority=level,
            priority_score=score,
            parent_id=normalized_parent_id,
            sort_order=initial_sort_order,
            submitter_id=member_id or None,
            assignee_id=body.assignee_id or None,
            tags_json=json.dumps(body.tags or [], ensure_ascii=False),
            collaborators_json=json.dumps(body.collaborators or [], ensure_ascii=False),
            attachments_json=json.dumps(body.attachments or [], ensure_ascii=False),
            plan_start=_parse_dt(body.plan_start),
            deadline=_parse_dt(body.deadline),
            start_at=_parse_dt(body.start_at),
            end_at=_parse_dt(body.end_at),
            test_time=_parse_dt(body.test_time),
            draft_time=_parse_dt(body.draft_time),
            release_time=_parse_dt(body.release_time),
            repo_id=body.repo_id or None,
            branch=body.branch or "",
        )
        session.add(s)
        await session.flush()
        await _log_event(
            session,
            "story",
            s.id,
            "created",
            {"title": body.title, "parent_id": normalized_parent_id},
            actor_id=member_id,
        )
        await session.commit()
        await session.refresh(s)
    schedule_notification(_notifier.notify_item_created(
        "story", s.id, s.title, s.project_id, member_id,
        assignee_id=body.assignee_id,
        collaborator_ids=body.collaborators,
    ))
    return _story_dict(s)

@sub_router.put("/stories/{story_id}")
async def update_story(story_id: str, body: StoryUpdate, request: Request):
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        s = await session.get(FlowStory, story_id)
        if not s:
            raise HTTPException(status_code=404, detail="需求不存在")
        if getattr(s, "is_archived", False):
            raise HTTPException(status_code=409, detail="操作失败，当前工作项已归档！")
        old_pm_id = s.pm_id
        old_assignee_id = getattr(s, "assignee_id", None)
        old_priority = s.priority
        old_priority_score = getattr(s, "priority_score", None)
        old_collaborators = _parse_json_list(s.collaborators_json)
        old_deadline = str(s.deadline) if s.deadline else None
        changes = {}
        if body.parent_id is not None:
            normalized_parent_id, parent_error = await _validate_story_parent(
                session,
                project_id=s.project_id,
                parent_id=body.parent_id,
                story_id=story_id,
            )
            if parent_error:
                raise HTTPException(status_code=400, detail=parent_error)
            old_val = s.parent_id
            changes["parent_id"] = {"from": old_val, "to": normalized_parent_id}
            s.parent_id = normalized_parent_id
        # priority_score 与 priority 联动：
        # - 同时传：以 priority_score 为准，priority 派生为对应等级
        # - 仅传 priority_score：派生 priority 等级
        # - 仅传 priority：score 重置为该等级的段起始值
        if body.priority_score is not None:
            new_score = normalize_priority_score(body.priority_score)
            if new_score != (old_priority_score or 0):
                changes["priority_score"] = {"from": old_priority_score, "to": new_score}
                s.priority_score = new_score
            new_level = score_to_priority_level(new_score)
            if body.priority is not None:
                new_level = body.priority
            if new_level != old_priority:
                changes["priority"] = {"from": old_priority, "to": new_level}
                s.priority = new_level
        elif body.priority is not None:
            new_level = body.priority
            new_score = priority_level_to_default_score(new_level)
            if new_level != old_priority:
                changes["priority"] = {"from": old_priority, "to": new_level}
                s.priority = new_level
            if new_score != (old_priority_score or 0):
                changes["priority_score"] = {"from": old_priority_score, "to": new_score}
                s.priority_score = new_score

        # state 单独走状态机 helper：维护 start_at / end_at + 写 state_changed
        # 事件 + 后续 schedule notify。lenient=True 允许跨段切换（前端工作墙
        # 状态下拉常常不沿 STORY_TRANSITIONS 顺序），但所有副作用一致。
        state_change_old: str | None = None
        if body.state is not None and body.state != s.state:
            ok, error, _af, state_change_old = await _apply_state_change(
                session,
                kind="story",
                obj=s,
                new_state=body.state,
                actor_id=actor_id,
                strict=False,
            )
            if not ok:
                raise HTTPException(status_code=400, detail=error)
            changes["state"] = {"from": state_change_old, "to": body.state}
        for field in ["title", "description", "assignee_id", "pm_id", "project_id"]:
            val = getattr(body, field)
            if val is not None:
                old_val = getattr(s, field)
                changes[field] = {"from": old_val, "to": val}
                setattr(s, field, val)
        if body.tags is not None:
            old_tags = _parse_json_list(s.tags_json)
            s.tags_json = json.dumps(body.tags, ensure_ascii=False)
            changes["tags"] = {"from": old_tags, "to": body.tags}
        if body.collaborators is not None:
            s.collaborators_json = json.dumps(body.collaborators, ensure_ascii=False)
            changes["collaborators"] = {"from": old_collaborators, "to": body.collaborators}
        if body.attachments is not None:
            old_attachments = _parse_json_list(s.attachments_json)
            s.attachments_json = json.dumps(body.attachments, ensure_ascii=False)
            changes["attachments"] = {"from": old_attachments, "to": body.attachments}
        if body.plan_start is not None:
            old_val = str(s.plan_start) if s.plan_start else None
            s.plan_start = _parse_dt(body.plan_start)
            changes["plan_start"] = {"from": old_val, "to": body.plan_start}
        if body.deadline is not None:
            s.deadline = _parse_dt(body.deadline)
            changes["deadline"] = {"from": old_deadline, "to": body.deadline}
        if body.start_at is not None:
            old_val = str(s.start_at) if s.start_at else None
            s.start_at = _parse_dt(body.start_at)
            changes["start_at"] = {"from": old_val, "to": body.start_at}
        if body.end_at is not None:
            old_val = str(s.end_at) if s.end_at else None
            s.end_at = _parse_dt(body.end_at)
            changes["end_at"] = {"from": old_val, "to": body.end_at}
        if body.test_time is not None:
            old_val = str(s.test_time) if s.test_time else None
            s.test_time = _parse_dt(body.test_time)
            changes["test_time"] = {"from": old_val, "to": body.test_time}
        if body.draft_time is not None:
            old_val = str(s.draft_time) if s.draft_time else None
            s.draft_time = _parse_dt(body.draft_time)
            changes["draft_time"] = {"from": old_val, "to": body.draft_time}
        if body.release_time is not None:
            old_val = str(s.release_time) if s.release_time else None
            s.release_time = _parse_dt(body.release_time)
            changes["release_time"] = {"from": old_val, "to": body.release_time}
        if body.repo_id is not None:
            old_val = s.repo_id
            s.repo_id = body.repo_id or None
            changes["repo_id"] = {"from": old_val, "to": body.repo_id}
        if body.branch is not None:
            old_val = s.branch
            s.branch = body.branch
            changes["branch"] = {"from": old_val, "to": body.branch}
        if body.progress is not None:
            old_val = s.progress
            s.progress = max(0, min(100, body.progress))
            changes["progress"] = {"from": old_val, "to": s.progress}
        if changes:
            await _log_event(session, "story", story_id, "updated", changes, actor_id=actor_id)
        await session.commit()
        await session.refresh(s)
        project_id = s.project_id or ""
        collaborators = _parse_json_list(s.collaborators_json)
    if state_change_old is not None and state_change_old != s.state:
        schedule_notification(_notifier.notify_state_change(
            "story", story_id, s.title, actor_id,
            state_change_old, s.state,
            assignee_id=getattr(s, "assignee_id", None) or s.pm_id,
            collaborator_ids=collaborators,
            creator_id=s.submitter_id,
            project_id=project_id,
        ))
    if body.assignee_id and body.assignee_id != old_assignee_id:
        schedule_notification(_notifier.notify_assignment(
            "story", story_id, s.title, actor_id, body.assignee_id,
            project_id=project_id,
        ))
    if body.pm_id and body.pm_id != old_pm_id:
        schedule_notification(_notifier.notify_assignment(
            "story", story_id, s.title, actor_id, body.pm_id,
            project_id=project_id,
        ))
    if body.collaborators is not None:
        new_ids = [c for c in body.collaborators if c not in old_collaborators]
        if new_ids:
            schedule_notification(_notifier.notify_collaborator_added(
                "story", story_id, s.title, project_id, actor_id, new_ids,
            ))
    field_changes: dict[str, tuple] = {}
    # 只有 priority 等级真正变化才触发通知；同等级内 score 变化（精排）不发通知。
    priority_change = changes.get("priority")
    if priority_change and priority_change.get("from") != priority_change.get("to"):
        field_changes["priority"] = (priority_change["from"], priority_change["to"])
    if "deadline" in changes and str(body.deadline) != old_deadline:
        field_changes["deadline"] = (old_deadline, body.deadline)
    if field_changes:
        schedule_notification(_notifier.notify_field_changes(
            "story", story_id, s.title, project_id, actor_id, field_changes,
            assignee_id=getattr(s, "assignee_id", None) or s.pm_id,
            creator_id=s.submitter_id,
            collaborator_ids=collaborators,
        ))
    return _story_dict(s)

@sub_router.delete("/stories/{story_id}")
async def delete_story(story_id: str):
    sf = get_session_factory()
    async with sf() as session:
        s = await session.get(FlowStory, story_id)
        if not s:
            raise HTTPException(status_code=404, detail="需求不存在")
        descendant_ids = await _collect_story_descendant_ids(session, [story_id])
        target_story_ids = [story_id, *descendant_ids]

        # collect task/bug ids under these stories
        task_ids = list(
            (await session.execute(select(FlowTask.id).where(FlowTask.story_id.in_(target_story_ids)))).scalars().all()
        )
        bug_ids = list(
            (await session.execute(select(FlowBug.id).where(FlowBug.story_id.in_(target_story_ids)))).scalars().all()
        )

        # clean up story associations
        await session.execute(sa_delete(FlowIterationStory).where(FlowIterationStory.story_id.in_(target_story_ids)))
        await session.execute(sa_delete(FlowVersionStory).where(FlowVersionStory.story_id.in_(target_story_ids)))

        # clean up task associations before deleting tasks
        if task_ids:
            await session.execute(sa_delete(FlowIterationTask).where(FlowIterationTask.task_id.in_(task_ids)))

        # clean up bug associations before deleting bugs
        if bug_ids:
            await session.execute(sa_delete(FlowIterationBug).where(FlowIterationBug.bug_id.in_(bug_ids)))
            await session.execute(sa_delete(FlowVersionBug).where(FlowVersionBug.bug_id.in_(bug_ids)))

        # clean up work item links (story/task/bug as source or target)
        all_entity_ids = [*target_story_ids, *task_ids, *bug_ids]
        await session.execute(sa_delete(FlowWorkItemLink).where(
            or_(FlowWorkItemLink.source_id.in_(all_entity_ids), FlowWorkItemLink.target_id.in_(all_entity_ids))
        ))

        # clean up comments and test case associations
        await session.execute(sa_delete(FlowComment).where(
            FlowComment.entity_type.in_(["story", "task", "bug"]),
            FlowComment.entity_id.in_(all_entity_ids),
        ))
        await session.execute(sa_delete(FlowTestCaseWorkItem).where(
            FlowTestCaseWorkItem.entity_id.in_(all_entity_ids),
        ))

        # nullify task.story_id for tasks referencing bugs (bug.task_id FK)
        if task_ids:
            await session.execute(sa_update(FlowBug).where(FlowBug.task_id.in_(task_ids)).values(task_id=None))

        # delete tasks, bugs, child stories, main story
        await session.execute(sa_delete(FlowTask).where(FlowTask.story_id.in_(target_story_ids)))
        await session.execute(sa_delete(FlowBug).where(FlowBug.story_id.in_(target_story_ids)))
        await session.execute(sa_delete(FlowStory).where(FlowStory.id.in_(descendant_ids)))
        await session.delete(s)
        await _log_event(
            session,
            "story",
            story_id,
            "deleted",
            {"title": s.title, "deleted_children": len(descendant_ids)},
        )
        await session.commit()
    return {"ok": True}

@sub_router.post("/stories/{story_id}/reorder")
async def reorder_story(story_id: str, body: StoryReorder, request: Request):
    """拖拽排序：支持同 parent 内调序，或跨 parent 移动（含挪到顶层）。

    参数语义：
    - before_id: source 落到该需求之"前"（按 sort_order 升序，source < before）
    - after_id:  source 落到该需求之"后"（source > after）
    - parent_id: 显式指定目标父节点；与锚点同时传时以锚点的 parent 为准

    sort_order 计算：
    - 同时给 before + after → 取两者中点（fractional ranking）
    - 仅 before → before - 1024
    - 仅 after  → after + 1024
    - 都不给 → 目标 parent 下当前最大 sort_order + 1024（落到末尾）
    """
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        source = await session.get(FlowStory, story_id)
        if not source:
            raise HTTPException(status_code=404, detail="需求不存在")
        if getattr(source, "is_archived", False):
            raise HTTPException(status_code=409, detail="已归档的需求不能拖拽")

        before = None
        after = None
        if body.before_id:
            before = await session.get(FlowStory, body.before_id)
            if not before:
                raise HTTPException(status_code=404, detail="目标锚点不存在（before）")
            if before.id == story_id:
                raise HTTPException(status_code=400, detail="不能拖到自身")
        if body.after_id:
            after = await session.get(FlowStory, body.after_id)
            if not after:
                raise HTTPException(status_code=404, detail="目标锚点不存在（after）")
            if after.id == story_id:
                raise HTTPException(status_code=400, detail="不能拖到自身")

        # 锚点必须同项目
        for anchor in (before, after):
            if anchor is not None and anchor.project_id != source.project_id:
                raise HTTPException(status_code=400, detail="不能跨项目拖拽")

        # 目标 parent_id 优先级：锚点 parent > body.parent_id > source 原 parent
        anchor_for_parent = before or after
        if anchor_for_parent is not None:
            target_parent_id_raw: str | None = anchor_for_parent.parent_id
        elif body.parent_id is not None:
            target_parent_id_raw = body.parent_id or None
        else:
            target_parent_id_raw = source.parent_id

        normalized_parent_id, parent_error = await _validate_story_parent(
            session,
            project_id=source.project_id,
            parent_id=target_parent_id_raw,
            story_id=story_id,
        )
        if parent_error:
            raise HTTPException(status_code=400, detail=parent_error)

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
            max_order_stmt = select(func.max(FlowStory.sort_order)).where(
                FlowStory.project_id == source.project_id
            )
            if normalized_parent_id is None:
                max_order_stmt = max_order_stmt.where(FlowStory.parent_id.is_(None))
            else:
                max_order_stmt = max_order_stmt.where(FlowStory.parent_id == normalized_parent_id)
            current_max = (await session.execute(max_order_stmt)).scalar()
            new_sort_order = (float(current_max) if current_max is not None else 0.0) + STEP

        old_parent_id = source.parent_id
        old_sort_order = source.sort_order
        changes: dict = {}
        if normalized_parent_id != old_parent_id:
            changes["parent_id"] = {"from": old_parent_id, "to": normalized_parent_id}
            source.parent_id = normalized_parent_id
        if new_sort_order != old_sort_order:
            changes["sort_order"] = {"from": old_sort_order, "to": new_sort_order}
            source.sort_order = new_sort_order

        if changes:
            await _log_event(session, "story", story_id, "reordered", changes, actor_id=actor_id)
        await session.commit()
        await session.refresh(source)
    return _story_dict(source)


@sub_router.post("/stories/{story_id}/transition")
async def transition_story(story_id: str, body: TransitionBody, request: Request):
    payload = require_auth(request)
    actor_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        s = await session.get(FlowStory, story_id)
        if not s:
            raise HTTPException(status_code=404, detail="需求不存在")
        if getattr(s, "is_archived", False):
            raise HTTPException(status_code=409, detail="操作失败，当前工作项已归档！")
        ok, error, _auto_fields, old_state = await _apply_state_change(
            session,
            kind="story",
            obj=s,
            new_state=body.target_state,
            actor_id=actor_id,
            strict=True,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=error)
        new_state = s.state
        collaborators = _parse_json_list(s.collaborators_json)
        await session.commit()
        await session.refresh(s)
    if new_state != old_state:
        schedule_notification(_notifier.notify_state_change(
            "story", story_id, s.title, actor_id,
            old_state, new_state,
            assignee_id=getattr(s, "assignee_id", None) or s.pm_id,
            collaborator_ids=collaborators,
            creator_id=s.submitter_id,
            project_id=s.project_id or "",
        ))
    return _story_dict(s)

@sub_router.post("/stories/{story_id}/copy")
async def copy_story(story_id: str, request: Request):
    payload = require_auth(request)
    member_id = payload.get("sub", "")
    sf = get_session_factory()
    async with sf() as session:
        src = await session.get(FlowStory, story_id)
        if not src:
            raise HTTPException(status_code=404, detail="需求不存在")
        new_story = FlowStory(
            project_id=src.project_id,
            title=f"{src.title} (副本)",
            description=src.description,
            priority=src.priority,
            priority_score=getattr(src, "priority_score", None),
            parent_id=src.parent_id,
            submitter_id=member_id or None,
            assignee_id=getattr(src, "assignee_id", None),
            tags_json=src.tags_json,
            collaborators_json=src.collaborators_json,
            attachments_json=src.attachments_json,
            deadline=src.deadline,
        )
        session.add(new_story)
        await session.flush()

        iter_row = (await session.execute(
            select(FlowIterationStory.iteration_id)
            .where(FlowIterationStory.story_id == story_id)
            .limit(1)
        )).scalar()
        if iter_row:
            session.add(FlowIterationStory(iteration_id=iter_row, story_id=new_story.id))

        from openvort.plugins.vortflow.models import FlowVersionStory
        ver_row = (await session.execute(
            select(FlowVersionStory.version_id)
            .where(FlowVersionStory.story_id == story_id)
            .limit(1)
        )).scalar()
        if ver_row:
            session.add(FlowVersionStory(version_id=ver_row, story_id=new_story.id))

        await _log_event(session, "story", new_story.id, "created",
                         {"title": new_story.title, "copied_from": story_id}, actor_id=member_id)
        await session.commit()
        await session.refresh(new_story)
    return _story_dict(new_story)

@sub_router.get("/stories/{story_id}/transitions")
async def get_story_transitions(story_id: str):
    """Get allowed next states for a story"""
    sf = get_session_factory()
    async with sf() as session:
        s = await session.get(FlowStory, story_id)
        if not s:
            raise HTTPException(status_code=404, detail="需求不存在")
    try:
        current = StoryState(s.state)
    except ValueError:
        return {"transitions": []}
    allowed = STORY_TRANSITIONS.get(current, [])
    return {"current": s.state, "transitions": [t.value for t in allowed]}
