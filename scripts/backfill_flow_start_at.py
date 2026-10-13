"""回填 vortflow 已完成工作项缺失的 start_at。

背景：之前的状态机只在切到 IN_PROGRESS / FIXING 时才回填 start_at，
若工作项被直接从 todo 类状态拖到完成态（跳过"进行中"），start_at 仍为 NULL，
导致成员工作量面板"平均流转"无法统计。

修复策略（按优先级）：

1. 从 FlowEvent (action='state_changed') 中找该工作项**首次进入"工作中"状态**
   的事件 created_at 作为 start_at；
   - story: 首次切到 in_progress / testing / bugfix
   - task: 首次切到 in_progress
   - bug: 首次切到 fixing
2. 若 1 未命中，使用该工作项**最早一次 state_changed** 事件的 created_at
   （任何状态变更都意味着这个工作项已被处理，比 created_at 更接近真实"开始时刻"）
3. 兜底使用工作项的 created_at（lead time 退化为创建到完成）

并做安全裁剪：start_at 不晚于 end_at。

用法：

    # 只看影响范围，不写库
    python scripts/backfill_flow_start_at.py --dry-run

    # 实际写库
    python scripts/backfill_flow_start_at.py

    # 限定项目（可选）
    python scripts/backfill_flow_start_at.py --project-id <pid>

注意：脚本仅回填 state in *_DONE_STATES 且 end_at IS NOT NULL 的项；
未完成项不动（它们将来由新版 transition 自动维护）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openvort.config.settings import Settings
from openvort.db.engine import close_db, get_session_factory, init_db
from openvort.plugins.vortflow.engine import (
    BUG_CLOSED_STATES,
    STORY_DONE_STATES,
    TASK_DONE_STATES,
)
from openvort.plugins.vortflow.models import (
    FlowBug,
    FlowEvent,
    FlowStory,
    FlowTask,
)

# 各类工作项的"已开始干活"状态集合，命中即视为真正进入处理流程
STORY_WORKING_STATES: set[str] = {"in_progress", "testing", "bugfix"}
TASK_WORKING_STATES: set[str] = {"in_progress"}
BUG_WORKING_STATES: set[str] = {"fixing"}


@dataclass
class BackfillStats:
    """单种工作项的回填统计"""

    entity_type: str
    total_completed_missing: int = 0  # 已完成且 start_at 缺失
    from_working_event: int = 0       # 来自方案 1
    from_first_event: int = 0          # 来自方案 2
    from_created_at: int = 0           # 来自方案 3
    skipped_no_end_at: int = 0         # 已完成但 end_at 也缺失，跳过
    clipped_to_end_at: int = 0         # 候选时间晚于 end_at，做了裁剪
    samples: list[dict[str, Any]] = field(default_factory=list)

    def add_sample(self, entry_id: str, source: str, picked: datetime, end_at: datetime) -> None:
        if len(self.samples) >= 5:
            return
        self.samples.append({
            "id": entry_id,
            "source": source,
            "picked_start_at": picked.isoformat(timespec="seconds"),
            "end_at": end_at.isoformat(timespec="seconds"),
            "lead_days": round((end_at - picked).total_seconds() / 86400, 2),
        })

    def report(self) -> None:
        print(f"\n=== {self.entity_type} ===")
        print(f"待回填 (state=DONE, start_at IS NULL): {self.total_completed_missing}")
        print(f"  - 来源 FlowEvent[首次进入工作中态]: {self.from_working_event}")
        print(f"  - 来源 FlowEvent[最早一次状态变更]: {self.from_first_event}")
        print(f"  - 兜底使用 created_at:             {self.from_created_at}")
        print(f"  - 因 start_at 晚于 end_at 被裁剪: {self.clipped_to_end_at}")
        print(f"  - 跳过（end_at 也缺失）:           {self.skipped_no_end_at}")
        if self.samples:
            print("  样本:")
            for s in self.samples:
                print(f"    {s}")


async def _collect_events(
    session, entity_type: str, ids: list[str],
) -> dict[str, list[tuple[datetime, str]]]:
    """批量取这些工作项的 state_changed 事件，返回 {id: [(created_at, to_state), ...]} 按时间升序"""
    if not ids:
        return {}
    rows = (await session.execute(
        select(FlowEvent.entity_id, FlowEvent.created_at, FlowEvent.detail)
        .where(
            FlowEvent.entity_type == entity_type,
            FlowEvent.action == "state_changed",
            FlowEvent.entity_id.in_(ids),
        )
        .order_by(FlowEvent.created_at.asc())
    )).all()
    bucket: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for entity_id, created_at, detail in rows:
        to_state = ""
        if detail:
            try:
                to_state = (json.loads(detail) or {}).get("to") or ""
            except (ValueError, TypeError):
                to_state = ""
        bucket[entity_id].append((created_at, to_state))
    return bucket


def _pick_start_at(
    events: list[tuple[datetime, str]],
    working_states: set[str],
    created_at: datetime,
) -> tuple[datetime, str]:
    """按优先级选 start_at，返回 (时间, 来源标签)"""
    for ts, to_state in events:
        if to_state in working_states:
            return ts, "working_event"
    if events:
        return events[0][0], "first_event"
    return created_at, "created_at"


async def _backfill_kind(
    session,
    *,
    model,
    entity_type: str,
    done_states: set[str],
    working_states: set[str],
    project_id: str | None,
    dry_run: bool,
) -> BackfillStats:
    stats = BackfillStats(entity_type=entity_type)

    where = [
        model.state.in_(done_states),
        model.start_at.is_(None),
    ]
    if project_id:
        where.append(model.project_id == project_id)

    items = (await session.execute(select(model).where(*where))).scalars().all()
    if not items:
        return stats

    item_ids = [it.id for it in items]
    events_map = await _collect_events(session, entity_type, item_ids)

    for it in items:
        if it.end_at is None:
            stats.skipped_no_end_at += 1
            continue
        stats.total_completed_missing += 1

        events = events_map.get(it.id, [])
        picked, source = _pick_start_at(events, working_states, it.created_at)

        if picked > it.end_at:
            picked = it.end_at
            stats.clipped_to_end_at += 1

        if source == "working_event":
            stats.from_working_event += 1
        elif source == "first_event":
            stats.from_first_event += 1
        else:
            stats.from_created_at += 1
        stats.add_sample(it.id, source, picked, it.end_at)

        if not dry_run:
            it.start_at = picked

    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description="回填 vortflow 已完成工作项缺失的 start_at")
    parser.add_argument("--dry-run", action="store_true", help="仅打印影响范围，不写库")
    parser.add_argument("--project-id", default="", help="可选：仅处理指定项目")
    parser.add_argument(
        "--kind", choices=["all", "story", "task", "bug"], default="all",
        help="只处理某一种工作项",
    )
    args = parser.parse_args()

    settings = Settings()
    await init_db(settings.database_url)
    sf = get_session_factory()

    project_id = args.project_id or None
    overall: list[BackfillStats] = []

    try:
        async with sf() as session:
            if args.kind in ("all", "story"):
                overall.append(await _backfill_kind(
                    session,
                    model=FlowStory,
                    entity_type="story",
                    done_states=STORY_DONE_STATES,
                    working_states=STORY_WORKING_STATES,
                    project_id=project_id,
                    dry_run=args.dry_run,
                ))
            if args.kind in ("all", "task"):
                overall.append(await _backfill_kind(
                    session,
                    model=FlowTask,
                    entity_type="task",
                    done_states=TASK_DONE_STATES,
                    working_states=TASK_WORKING_STATES,
                    project_id=project_id,
                    dry_run=args.dry_run,
                ))
            if args.kind in ("all", "bug"):
                overall.append(await _backfill_kind(
                    session,
                    model=FlowBug,
                    entity_type="bug",
                    done_states=BUG_CLOSED_STATES,
                    working_states=BUG_WORKING_STATES,
                    project_id=project_id,
                    dry_run=args.dry_run,
                ))

            if not args.dry_run:
                await session.commit()

        print("\n" + "=" * 60)
        print("回填报告" + ("（DRY RUN，未写库）" if args.dry_run else "（已提交）"))
        if project_id:
            print(f"项目过滤: {project_id}")
        print("=" * 60)
        for s in overall:
            s.report()
        total = sum(s.total_completed_missing for s in overall)
        print("\n" + "-" * 60)
        print(f"合计回填 {total} 条")
        if args.dry_run:
            print("如确认无误，去掉 --dry-run 重新执行即可写入数据库。")
    finally:
        await close_db()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
