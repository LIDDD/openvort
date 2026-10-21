"""Iteration CRUD, Iteration Stories & Tasks."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, delete as sa_delete

from openvort.db.engine import get_session_factory
from openvort.plugins.vortflow.models import (
    FlowIteration, FlowIterationStory, FlowIterationTask, FlowIterationBug,
    FlowStory, FlowTask, FlowBug,
)
from openvort.plugins.vortflow.engine import (
    STORY_DONE_STATES, TASK_DONE_STATES, BUG_CLOSED_STATES,
)
from .helpers import _iteration_dict, _log_event, _parse_dt, _story_dict, _task_dict, _bug_dict, resolve_project_ids, _attach_project_names
from .schemas import (
    IterationCreate, IterationUpdate, IterationStoryBody, IterationTaskBody, IterationBugBody,
)

sub_router = APIRouter()


# ============ Iteration CRUD ============

@sub_router.get("/iterations")
async def list_iterations(
    project_id: str = Query("", description="按项目过滤（单个）"),
    project_ids: str = Query("", description="按项目过滤（逗号分隔多选，优先于 project_id）"),
    status: str = Query("", description="按状态过滤"),
    keyword: str = Query("", description="按名称/目标搜索"),
    owner_id: str = Query("", description="按负责人过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    sf = get_session_factory()
    async with sf() as session:
        # 分页加载依赖稳定顺序；仅按日期排序时同日期/空日期记录在不同请求间
        # 可能换位，导致分页结果重复或漏掉迭代。ID 作为次排序键保证翻页顺序稳定。
        stmt = select(FlowIteration).order_by(
            FlowIteration.start_date.desc().nulls_last(),
            FlowIteration.id.asc(),
        )
        count_stmt = select(func.count()).select_from(FlowIteration)
        pids = resolve_project_ids(project_id, project_ids)
        if pids:
            stmt = stmt.where(FlowIteration.project_id.in_(pids))
            count_stmt = count_stmt.where(FlowIteration.project_id.in_(pids))
        if status:
            stmt = stmt.where(FlowIteration.status == status)
            count_stmt = count_stmt.where(FlowIteration.status == status)
        if keyword:
            like = f"%{keyword}%"
            cond = FlowIteration.name.ilike(like) | FlowIteration.goal.ilike(like)
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        if owner_id:
            stmt = stmt.where(FlowIteration.owner_id == owner_id)
            count_stmt = count_stmt.where(FlowIteration.owner_id == owner_id)
        total = (await session.execute(count_stmt)).scalar_one()
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()

        iter_ids = [r.id for r in rows]
        story_stats: dict[str, dict[str, int]] = {}
        task_stats: dict[str, dict[str, int]] = {}
        bug_stats: dict[str, dict[str, int]] = {}
        if iter_ids:
            for iter_id, cnt in (await session.execute(
                select(FlowIterationStory.iteration_id, func.count())
                .where(FlowIterationStory.iteration_id.in_(iter_ids))
                .group_by(FlowIterationStory.iteration_id)
            )):
                story_stats.setdefault(iter_id, {"total": 0, "done": 0})["total"] = cnt
            for iter_id, cnt in (await session.execute(
                select(FlowIterationStory.iteration_id, func.count())
                .join(FlowStory, FlowIterationStory.story_id == FlowStory.id)
                .where(FlowIterationStory.iteration_id.in_(iter_ids), FlowStory.state.in_(STORY_DONE_STATES))
                .group_by(FlowIterationStory.iteration_id)
            )):
                story_stats.setdefault(iter_id, {"total": 0, "done": 0})["done"] = cnt
            for iter_id, cnt in (await session.execute(
                select(FlowIterationTask.iteration_id, func.count())
                .where(FlowIterationTask.iteration_id.in_(iter_ids))
                .group_by(FlowIterationTask.iteration_id)
            )):
                task_stats.setdefault(iter_id, {"total": 0, "done": 0})["total"] = cnt
            for iter_id, cnt in (await session.execute(
                select(FlowIterationTask.iteration_id, func.count())
                .join(FlowTask, FlowIterationTask.task_id == FlowTask.id)
                .where(FlowIterationTask.iteration_id.in_(iter_ids), FlowTask.state.in_(TASK_DONE_STATES))
                .group_by(FlowIterationTask.iteration_id)
            )):
                task_stats.setdefault(iter_id, {"total": 0, "done": 0})["done"] = cnt
            for iter_id, cnt in (await session.execute(
                select(FlowIterationBug.iteration_id, func.count())
                .where(FlowIterationBug.iteration_id.in_(iter_ids))
                .group_by(FlowIterationBug.iteration_id)
            )):
                bug_stats.setdefault(iter_id, {"total": 0, "done": 0})["total"] = cnt
            for iter_id, cnt in (await session.execute(
                select(FlowIterationBug.iteration_id, func.count())
                .join(FlowBug, FlowIterationBug.bug_id == FlowBug.id)
                .where(FlowIterationBug.iteration_id.in_(iter_ids), FlowBug.state.in_(BUG_CLOSED_STATES))
                .group_by(FlowIterationBug.iteration_id)
            )):
                bug_stats.setdefault(iter_id, {"total": 0, "done": 0})["done"] = cnt

        items = []
        for r in rows:
            d = _iteration_dict(r)
            s = story_stats.get(r.id, {"total": 0, "done": 0})
            t = task_stats.get(r.id, {"total": 0, "done": 0})
            b = bug_stats.get(r.id, {"total": 0, "done": 0})
            d["work_item_total"] = s["total"] + t["total"] + b["total"]
            d["work_item_done"] = s["done"] + t["done"] + b["done"]
            items.append(d)
        await _attach_project_names(session, items)
    return {"total": total, "items": items}


@sub_router.get("/iterations/{iteration_id}")
async def get_iteration(iteration_id: str):
    sf = get_session_factory()
    async with sf() as session:
        r = await session.get(FlowIteration, iteration_id)
        if not r:
            raise HTTPException(status_code=404, detail="迭代不存在")
    return _iteration_dict(r)


@sub_router.post("/iterations")
async def create_iteration(body: IterationCreate):
    sf = get_session_factory()
    async with sf() as session:
        i = FlowIteration(
            project_id=body.project_id, name=body.name, goal=body.goal,
            owner_id=body.owner_id,
            start_date=_parse_dt(body.start_date), end_date=_parse_dt(body.end_date),
            status=body.status,
            estimate_hours=body.estimate_hours,
        )
        session.add(i)
        await session.flush()
        await _log_event(session, "iteration", i.id, "created", {"name": body.name})
        await session.commit()
        await session.refresh(i)
    return _iteration_dict(i)


@sub_router.put("/iterations/{iteration_id}")
async def update_iteration(iteration_id: str, body: IterationUpdate):
    sf = get_session_factory()
    async with sf() as session:
        i = await session.get(FlowIteration, iteration_id)
        if not i:
            raise HTTPException(status_code=404, detail="迭代不存在")
        changes = {}
        for field in ["name", "goal", "status", "owner_id", "estimate_hours"]:
            val = getattr(body, field)
            if val is not None:
                old_val = getattr(i, field)
                changes[field] = {"from": old_val, "to": val}
                setattr(i, field, val)
        if body.start_date is not None:
            old_val = str(i.start_date) if i.start_date else None
            i.start_date = _parse_dt(body.start_date)
            changes["start_date"] = {"from": old_val, "to": body.start_date}
        if body.end_date is not None:
            old_val = str(i.end_date) if i.end_date else None
            i.end_date = _parse_dt(body.end_date)
            changes["end_date"] = {"from": old_val, "to": body.end_date}
        if changes:
            await _log_event(session, "iteration", iteration_id, "updated", changes)
        await session.commit()
        await session.refresh(i)
    return _iteration_dict(i)


@sub_router.delete("/iterations/{iteration_id}")
async def delete_iteration(iteration_id: str):
    sf = get_session_factory()
    async with sf() as session:
        i = await session.get(FlowIteration, iteration_id)
        if not i:
            raise HTTPException(status_code=404, detail="迭代不存在")
        await session.execute(sa_delete(FlowIterationStory).where(FlowIterationStory.iteration_id == iteration_id))
        await session.execute(sa_delete(FlowIterationTask).where(FlowIterationTask.iteration_id == iteration_id))
        await session.execute(sa_delete(FlowIterationBug).where(FlowIterationBug.iteration_id == iteration_id))
        await session.delete(i)
        await _log_event(session, "iteration", iteration_id, "deleted", {"name": i.name})
        await session.commit()
    return {"ok": True}


@sub_router.get("/iterations/{iteration_id}/health")
async def iteration_health(iteration_id: str):
    """迭代健康度：时间进度 / 完成度 / scope creep / 未估时数 / Top 贡献者。

    给工作墙的 IterationHealthBar 用。
    """
    from openvort.contacts.models import Member

    sf = get_session_factory()
    async with sf() as session:
        iteration = await session.get(FlowIteration, iteration_id)
        if not iteration:
            raise HTTPException(status_code=404, detail="迭代不存在")

        now = datetime.now()
        start = iteration.start_date
        end = iteration.end_date

        # 时间进度（按整天计算）。无 start/end 时 duration_days=0，前端按"未排期"处理
        if start and end:
            duration_days = max(1, (end.date() - start.date()).days + 1)
            elapsed_days = max(0, min(duration_days, (now.date() - start.date()).days + 1))
        else:
            duration_days = 0
            elapsed_days = 0

        # 工作项总数与完成数
        async def count_total_done(link_table, link_id_attr, item_table, done_states):
            total = (await session.execute(
                select(func.count())
                .select_from(link_table)
                .where(link_table.iteration_id == iteration_id)
            )).scalar_one()
            done = (await session.execute(
                select(func.count())
                .select_from(link_table)
                .join(item_table, link_id_attr == item_table.id)
                .where(
                    link_table.iteration_id == iteration_id,
                    item_table.is_archived.is_not(True),
                    item_table.state.in_(done_states),
                )
            )).scalar_one()
            return total, done

        story_total, story_done = await count_total_done(
            FlowIterationStory, FlowIterationStory.story_id, FlowStory, STORY_DONE_STATES
        )
        task_total, task_done = await count_total_done(
            FlowIterationTask, FlowIterationTask.task_id, FlowTask, TASK_DONE_STATES
        )
        bug_total, bug_done = await count_total_done(
            FlowIterationBug, FlowIterationBug.bug_id, FlowBug, BUG_CLOSED_STATES
        )

        total = story_total + task_total + bug_total
        done = story_done + task_done + bug_done

        # scope creep：迭代开始日之后被加进来的工作项数（关联表 created_at > start_date）
        if start:
            creep_count = 0
            for link_table in (FlowIterationStory, FlowIterationTask, FlowIterationBug):
                cnt = (await session.execute(
                    select(func.count())
                    .select_from(link_table)
                    .where(
                        link_table.iteration_id == iteration_id,
                        link_table.created_at > start,
                    )
                )).scalar_one()
                creep_count += cnt
        else:
            creep_count = 0

        # 未估时：迭代内 task.estimate_hours IS NULL 的数量（仅 task 强制要估时）
        not_estimated_count = (await session.execute(
            select(func.count())
            .select_from(FlowIterationTask)
            .join(FlowTask, FlowIterationTask.task_id == FlowTask.id)
            .where(
                FlowIterationTask.iteration_id == iteration_id,
                FlowTask.is_archived.is_not(True),
                FlowTask.estimate_hours.is_(None),
            )
        )).scalar_one()

        # Top 贡献者：按 done desc 取前 3
        # owner 口径与 work-items / members_workload 一致：
        # - 需求 owner = coalesce(nullif(assignee_id,''), pm_id)
        # - 任务 owner = assignee_id
        # - 缺陷 owner = coalesce(nullif(assignee_id,''), developer_id)
        story_owner = func.coalesce(func.nullif(FlowStory.assignee_id, ""), FlowStory.pm_id)
        task_owner = FlowTask.assignee_id
        bug_owner = func.coalesce(func.nullif(FlowBug.assignee_id, ""), FlowBug.developer_id)

        async def by_owner(owner_col, link_table, link_id_attr, item_table, done_states):
            """返回 (total_map, done_map): owner_id -> count"""
            base = (
                select(owner_col, func.count())
                .select_from(link_table)
                .join(item_table, link_id_attr == item_table.id)
                .where(
                    link_table.iteration_id == iteration_id,
                    item_table.is_archived.is_not(True),
                    owner_col.is_not(None),
                )
                .group_by(owner_col)
            )
            total_rows = (await session.execute(base)).all()
            done_rows = (await session.execute(
                base.where(item_table.state.in_(done_states))
            )).all()
            return (
                {r[0]: r[1] for r in total_rows if r[0]},
                {r[0]: r[1] for r in done_rows if r[0]},
            )

        s_total_by, s_done_by = await by_owner(
            story_owner, FlowIterationStory, FlowIterationStory.story_id, FlowStory, STORY_DONE_STATES
        )
        t_total_by, t_done_by = await by_owner(
            task_owner, FlowIterationTask, FlowIterationTask.task_id, FlowTask, TASK_DONE_STATES
        )
        b_total_by, b_done_by = await by_owner(
            bug_owner, FlowIterationBug, FlowIterationBug.bug_id, FlowBug, BUG_CLOSED_STATES
        )

        all_owner_ids = set(s_total_by) | set(t_total_by) | set(b_total_by)
        contrib = []
        for oid in all_owner_ids:
            ot = s_total_by.get(oid, 0) + t_total_by.get(oid, 0) + b_total_by.get(oid, 0)
            od = s_done_by.get(oid, 0) + t_done_by.get(oid, 0) + b_done_by.get(oid, 0)
            contrib.append({"member_id": oid, "total": ot, "done": od})

        # 排序：done desc，再按 total desc，再按 member_id 稳定
        contrib.sort(key=lambda x: (-x["done"], -x["total"], x["member_id"]))
        top3 = contrib[:3]

        if top3:
            top_ids = [c["member_id"] for c in top3]
            members = (await session.execute(
                select(Member.id, Member.name).where(Member.id.in_(top_ids))
            )).all()
            name_map = {m[0]: m[1] for m in members}
            for c in top3:
                c["name"] = name_map.get(c["member_id"]) or c["member_id"][:6]

    return {
        "id": iteration.id,
        "name": iteration.name,
        "status": iteration.status,
        "start_date": iteration.start_date.isoformat() if iteration.start_date else None,
        "end_date": iteration.end_date.isoformat() if iteration.end_date else None,
        "duration_days": duration_days,
        "elapsed_days": elapsed_days,
        "total": total,
        "done": done,
        "by_type": {
            "story": {"total": story_total, "done": story_done},
            "task": {"total": task_total, "done": task_done},
            "bug": {"total": bug_total, "done": bug_done},
        },
        "creep_count": creep_count,
        "not_estimated_count": not_estimated_count,
        "top_contributors": top3,
    }


# ---- Iteration Stories ----

@sub_router.get("/iterations/{iteration_id}/stories")
async def list_iteration_stories(iteration_id: str):
    sf = get_session_factory()
    async with sf() as session:
        stmt = (
            select(FlowIterationStory, FlowStory)
            .join(FlowStory, FlowIterationStory.story_id == FlowStory.id)
            .where(FlowIterationStory.iteration_id == iteration_id)
            .order_by(FlowIterationStory.story_order.asc())
        )
        rows = await session.execute(stmt)
        items = []
        for link, story in rows:
            items.append({
                "link_id": link.id,
                "story_order": link.story_order,
                **_story_dict(story),
            })
    return {"items": items}


@sub_router.post("/iterations/{iteration_id}/stories")
async def add_iteration_story(iteration_id: str, body: IterationStoryBody):
    sf = get_session_factory()
    async with sf() as session:
        iteration = await session.get(FlowIteration, iteration_id)
        if not iteration:
            raise HTTPException(status_code=404, detail="迭代不存在")
        story = await session.get(FlowStory, body.story_id)
        if not story:
            raise HTTPException(status_code=404, detail="需求不存在")
        existing = await session.execute(
            select(FlowIterationStory).where(
                FlowIterationStory.iteration_id == iteration_id,
                FlowIterationStory.story_id == body.story_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="需求已在迭代中")
        link = FlowIterationStory(
            iteration_id=iteration_id, story_id=body.story_id,
            story_order=body.story_order,
        )
        session.add(link)
        await _log_event(session, "iteration", iteration_id, "story_added",
                         {"story_id": body.story_id})
        await session.commit()
    return {"ok": True}


@sub_router.delete("/iterations/{iteration_id}/stories/{story_id}")
async def remove_iteration_story(iteration_id: str, story_id: str):
    sf = get_session_factory()
    async with sf() as session:
        await session.execute(
            sa_delete(FlowIterationStory).where(
                FlowIterationStory.iteration_id == iteration_id,
                FlowIterationStory.story_id == story_id,
            )
        )
        await _log_event(session, "iteration", iteration_id, "story_removed",
                         {"story_id": story_id})
        await session.commit()
    return {"ok": True}


# ---- Iteration Tasks ----

@sub_router.get("/iterations/{iteration_id}/tasks")
async def list_iteration_tasks(iteration_id: str):
    sf = get_session_factory()
    async with sf() as session:
        stmt = (
            select(FlowIterationTask, FlowTask)
            .join(FlowTask, FlowIterationTask.task_id == FlowTask.id)
            .where(FlowIterationTask.iteration_id == iteration_id)
            .order_by(FlowIterationTask.task_order.asc())
        )
        rows = await session.execute(stmt)
        items = []
        for link, task in rows:
            items.append({
                "link_id": link.id,
                "task_order": link.task_order,
                **_task_dict(task),
            })
    return {"items": items}


@sub_router.post("/iterations/{iteration_id}/tasks")
async def add_iteration_task(iteration_id: str, body: IterationTaskBody):
    sf = get_session_factory()
    async with sf() as session:
        iteration = await session.get(FlowIteration, iteration_id)
        if not iteration:
            raise HTTPException(status_code=404, detail="迭代不存在")
        task = await session.get(FlowTask, body.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        existing = await session.execute(
            select(FlowIterationTask).where(
                FlowIterationTask.iteration_id == iteration_id,
                FlowIterationTask.task_id == body.task_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="任务已在迭代中")
        link = FlowIterationTask(
            iteration_id=iteration_id, task_id=body.task_id,
            task_order=body.task_order,
        )
        session.add(link)
        await _log_event(session, "iteration", iteration_id, "task_added",
                         {"task_id": body.task_id})
        await session.commit()
    return {"ok": True}


@sub_router.delete("/iterations/{iteration_id}/tasks/{task_id}")
async def remove_iteration_task(iteration_id: str, task_id: str):
    sf = get_session_factory()
    async with sf() as session:
        await session.execute(
            sa_delete(FlowIterationTask).where(
                FlowIterationTask.iteration_id == iteration_id,
                FlowIterationTask.task_id == task_id,
            )
        )
        await _log_event(session, "iteration", iteration_id, "task_removed",
                         {"task_id": task_id})
        await session.commit()
    return {"ok": True}


# ---- Iteration Bugs ----

@sub_router.post("/iterations/{iteration_id}/bugs")
async def add_iteration_bug(iteration_id: str, body: IterationBugBody):
    sf = get_session_factory()
    async with sf() as session:
        iteration = await session.get(FlowIteration, iteration_id)
        if not iteration:
            raise HTTPException(status_code=404, detail="迭代不存在")
        bug = await session.get(FlowBug, body.bug_id)
        if not bug:
            raise HTTPException(status_code=404, detail="缺陷不存在")
        existing = await session.execute(
            select(FlowIterationBug).where(
                FlowIterationBug.iteration_id == iteration_id,
                FlowIterationBug.bug_id == body.bug_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="缺陷已在迭代中")
        link = FlowIterationBug(
            iteration_id=iteration_id, bug_id=body.bug_id,
            bug_order=body.bug_order,
        )
        session.add(link)
        await _log_event(session, "iteration", iteration_id, "bug_added",
                         {"bug_id": body.bug_id})
        await session.commit()
    return {"ok": True}


@sub_router.delete("/iterations/{iteration_id}/bugs/{bug_id}")
async def remove_iteration_bug(iteration_id: str, bug_id: str):
    sf = get_session_factory()
    async with sf() as session:
        await session.execute(
            sa_delete(FlowIterationBug).where(
                FlowIterationBug.iteration_id == iteration_id,
                FlowIterationBug.bug_id == bug_id,
            )
        )
        await _log_event(session, "iteration", iteration_id, "bug_removed",
                         {"bug_id": bug_id})
        await session.commit()
    return {"ok": True}
