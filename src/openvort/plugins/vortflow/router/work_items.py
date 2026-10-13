"""VortFlow 工作墙：跨类型工作项聚合查询。

- 三表分别查询 + 应用层合并 + 全局排序 + 切片分页
- 字段统一：
  - owner_id：需求 = assignee_id || pm_id；任务 = assignee_id；缺陷 = assignee_id || developer_id
  - creator_id：需求 = submitter_id；任务 = creator_id；缺陷 = reporter_id
  - priority：需求 = priority；任务/缺陷 = 由 priority_score 派生的等级（1-4）
  - priority_score (0-100)：三类型均为数据库存储或序列化默认值
- 排序：sort_by=priority 等价于 priority_score DESC（score 大的紧急在前），无视 sort_order。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from openvort.db.engine import get_session_factory
from openvort.plugins.vortflow.engine import (
    BUG_CLOSED_STATES,
    STORY_DONE_STATES,
    TASK_DONE_STATES,
)
from openvort.plugins.vortflow.models import (
    FlowBug,
    FlowIterationBug,
    FlowIterationStory,
    FlowIterationTask,
    FlowStory,
    FlowTask,
)
from openvort.plugins.vortflow.router.helpers import (
    _attach_bug_links,
    _attach_project_names,
    _attach_story_links,
    _attach_task_links,
    _bug_dict,
    _story_dict,
    _task_dict,
    resolve_project_ids,
    estimate_hours_to_priority_score_default,
    priority_level_to_default_score,
    score_to_priority_level,
    severity_to_priority_score,
)

sub_router = APIRouter()

SUPPORTED_TYPES = {"story", "task", "bug"}


@sub_router.get("/work-items")
async def list_work_items(
    types: str = Query("story,task,bug", description="工作项类型，逗号分隔（story/task/bug）"),
    project_id: str = Query("", description="按项目过滤（单个）；为空则跨项目"),
    project_ids: str = Query("", description="按项目过滤（逗号分隔多选，优先于 project_id）"),
    iteration_id: str = Query("", description="按迭代过滤"),
    state: str = Query("", description="按状态过滤（逗号分隔的 backend state 名）"),
    keyword: str = Query("", description="关键词搜索"),
    assignee_id: str = Query("", description="按负责人过滤"),
    creator_id: str = Query("", description="按创建人过滤"),
    participant_id: str = Query(
        "",
        description=(
            "按参与者过滤；与「成员关注」卡片口径完全一致（fallback 语义）："
            "需求=负责人 OR (负责人为空 → 产品经理) OR 协作者；"
            "任务=负责人 OR 协作者；"
            "缺陷=负责人 OR (负责人为空 → 开发者) OR 协作者。"
            "**不含创建人/报告人**——若需按创建维度过滤，请使用 creator_id。"
            "fallback 语义保证：当工作项已指派给具体负责人后，原 pm/developer "
            "不再出现在自己的工作墙，避免「我曾参与但已转手」的工作项干扰视图。"
        ),
    ),
    archived: bool = Query(False, description="是否查看已归档"),
    include_archived: bool = Query(
        False,
        description="是否同时包含已归档（为 True 时忽略 archived，返回归档+未归档）",
    ),
    sort_by: str = Query("created_at", description="排序字段（priority/updated_at/created_at/deadline）"),
    sort_order: str = Query("desc", description="排序方向 asc/desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    completed_after: str = Query(
        "",
        description=(
            "「当日已完成」起点（ISO datetime）。提供时只命中完成态记录中 "
            "end_at ∈ [completed_after, completed_after + 1d) 的项；未完成态不受影响。"
            "区间隐含 1 天上界以避免 end_at 被误填到未来导致的脏数据被误算入「今日完成」。"
        ),
    ),
):
    """跨类型工作项聚合查询（用于工作墙）。"""
    type_set = {t.strip() for t in types.split(",") if t.strip()} or set(SUPPORTED_TYPES)
    type_set &= SUPPORTED_TYPES
    if not type_set:
        return {"items": [], "total": 0}

    completed_after_dt: datetime | None = None
    if completed_after:
        try:
            parsed = datetime.fromisoformat(completed_after.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                # 前端 toISOString() 输出的是 UTC（带 Z），但数据库 end_at 等列存的是本地
                # naive 时间。先把含时区的输入转换为本地时区再剥掉 tzinfo，否则会把
                # 「昨天本地 16:00 之后」错算成「今天 0 点之后」（北京 +08:00 偏移）。
                parsed = parsed.astimezone().replace(tzinfo=None)
            completed_after_dt = parsed
        except (ValueError, TypeError):
            completed_after_dt = None

    sf = get_session_factory()
    async with sf() as session:
        all_items: list[dict] = []
        total = 0
        common = dict(
            session=session,
            project_ids=resolve_project_ids(project_id, project_ids),
            iteration_id=iteration_id,
            state=state,
            keyword=keyword,
            assignee_id=assignee_id,
            creator_id=creator_id,
            participant_id=participant_id,
            archived=archived,
            include_archived=include_archived,
            sort_by=sort_by,
            sort_order=sort_order,
            completed_after=completed_after_dt,
            limit=page * page_size,
        )

        if "story" in type_set:
            items, sub_total = await _query_stories(**common)
            for it in items:
                it["type"] = "story"
                it["owner_id"] = it.get("assignee_id") or it.get("pm_id") or ""
                it["creator_id"] = it.get("submitter_id") or ""
                # priority_score 已由 _story_dict 输出；兜底防 None。
                if it.get("priority_score") is None:
                    it["priority_score"] = priority_level_to_default_score(it.get("priority"))
            all_items.extend(items)
            total += sub_total

        if "task" in type_set:
            items, sub_total = await _query_tasks(**common)
            for it in items:
                it["type"] = "task"
                it["owner_id"] = it.get("assignee_id") or ""
                sc = it.get("priority_score")
                if sc is None:
                    sc = estimate_hours_to_priority_score_default(it.get("estimate_hours"))
                    it["priority_score"] = sc
                it["priority"] = score_to_priority_level(int(sc))
            all_items.extend(items)
            total += sub_total

        if "bug" in type_set:
            items, sub_total = await _query_bugs(**common)
            for it in items:
                it["type"] = "bug"
                it["owner_id"] = it.get("assignee_id") or it.get("developer_id") or ""
                it["creator_id"] = it.get("reporter_id") or ""
                it["priority"] = it.get("severity")
                sc = it.get("priority_score")
                if sc is None:
                    sc = severity_to_priority_score(it.get("severity"))
                    it["priority_score"] = sc
            all_items.extend(items)
            total += sub_total

        # 优先级排序：按 priority_score DESC（score 大的在前）；其它字段保留原 sort_order 语义。
        if sort_by in ("priority", "priority_score"):
            all_items.sort(
                key=lambda x: (x.get("priority_score") or 0, _ts_str(x.get("updated_at"))),
                reverse=True,
            )
        else:
            all_items.sort(key=_build_sort_key(sort_by or "created_at"), reverse=(sort_order != "asc"))

        start = (page - 1) * page_size
        items = all_items[start : start + page_size]
        await _attach_project_names(session, items)

    return {"items": items, "total": total}


def _ts_str(s: str | None) -> float:
    if not s:
        return 0
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0


def _build_sort_key(sort_by: str):
    """根据非优先级排序字段返回排序 key 函数（priority 已在主流程单独处理）。"""

    if sort_by == "updated_at":
        return lambda x: _ts_str(x.get("updated_at"))
    if sort_by == "created_at":
        return lambda x: _ts_str(x.get("created_at"))
    if sort_by == "deadline":
        return lambda x: _ts_str(x.get("deadline") or "9999-12-31T00:00:00")
    # 兜底：仍按 priority_score 排序
    return lambda x: (x.get("priority_score") or 0, _ts_str(x.get("updated_at")))


def _split_states(state: str) -> list[str]:
    return [s.strip() for s in state.split(",") if s.strip()]


def _apply_local_sort(stmt, model, sort_by: str, sort_order: str, *, priority_col, priority_desc: bool = False):
    """对单表查询应用本地排序，确保全局排序时 top-N 截断不会漏关键记录。

    - sort_by=priority 时：优先用 priority_score 列 DESC（数值越大越优先）
    - 其他字段按 sort_order 应用 asc/desc。
    """
    asc = sort_order == "asc"
    if sort_by in ("priority", "priority_score"):
        if priority_col is None:
            col, asc = model.updated_at, False
        else:
            col = priority_col
            asc = not priority_desc
    elif sort_by == "updated_at":
        col = model.updated_at
    elif sort_by == "created_at":
        col = model.created_at
    elif sort_by == "deadline":
        col = model.deadline
    else:
        col, asc = model.updated_at, False
    order_fn = col.asc() if asc else col.desc()
    return stmt.order_by(order_fn, model.id.desc())


async def _query_stories(
    *,
    session,
    project_ids: list[str],
    iteration_id: str,
    state: str,
    keyword: str,
    assignee_id: str,
    creator_id: str,
    participant_id: str,
    archived: bool,
    include_archived: bool,
    sort_by: str,
    sort_order: str,
    completed_after: datetime | None,
    limit: int,
):
    # include_archived=True 时返回归档+未归档，不加归档过滤条件。
    where: list = [FlowStory.parent_id.is_(None)]
    if not include_archived:
        where.append(FlowStory.is_archived.is_(True) if archived else FlowStory.is_archived.is_not(True))

    if project_ids:
        where.append(FlowStory.project_id.in_(project_ids))
    if iteration_id == "__unplanned__":
        planned_ids = select(FlowIterationStory.story_id)
        where.append(~FlowStory.id.in_(planned_ids))
    elif iteration_id:
        iter_ids = select(FlowIterationStory.story_id).where(FlowIterationStory.iteration_id == iteration_id)
        where.append(FlowStory.id.in_(iter_ids))
    states = _split_states(state)
    if states:
        where.append(FlowStory.state.in_(states))
    if keyword:
        where.append(FlowStory.title.ilike(f"%{keyword}%"))
    if assignee_id:
        where.append(
            or_(
                FlowStory.assignee_id == assignee_id,
                (FlowStory.assignee_id.is_(None)) & (FlowStory.pm_id == assignee_id),
            )
        )
    if creator_id:
        where.append(FlowStory.submitter_id == creator_id)
    if participant_id:
        # 与 /members/workload 的成员匹配口径完全一致：
        # 需求 owner = coalesce(nullif(assignee_id, ""), pm_id)。
        # pm 仅在 assignee 为空时才回退命中，避免「pm 是 X 但已指派给别人」的需求
        # 仍被算入 X 的工作墙。collab 仍以 OR 命中。
        like_p = f'%"{participant_id}"%'
        where.append(
            or_(
                FlowStory.assignee_id == participant_id,
                and_(
                    or_(FlowStory.assignee_id.is_(None), FlowStory.assignee_id == ""),
                    FlowStory.pm_id == participant_id,
                ),
                FlowStory.collaborators_json.like(like_p),
            )
        )
    # 「当日已完成」窗口：完成态记录 end_at ∈ [completed_after, completed_after + 1d)；
    # 未完成态记录不受影响。加上界规避 end_at 被填到未来日期的脏数据被误算入。
    if completed_after is not None:
        completed_until = completed_after + timedelta(days=1)
        where.append(
            or_(
                FlowStory.state.not_in(STORY_DONE_STATES),
                and_(
                    FlowStory.end_at.is_not(None),
                    FlowStory.end_at >= completed_after,
                    FlowStory.end_at < completed_until,
                ),
            )
        )

    total = (await session.execute(select(func.count()).select_from(FlowStory).where(*where))).scalar_one()
    stmt = _apply_local_sort(
        select(FlowStory).where(*where), FlowStory, sort_by, sort_order,
        priority_col=FlowStory.priority_score, priority_desc=True,
    ).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [_story_dict(r) for r in rows]
    await _attach_story_links(session, items)
    return items, total


async def _query_tasks(
    *,
    session,
    project_ids: list[str],
    iteration_id: str,
    state: str,
    keyword: str,
    assignee_id: str,
    creator_id: str,
    participant_id: str,
    archived: bool,
    include_archived: bool,
    sort_by: str,
    sort_order: str,
    completed_after: datetime | None,
    limit: int,
):
    # include_archived=True 时返回归档+未归档，不加归档过滤条件。
    where: list = [FlowTask.parent_id.is_(None)]
    if not include_archived:
        where.append(FlowTask.is_archived.is_(True) if archived else FlowTask.is_archived.is_not(True))

    if project_ids:
        project_story_ids = select(FlowStory.id).where(FlowStory.project_id.in_(project_ids))
        where.append(or_(FlowTask.project_id.in_(project_ids), FlowTask.story_id.in_(project_story_ids)))
    if iteration_id == "__unplanned__":
        planned_ids = select(FlowIterationTask.task_id)
        where.append(~FlowTask.id.in_(planned_ids))
    elif iteration_id:
        iter_ids = select(FlowIterationTask.task_id).where(FlowIterationTask.iteration_id == iteration_id)
        where.append(FlowTask.id.in_(iter_ids))
    states = _split_states(state)
    if states:
        where.append(FlowTask.state.in_(states))
    if keyword:
        where.append(FlowTask.title.ilike(f"%{keyword}%"))
    if assignee_id:
        where.append(FlowTask.assignee_id == assignee_id)
    if creator_id:
        where.append(FlowTask.creator_id == creator_id)
    if participant_id:
        like_p = f'%"{participant_id}"%'
        where.append(
            or_(
                FlowTask.assignee_id == participant_id,
                FlowTask.collaborators_json.like(like_p),
            )
        )
    if completed_after is not None:
        completed_until = completed_after + timedelta(days=1)
        where.append(
            or_(
                FlowTask.state.not_in(TASK_DONE_STATES),
                and_(
                    FlowTask.end_at.is_not(None),
                    FlowTask.end_at >= completed_after,
                    FlowTask.end_at < completed_until,
                ),
            )
        )

    total = (await session.execute(select(func.count()).select_from(FlowTask).where(*where))).scalar_one()
    stmt = _apply_local_sort(select(FlowTask).where(*where), FlowTask, sort_by, sort_order, priority_col=FlowTask.priority_score, priority_desc=True).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [_task_dict(r) for r in rows]
    await _attach_task_links(session, items)
    return items, total


async def _query_bugs(
    *,
    session,
    project_ids: list[str],
    iteration_id: str,
    state: str,
    keyword: str,
    assignee_id: str,
    creator_id: str,
    participant_id: str,
    archived: bool,
    include_archived: bool,
    sort_by: str,
    sort_order: str,
    completed_after: datetime | None,
    limit: int,
):
    # include_archived=True 时返回归档+未归档，不加归档过滤条件。
    where: list = []
    if not include_archived:
        where.append(FlowBug.is_archived.is_(True) if archived else FlowBug.is_archived.is_not(True))

    if project_ids:
        project_story_ids = select(FlowStory.id).where(FlowStory.project_id.in_(project_ids))
        where.append(or_(FlowBug.project_id.in_(project_ids), FlowBug.story_id.in_(project_story_ids)))
    if iteration_id == "__unplanned__":
        planned_story_ids = select(FlowIterationStory.story_id)
        planned_bug_ids = select(FlowIterationBug.bug_id)
        where.append(
            or_(
                FlowBug.story_id.is_(None),
                FlowBug.story_id == "",
                ~FlowBug.story_id.in_(planned_story_ids),
            )
        )
        where.append(~FlowBug.id.in_(planned_bug_ids))
    elif iteration_id:
        iter_story_ids = select(FlowIterationStory.story_id).where(FlowIterationStory.iteration_id == iteration_id)
        direct_bug_ids = select(FlowIterationBug.bug_id).where(FlowIterationBug.iteration_id == iteration_id)
        where.append(or_(FlowBug.story_id.in_(iter_story_ids), FlowBug.id.in_(direct_bug_ids)))
    states = _split_states(state)
    if states:
        where.append(FlowBug.state.in_(states))
    if keyword:
        where.append(FlowBug.title.ilike(f"%{keyword}%"))
    if assignee_id:
        where.append(
            or_(
                FlowBug.assignee_id == assignee_id,
                (FlowBug.assignee_id.is_(None)) & (FlowBug.developer_id == assignee_id),
            )
        )
    if creator_id:
        where.append(FlowBug.reporter_id == creator_id)
    if participant_id:
        # 与 /members/workload 的成员匹配口径完全一致：
        # 缺陷 owner = coalesce(nullif(assignee_id, ""), developer_id)。
        # developer 仅在 assignee 为空时才回退命中，避免「assignee=测试/产品,
        # developer=研发」的缺陷仍出现在研发的工作墙——他对应的状态由 assignee 主导。
        like_p = f'%"{participant_id}"%'
        where.append(
            or_(
                FlowBug.assignee_id == participant_id,
                and_(
                    or_(FlowBug.assignee_id.is_(None), FlowBug.assignee_id == ""),
                    FlowBug.developer_id == participant_id,
                ),
                FlowBug.collaborators_json.like(like_p),
            )
        )
    if completed_after is not None:
        completed_until = completed_after + timedelta(days=1)
        where.append(
            or_(
                FlowBug.state.not_in(BUG_CLOSED_STATES),
                and_(
                    FlowBug.end_at.is_not(None),
                    FlowBug.end_at >= completed_after,
                    FlowBug.end_at < completed_until,
                ),
            )
        )

    total = (await session.execute(select(func.count()).select_from(FlowBug).where(*where))).scalar_one()
    stmt = _apply_local_sort(select(FlowBug).where(*where), FlowBug, sort_by, sort_order, priority_col=FlowBug.priority_score, priority_desc=True).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [_bug_dict(r) for r in rows]
    await _attach_bug_links(session, items)
    return items, total
