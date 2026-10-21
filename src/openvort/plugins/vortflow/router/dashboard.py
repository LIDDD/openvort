"""VortFlow Dashboard stats."""

import json
from datetime import datetime, timedelta
from typing import Iterable

from fastapi import APIRouter, Query
from sqlalchemy import String, func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.sql.functions import coalesce

from openvort.db.engine import get_session_factory
from openvort.plugins.vortflow.engine import (
    BUG_CLOSED_STATES,
    STORY_DEVELOPMENT_PENDING_STATES,
    STORY_DONE_STATES,
    TASK_DONE_STATES,
    BugState,
    StoryState,
    TaskState,
)
from openvort.plugins.vortflow.models import (
    FlowBug,
    FlowComment,
    FlowEvent,
    FlowIterationBug,
    FlowIterationStory,
    FlowIterationTask,
    FlowStory,
    FlowTask,
)

UNPLANNED_ITERATION = "__unplanned__"

# 与 /work-items 接口「在手」过滤一致：取所有合法 state 的非完成态集合
STORY_PENDING_STATES: set[str] = {s.value for s in StoryState if s.value not in STORY_DONE_STATES}
TASK_PENDING_STATES: set[str] = {s.value for s in TaskState if s.value not in TASK_DONE_STATES}
BUG_PENDING_STATES: set[str] = {s.value for s in BugState if s.value not in BUG_CLOSED_STATES}

sub_router = APIRouter()


@sub_router.get("/dashboard/stats")
async def dashboard_stats(
    project_id: str = Query("", description="按项目过滤（单个）"),
    project_ids: str = Query("", description="按项目过滤（逗号分隔多选，优先于 project_id）"),
):
    from openvort.plugins.vortflow.router.helpers import resolve_project_ids

    sf = get_session_factory()
    async with sf() as session:
        story_where = [FlowStory.is_archived.is_not(True)]
        task_where = [FlowTask.is_archived.is_not(True)]
        bug_where = [FlowBug.is_archived.is_not(True)]

        pids = resolve_project_ids(project_id, project_ids)
        if pids:
            proj_story_ids = select(FlowStory.id).where(FlowStory.project_id.in_(pids))
            story_where.append(FlowStory.project_id.in_(pids))
            task_where.append(
                or_(FlowTask.project_id.in_(pids), FlowTask.story_id.in_(proj_story_ids))
            )
            bug_where.append(
                or_(FlowBug.project_id.in_(pids), FlowBug.story_id.in_(proj_story_ids))
            )

        story_total = (await session.execute(
            select(func.count()).select_from(FlowStory).where(*story_where)
        )).scalar_one()
        story_done = (await session.execute(
            select(func.count()).select_from(FlowStory)
            .where(*story_where, FlowStory.state.in_(STORY_DONE_STATES))
        )).scalar_one()

        task_total = (await session.execute(
            select(func.count()).select_from(FlowTask).where(*task_where)
        )).scalar_one()
        task_done = (await session.execute(
            select(func.count()).select_from(FlowTask)
            .where(*task_where, FlowTask.state.in_(TASK_DONE_STATES))
        )).scalar_one()

        bug_total = (await session.execute(
            select(func.count()).select_from(FlowBug).where(*bug_where)
        )).scalar_one()
        bug_closed = (await session.execute(
            select(func.count()).select_from(FlowBug)
            .where(*bug_where, FlowBug.state.in_(BUG_CLOSED_STATES))
        )).scalar_one()

    return {
        "stories": {"total": story_total, "done": story_done},
        "tasks": {"total": task_total, "done": task_done},
        "bugs": {"total": bug_total, "closed": bug_closed},
    }


@sub_router.get("/members/workload")
async def members_workload(
    member_ids: str = Query("", description="逗号分隔的成员 ID 列表"),
    project_id: str = Query("", description="可选项目过滤（单个）"),
    project_ids: str = Query("", description="可选项目过滤（逗号分隔多选，优先于 project_id）"),
    iteration_id: str = Query("", description="可选迭代过滤；具体 id 仅看该迭代内，'__unplanned__' 仅看未排期"),
    due_soon_days: int = Query(3, ge=0, le=30, description="即将到期阈值（天）"),
    history_days: int = Query(7, ge=1, le=30, description="在手历史 / 活动度回看天数"),
    forecast_days: int = Query(7, ge=1, le=30, description="未来到期 / 累计逾期预测天数"),
    velocity_days: int = Query(7, ge=1, le=30, description="完成数 / 流转天数统计窗口（天）"),
    stale_days: int = Query(7, ge=1, le=60, description="停滞判定阈值：在手项 N 天无 Event/Comment 视为停滞"),
):
    """成员工作量聚合，给工作墙的成员关注面板使用。

    每位成员返回字段（向前兼容，新增字段不会破坏老前端）：

    旧字段：
    - pending_total / by_type.{story,task,bug} — 未完成
    - overdue / due_soon / urgent — 风险

    Phase 1 扩展：
    - completed_recent / completed_prev — 流速：最近 velocity_days 天与上一个 velocity_days 天完成数（同比）
    - avg_lead_time_days — 个人平均流转天数（已完成项的 end_at - start_at）
    - team_avg_lead_time_days — 同窗口、同过滤下所有传入成员的均值
    - stale_count — 停滞数（在手项中超过 stale_days 没有 Event 或 Comment 且未逾期）
    - activity_7d — 长度 history_days 的整数数组（旧→新），每日 FlowEvent + FlowComment 数
    - pending_history_7d — 长度 history_days 的整数数组（旧→新），每日在手数估算

    Phase 2 扩展（hover 浮窗时间轴图表用）：
    - daily_completed — 长度 history_days，过去每日完成数（旧→新）
    - daily_created — 长度 history_days，过去每日新增数（旧→新）
    - future_due — 长度 forecast_days，未来每日到期数（基于在手项 deadline，明天起→远期）
    - future_overdue_cumulative — 长度 forecast_days，未来每日累计逾期数（含当前逾期）

    口径说明：
    - 成员匹配口径：与 /work-items 的 participant_id 一致，命中以下任一即计入：
      assignee_id / pm_id（需求）/ developer_id（缺陷）/ collaborators_json。
      **不含创建人/报告人**：他们仅作为来源记录，不属于「手上的活」。
      因此同一工作项可能同时计入多人卡片（assignee + 协作者），这是预期行为：
      卡片表达的是「这个人手上需要关注的事」，而非全局唯一所有权。
    - stale_count 与 overdue **互斥**：已逾期的项已计入 overdue，不再出现在 stale 中，
      避免卡片上「逾期 N」「停滞 M」两个标签数字重复造成误导。
    - 历史字段 wip_limit / capacity_norm 已下线：单一阈值套不同岗位假阳性过高，
      告警改由「逾期 / 即将到期 / 停滞」业务事件驱动。
    """
    ids = [x.strip() for x in member_ids.split(",") if x.strip()]
    if not ids:
        return []

    today_start = datetime.combine(datetime.now().date(), datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)
    soon_end = today_start + timedelta(days=due_soon_days + 1)
    velocity_start = tomorrow_start - timedelta(days=velocity_days)
    velocity_prev_start = velocity_start - timedelta(days=velocity_days)
    stale_cutoff = datetime.now() - timedelta(days=stale_days)
    history_start = tomorrow_start - timedelta(days=history_days)

    # 与 work-items 接口的负责人语义对齐：
    # - 需求 owner = coalesce(nullif(assignee_id, ''), pm_id)
    # - 任务 owner = assignee_id
    # - 缺陷 owner = coalesce(nullif(assignee_id, ''), developer_id)
    # nullif 处理空字符串场景，确保 fallback 与 /work-items 接口一致
    # 注：owner 表达式仅用于 stale / future_due 这类需要回填一个具体 owner 的场景；
    # 计数维度统一改走「成员匹配」（owner OR collaborators_json）以纳入协作者。
    story_owner = coalesce(func.nullif(FlowStory.assignee_id, ""), FlowStory.pm_id)
    task_owner = FlowTask.assignee_id
    bug_owner = coalesce(func.nullif(FlowBug.assignee_id, ""), FlowBug.developer_id)

    ids_set = set(ids)

    # 成员匹配交叉连接子查询：将单条工作项展开成 (item, mid) 行对，
    # 让同一项能同时计入多个匹配成员的卡片。每次调用生成新实例，避免 alias 复用问题。
    def _member_subq():
        return select(func.unnest(array(ids, type_=String())).label("mid")).subquery()

    # collaborators_json 形如 '["u_aaa","u_bbb"]'，借助 LIKE '%"<mid>"%' 命中。
    # 成员 id 是受控 UUID/u_xxx，不含双引号，不会与 JSON 边界字符混淆。
    def _collab_like(model, mid_col):
        return getattr(model, "collaborators_json").like(
            func.concat('%"', mid_col, '"%')
        )

    def _story_match(mid_col):
        return or_(
            coalesce(func.nullif(FlowStory.assignee_id, ""), FlowStory.pm_id) == mid_col,
            _collab_like(FlowStory, mid_col),
        )

    def _task_match(mid_col):
        return or_(
            FlowTask.assignee_id == mid_col,
            _collab_like(FlowTask, mid_col),
        )

    def _bug_match(mid_col):
        return or_(
            coalesce(func.nullif(FlowBug.assignee_id, ""), FlowBug.developer_id) == mid_col,
            _collab_like(FlowBug, mid_col),
        )

    # 用于「单次拉行后在 Python 里展开匹配成员」的预过滤：
    # 任意 owner 命中 ids，或任意 collaborator 命中 ids。
    def _any_member_match(model, owner_expr):
        return or_(
            owner_expr.in_(ids),
            *[
                getattr(model, "collaborators_json").like(f'%"{mid}"%')
                for mid in ids
            ],
        )

    def _parse_collabs(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            v = json.loads(raw)
        except Exception:
            return []
        if not isinstance(v, list):
            return []
        return [str(x) for x in v if isinstance(x, (str, int)) and str(x)]

    sf = get_session_factory()
    async with sf() as session:
        from openvort.plugins.vortflow.router.helpers import resolve_project_ids
        pids = resolve_project_ids(project_id, project_ids)
        if pids:
            project_story_ids = select(FlowStory.id).where(FlowStory.project_id.in_(pids))
            story_proj = [FlowStory.project_id.in_(pids)]
            task_proj = [or_(
                FlowTask.project_id.in_(pids),
                FlowTask.story_id.in_(project_story_ids),
            )]
            bug_proj = [or_(
                FlowBug.project_id.in_(pids),
                FlowBug.story_id.in_(project_story_ids),
            )]
        else:
            story_proj = []
            task_proj = []
            bug_proj = []

        # 迭代过滤：
        # - 空：不过滤
        # - 具体 id：取该迭代下关联的工作项
        # - __unplanned__：取所有未关联到任何迭代的工作项
        if iteration_id == UNPLANNED_ITERATION:
            story_iter = [FlowStory.id.not_in(select(FlowIterationStory.story_id))]
            task_iter = [FlowTask.id.not_in(select(FlowIterationTask.task_id))]
            bug_iter = [FlowBug.id.not_in(select(FlowIterationBug.bug_id))]
        elif iteration_id:
            story_iter = [FlowStory.id.in_(
                select(FlowIterationStory.story_id).where(FlowIterationStory.iteration_id == iteration_id)
            )]
            task_iter = [FlowTask.id.in_(
                select(FlowIterationTask.task_id).where(FlowIterationTask.iteration_id == iteration_id)
            )]
            bug_iter = [FlowBug.id.in_(
                select(FlowIterationBug.bug_id).where(FlowIterationBug.iteration_id == iteration_id)
            )]
        else:
            story_iter = []
            task_iter = []
            bug_iter = []

        # 与 /work-items 接口的统计口径对齐：
        # 1. 只统计顶层工作项（需求/任务），缺陷无父级
        # 2. 用「非完成态」白名单替代 not_in(完成态)，避免脏数据/旧状态被误算入「在手」
        # 3. 不在 base 中限制 owner.in_(ids)：成员匹配交由后续的 cross join + match_fn 处理，
        #    以便协作者也能命中。
        story_base = [
            FlowStory.is_archived.is_not(True),
            FlowStory.parent_id.is_(None),
            FlowStory.state.in_(STORY_PENDING_STATES),
            *story_proj,
            *story_iter,
        ]
        task_base = [
            FlowTask.is_archived.is_not(True),
            FlowTask.parent_id.is_(None),
            FlowTask.state.in_(TASK_PENDING_STATES),
            *task_proj,
            *task_iter,
        ]
        bug_base = [
            FlowBug.is_archived.is_not(True),
            FlowBug.state.in_(BUG_PENDING_STATES),
            *bug_proj,
            *bug_iter,
        ]

        # 完成项过滤：跟在手过滤共享 project / iteration / parent 维度，但 state ∈ DONE
        # 流速 / 流转天数 / 历史快照都基于这套口径，保持视角一致
        story_done_base = [
            FlowStory.is_archived.is_not(True),
            FlowStory.parent_id.is_(None),
            FlowStory.state.in_(STORY_DONE_STATES),
            *story_proj,
            *story_iter,
        ]
        task_done_base = [
            FlowTask.is_archived.is_not(True),
            FlowTask.parent_id.is_(None),
            FlowTask.state.in_(TASK_DONE_STATES),
            *task_proj,
            *task_iter,
        ]
        bug_done_base = [
            FlowBug.is_archived.is_not(True),
            FlowBug.state.in_(BUG_CLOSED_STATES),
            *bug_proj,
            *bug_iter,
        ]

        async def count_by(model, match_fn, *where) -> dict[str, int]:
            """按「成员匹配」（owner OR collaborator）分组计数。

            通过 cross join unnest(member_ids) 让一条工作项可以同时归到多个匹配成员。
            match_fn(mid_col) 给出 model 与 mid_col 之间的命中条件。
            """
            sq = _member_subq()
            mid_col = sq.c.mid
            rows = (await session.execute(
                select(mid_col, func.count())
                .select_from(model, sq)
                .where(match_fn(mid_col), *where)
                .group_by(mid_col)
            )).all()
            return {row[0]: row[1] for row in rows if row[0]}

        story_pending = await count_by(FlowStory, _story_match, *story_base)
        task_pending = await count_by(FlowTask, _task_match, *task_base)
        bug_pending = await count_by(FlowBug, _bug_match, *bug_base)

        story_overdue = await count_by(
            FlowStory, _story_match,
            *story_base, FlowStory.state.in_(STORY_DEVELOPMENT_PENDING_STATES),
            FlowStory.deadline.is_not(None), FlowStory.deadline < today_start,
        )
        task_overdue = await count_by(
            FlowTask, _task_match,
            *task_base, FlowTask.deadline.is_not(None), FlowTask.deadline < today_start,
        )
        bug_overdue = await count_by(
            FlowBug, _bug_match,
            *bug_base, FlowBug.deadline.is_not(None), FlowBug.deadline < today_start,
        )

        story_due_soon = await count_by(
            FlowStory, _story_match,
            *story_base, FlowStory.state.in_(STORY_DEVELOPMENT_PENDING_STATES),
            FlowStory.deadline.is_not(None),
            FlowStory.deadline >= today_start, FlowStory.deadline < soon_end,
        )
        task_due_soon = await count_by(
            FlowTask, _task_match,
            *task_base, FlowTask.deadline.is_not(None),
            FlowTask.deadline >= today_start, FlowTask.deadline < soon_end,
        )
        bug_due_soon = await count_by(
            FlowBug, _bug_match,
            *bug_base, FlowBug.deadline.is_not(None),
            FlowBug.deadline >= today_start, FlowBug.deadline < soon_end,
        )

        story_urgent = await count_by(
            FlowStory, _story_match,
            *story_base, FlowStory.priority.in_([1, 2]),
        )
        bug_urgent = await count_by(
            FlowBug, _bug_match,
            *bug_base, FlowBug.severity.in_([1, 2]),
        )

        # ============ 流速：最近窗口 / 上一窗口 完成数 ============
        # 用 end_at 作为完成时间。end_at 为空的已完成项不计入（无法归到具体哪天）。
        story_done_recent = await count_by(
            FlowStory, _story_match,
            *story_done_base, FlowStory.end_at.is_not(None),
            FlowStory.end_at >= velocity_start, FlowStory.end_at < tomorrow_start,
        )
        task_done_recent = await count_by(
            FlowTask, _task_match,
            *task_done_base, FlowTask.end_at.is_not(None),
            FlowTask.end_at >= velocity_start, FlowTask.end_at < tomorrow_start,
        )
        bug_done_recent = await count_by(
            FlowBug, _bug_match,
            *bug_done_base, FlowBug.end_at.is_not(None),
            FlowBug.end_at >= velocity_start, FlowBug.end_at < tomorrow_start,
        )

        story_done_prev = await count_by(
            FlowStory, _story_match,
            *story_done_base, FlowStory.end_at.is_not(None),
            FlowStory.end_at >= velocity_prev_start, FlowStory.end_at < velocity_start,
        )
        task_done_prev = await count_by(
            FlowTask, _task_match,
            *task_done_base, FlowTask.end_at.is_not(None),
            FlowTask.end_at >= velocity_prev_start, FlowTask.end_at < velocity_start,
        )
        bug_done_prev = await count_by(
            FlowBug, _bug_match,
            *bug_done_base, FlowBug.end_at.is_not(None),
            FlowBug.end_at >= velocity_prev_start, FlowBug.end_at < velocity_start,
        )

        # ============ 流转天数：avg(end_at - start_at) days ============
        # 只统计 start_at 与 end_at 都齐全的工作项，按「成员匹配」分组求和 + 计数后再除
        async def lead_sum_count(model, match_fn, *where) -> dict[str, tuple[float, int]]:
            sq = _member_subq()
            mid_col = sq.c.mid
            # PostgreSQL: extract(epoch from interval) / 86400 = days
            diff_seconds = func.extract("epoch", model.end_at - model.start_at)
            rows = (await session.execute(
                select(mid_col, func.sum(diff_seconds), func.count())
                .select_from(model, sq)
                .where(
                    match_fn(mid_col),
                    *where,
                    model.start_at.is_not(None),
                    model.end_at.is_not(None),
                )
                .group_by(mid_col)
            )).all()
            return {row[0]: (float(row[1] or 0), int(row[2] or 0)) for row in rows if row[0]}

        story_lead = await lead_sum_count(
            FlowStory, _story_match,
            *story_done_base, FlowStory.end_at >= velocity_start, FlowStory.end_at < tomorrow_start,
        )
        task_lead = await lead_sum_count(
            FlowTask, _task_match,
            *task_done_base, FlowTask.end_at >= velocity_start, FlowTask.end_at < tomorrow_start,
        )
        bug_lead = await lead_sum_count(
            FlowBug, _bug_match,
            *bug_done_base, FlowBug.end_at >= velocity_start, FlowBug.end_at < tomorrow_start,
        )

        # ============ 活动度：FlowEvent + FlowComment 按天分桶 ============
        # 注意：activity 不按 project / iteration 过滤，反映的是该成员在 vortflow 中的总活动度。
        # 这样能捕捉到"换项目了/迭代了"也算活跃，避免误判停滞。
        async def activity_buckets(actor_col, model) -> dict[str, list[int]]:
            day_col = func.date_trunc("day", model.created_at)
            rows = (await session.execute(
                select(actor_col, day_col, func.count())
                .where(
                    actor_col.in_(ids),
                    model.created_at >= history_start,
                    model.created_at < tomorrow_start,
                )
                .group_by(actor_col, day_col)
            )).all()
            out: dict[str, list[int]] = {}
            for actor, day, cnt in rows:
                if not actor or not day:
                    continue
                day_dt = day if isinstance(day, datetime) else datetime.combine(day, datetime.min.time())
                # offset 0 = 最旧那天, history_days-1 = 今天
                offset = (day_dt.date() - history_start.date()).days
                if offset < 0 or offset >= history_days:
                    continue
                arr = out.setdefault(actor, [0] * history_days)
                arr[offset] += int(cnt)
            return out

        event_buckets = await activity_buckets(FlowEvent.actor_id, FlowEvent)
        comment_buckets = await activity_buckets(FlowComment.author_id, FlowComment)

        # ============ 在手历史快照（反推算法）============
        # pending(d) = pending_now + sum(完成于 (d, today]) - sum(创建于 (d, today])
        # 简化假设：忽略归档/重新打开等极端场景。Phase 6 引入每日快照表后改为精确值。
        async def daily_count_by(model, match_fn, time_col, *where) -> dict[str, list[int]]:
            sq = _member_subq()
            mid_col = sq.c.mid
            day_col = func.date_trunc("day", time_col)
            rows = (await session.execute(
                select(mid_col, day_col, func.count())
                .select_from(model, sq)
                .where(
                    match_fn(mid_col),
                    *where,
                    time_col >= history_start,
                    time_col < tomorrow_start,
                )
                .group_by(mid_col, day_col)
            )).all()
            out: dict[str, list[int]] = {}
            for owner, day, cnt in rows:
                if not owner or not day:
                    continue
                day_dt = day if isinstance(day, datetime) else datetime.combine(day, datetime.min.time())
                offset = (day_dt.date() - history_start.date()).days
                if offset < 0 or offset >= history_days:
                    continue
                arr = out.setdefault(owner, [0] * history_days)
                arr[offset] += int(cnt)
            return out

        story_completed_daily = await daily_count_by(
            FlowStory, _story_match, FlowStory.end_at,
            *story_done_base, FlowStory.end_at.is_not(None),
        )
        task_completed_daily = await daily_count_by(
            FlowTask, _task_match, FlowTask.end_at,
            *task_done_base, FlowTask.end_at.is_not(None),
        )
        bug_completed_daily = await daily_count_by(
            FlowBug, _bug_match, FlowBug.end_at,
            *bug_done_base, FlowBug.end_at.is_not(None),
        )

        # 创建数：在 history 窗口内创建的项（无论当前是否完成）。
        # 复用 done_base 的过滤维度但去掉 state 限制；成员匹配交给 match_fn。
        story_created_base = [
            FlowStory.is_archived.is_not(True),
            FlowStory.parent_id.is_(None),
            *story_proj,
            *story_iter,
        ]
        task_created_base = [
            FlowTask.is_archived.is_not(True),
            FlowTask.parent_id.is_(None),
            *task_proj,
            *task_iter,
        ]
        bug_created_base = [
            FlowBug.is_archived.is_not(True),
            *bug_proj,
            *bug_iter,
        ]
        story_created_daily = await daily_count_by(
            FlowStory, _story_match, FlowStory.created_at, *story_created_base,
        )
        task_created_daily = await daily_count_by(
            FlowTask, _task_match, FlowTask.created_at, *task_created_base,
        )
        bug_created_daily = await daily_count_by(
            FlowBug, _bug_match, FlowBug.created_at, *bug_created_base,
        )

        # ============ 停滞判定 ============
        # 与 helpers._attach_activity_info 注入的 last_activity_at 口径完全对齐：
        # last_activity_at = max(updated_at, last FlowEvent.created_at, last FlowComment.created_at)
        # 1) 拉所有在手项的 (entity_type, entity_id, owner, updated_at, deadline)
        # 2) 在 stale_cutoff 之后满足以下任一即视为活跃：
        #    - updated_at 在 cutoff 之后（覆盖那些没写 FlowEvent 的更新路径，如 story/task 创建）
        #    - 有 FlowEvent.created_at 在 cutoff 之后
        #    - 有 FlowComment.created_at 在 cutoff 之后
        # 3) 在手 - 活跃 - 已逾期 = 停滞（已逾期项已经被 overdue 标签计数，不重复展示）
        # pending_items 元组语义：(entity_type, entity_id, matched_member_id, updated_at, deadline)
        # 同一条工作项可能展开成多行（assignee + 多个协作者都在 ids 中时），
        # 让停滞 / 未来到期 / 当前逾期等指标按「成员视角」计入。
        pending_items: list[tuple[str, str, str, datetime | None, datetime | None]] = []

        def _expand(et: str, eid: str, owner: str | None, collabs_raw: str | None,
                    upd: datetime | None, dl: datetime | None) -> None:
            matched: set[str] = set()
            if owner and owner in ids_set:
                matched.add(owner)
            for c in _parse_collabs(collabs_raw):
                if c in ids_set:
                    matched.add(c)
            for m in matched:
                pending_items.append((et, eid, m, upd, dl))

        story_pending_rows = (await session.execute(
            select(
                FlowStory.id, story_owner, FlowStory.collaborators_json,
                FlowStory.updated_at, FlowStory.deadline, FlowStory.state,
            ).where(*story_base, _any_member_match(FlowStory, story_owner))
        )).all()
        for sid, owner, collabs_raw, upd, dl, state in story_pending_rows:
            # deadline 是开发排期；进入待测试或后续状态后，不再参与逾期/到期预测。
            deadline_for_risk = dl if state in STORY_DEVELOPMENT_PENDING_STATES else None
            _expand("story", sid, owner, collabs_raw, upd, deadline_for_risk)

        task_pending_rows = (await session.execute(
            select(
                FlowTask.id, task_owner, FlowTask.collaborators_json,
                FlowTask.updated_at, FlowTask.deadline,
            ).where(*task_base, _any_member_match(FlowTask, task_owner))
        )).all()
        for tid, owner, collabs_raw, upd, dl in task_pending_rows:
            _expand("task", tid, owner, collabs_raw, upd, dl)

        bug_pending_rows = (await session.execute(
            select(
                FlowBug.id, bug_owner, FlowBug.collaborators_json,
                FlowBug.updated_at, FlowBug.deadline,
            ).where(*bug_base, _any_member_match(FlowBug, bug_owner))
        )).all()
        for bid, owner, collabs_raw, upd, dl in bug_pending_rows:
            _expand("bug", bid, owner, collabs_raw, upd, dl)

        active_entities: set[tuple[str, str]] = set()
        # First pass: 用 updated_at 兜底，避免无 Event/Comment 但近期被更新的项误判
        for et, eid, _owner, upd, _dl in pending_items:
            if upd is not None and upd >= stale_cutoff:
                active_entities.add((et, eid))

        if pending_items:
            pending_ids_by_type: dict[str, set[str]] = {"story": set(), "task": set(), "bug": set()}
            for et, eid, _, _, _ in pending_items:
                pending_ids_by_type[et].add(eid)

            # 用 entity_id IN 限制扫描范围；FlowEvent / FlowComment 表通常较大，这步关键
            for et, id_set in pending_ids_by_type.items():
                if not id_set:
                    continue
                ev_rows = (await session.execute(
                    select(FlowEvent.entity_id).where(
                        FlowEvent.entity_type == et,
                        FlowEvent.entity_id.in_(id_set),
                        FlowEvent.created_at >= stale_cutoff,
                    ).distinct()
                )).all()
                for (eid,) in ev_rows:
                    active_entities.add((et, eid))

                cm_rows = (await session.execute(
                    select(FlowComment.entity_id).where(
                        FlowComment.entity_type == et,
                        FlowComment.entity_id.in_(id_set),
                        FlowComment.created_at >= stale_cutoff,
                    ).distinct()
                )).all()
                for (eid,) in cm_rows:
                    active_entities.add((et, eid))

        stale_per_member: dict[str, int] = {mid: 0 for mid in ids}
        for et, eid, owner, _upd, dl in pending_items:
            if (et, eid) in active_entities:
                continue
            # 已逾期项已经被 overdue 标签计数，不再重复列入 stale
            if dl is not None and dl < today_start:
                continue
            stale_per_member[owner] = stale_per_member.get(owner, 0) + 1

        # ============ 未来到期数（按 deadline 桶分到明天起的 forecast_days 天） ============
        # forecast_days 中第 i 项（0-based）对应「today_start + (i+1)..(i+2) 天」之间的 deadline
        # 即明天 = future_due[0]，后天 = future_due[1]，...
        # 当前已逾期项不计入未来桶，但作为 future_overdue_cumulative 的起点累加
        future_horizon = today_start + timedelta(days=forecast_days + 1)
        future_due_per_member: dict[str, list[int]] = {mid: [0] * forecast_days for mid in ids}
        currently_overdue_per_member: dict[str, int] = {mid: 0 for mid in ids}
        for _et, _eid, owner, _upd, dl in pending_items:
            if dl is None:
                continue
            if dl < today_start:
                currently_overdue_per_member[owner] = currently_overdue_per_member.get(owner, 0) + 1
                continue
            if dl >= future_horizon:
                continue
            # 桶 index = floor((dl - tomorrow) / 1 day)，明天落 0，后天落 1...
            tomorrow_start = today_start + timedelta(days=1)
            offset = (dl.date() - tomorrow_start.date()).days
            if 0 <= offset < forecast_days:
                arr = future_due_per_member.setdefault(owner, [0] * forecast_days)
                arr[offset] += 1

    # ============ 在 session 外组装结果 ============
    def _merge_daily(arr_dicts: Iterable[dict[str, list[int]]], mid: str) -> list[int]:
        merged = [0] * history_days
        for d in arr_dicts:
            arr = d.get(mid)
            if not arr:
                continue
            for i, v in enumerate(arr):
                merged[i] += int(v)
        return merged

    # 团队均值流转天数：合并所有人的 lead 数据后再算
    team_lead_seconds = 0.0
    team_lead_count = 0
    for d in (story_lead, task_lead, bug_lead):
        for _, (s, c) in d.items():
            team_lead_seconds += s
            team_lead_count += c
    team_avg_lead_days = (
        round(team_lead_seconds / team_lead_count / 86400, 2)
        if team_lead_count > 0 else 0.0
    )

    result = []
    for mid in ids:
        story_n = story_pending.get(mid, 0)
        task_n = task_pending.get(mid, 0)
        bug_n = bug_pending.get(mid, 0)

        completed_recent = (
            story_done_recent.get(mid, 0)
            + task_done_recent.get(mid, 0)
            + bug_done_recent.get(mid, 0)
        )
        completed_prev = (
            story_done_prev.get(mid, 0)
            + task_done_prev.get(mid, 0)
            + bug_done_prev.get(mid, 0)
        )

        s_sum, s_cnt = story_lead.get(mid, (0.0, 0))
        t_sum, t_cnt = task_lead.get(mid, (0.0, 0))
        b_sum, b_cnt = bug_lead.get(mid, (0.0, 0))
        total_sec = s_sum + t_sum + b_sum
        total_cnt = s_cnt + t_cnt + b_cnt
        avg_lead_days = (
            round(total_sec / total_cnt / 86400, 2)
            if total_cnt > 0 else 0.0
        )

        activity_arr = [
            (event_buckets.get(mid) or [0] * history_days)[i]
            + (comment_buckets.get(mid) or [0] * history_days)[i]
            for i in range(history_days)
        ]

        completed_daily = _merge_daily(
            (story_completed_daily, task_completed_daily, bug_completed_daily), mid,
        )
        created_daily = _merge_daily(
            (story_created_daily, task_created_daily, bug_created_daily), mid,
        )
        pending_total_now = story_n + task_n + bug_n
        # 反推每天结束时的在手数：history 窗口最后一天 = 今天
        pending_history: list[int] = []
        for i in range(history_days):
            # 从 i+1 天开始（含当天日终）到今天结束，期间完成数与创建数
            # 也即 completed_daily[i+1 .. history_days-1] 与 created_daily[i+1 .. history_days-1]
            completed_after = sum(completed_daily[i + 1:])
            created_after = sum(created_daily[i + 1:])
            pending_history.append(max(0, pending_total_now + completed_after - created_after))

        # 未来到期 + 累计逾期：以「今日已逾期数」为起点，按未来每天的到期数依次累加
        future_due_arr = future_due_per_member.get(mid, [0] * forecast_days)
        cur_overdue = currently_overdue_per_member.get(mid, 0)
        future_overdue_cum: list[int] = []
        running = cur_overdue
        for v in future_due_arr:
            running += int(v)
            future_overdue_cum.append(running)

        result.append({
            "member_id": mid,
            "pending_total": pending_total_now,
            "by_type": {"story": story_n, "task": task_n, "bug": bug_n},
            "overdue": (
                story_overdue.get(mid, 0)
                + task_overdue.get(mid, 0)
                + bug_overdue.get(mid, 0)
            ),
            "due_soon": (
                story_due_soon.get(mid, 0)
                + task_due_soon.get(mid, 0)
                + bug_due_soon.get(mid, 0)
            ),
            "urgent": story_urgent.get(mid, 0) + bug_urgent.get(mid, 0),

            # ===== 流速 =====
            "completed_recent": completed_recent,
            "completed_prev": completed_prev,
            "avg_lead_time_days": avg_lead_days,
            "team_avg_lead_time_days": team_avg_lead_days,

            # ===== 停滞（与 overdue 互斥）=====
            "stale_count": stale_per_member.get(mid, 0),

            # ===== 历史 =====
            "activity_7d": activity_arr,
            "pending_history_7d": pending_history,
            "daily_completed": completed_daily,
            "daily_created": created_daily,

            # ===== 未来 =====
            "future_due": future_due_arr,
            "future_overdue_cumulative": future_overdue_cum,
        })
    return result
