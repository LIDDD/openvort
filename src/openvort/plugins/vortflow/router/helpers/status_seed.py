"""工作项状态种子数据与运行时同步逻辑。

# 状态机概念分层

VortFlow 的状态体系实际有两层：

1. **engine state（机器粒度）**——`engine.py` 中的 ``StoryState`` / ``TaskState`` /
   ``BugState`` 枚举值（如 ``submitted`` / ``intake`` / ``review`` / ``pm_refine`` /
   ``design`` 等），这是状态机内部转换的最小单元，由 ``*_TRANSITIONS`` 表定义合法跳转。
2. **UI status（展示粒度）**——前端"状态下拉"看到的中文名（如 ``"意向"`` / ``"设计中"`` /
   ``"开发中"``）。一个 UI status 可对应**多个** engine state，例如 ``"开发中"`` 同时
   覆盖 ``breakdown,dev_assign,in_progress,bugfix`` 四个引擎状态。

两层之间的映射定义在 ``_STATUS_DEFAULTS`` 中的 ``command`` 字段（多 engine state 用
逗号分隔）。这种"展示粒度粗于机器粒度"是产品决定，不能机器派生。

# 三轨同步现状（阶段 F.1 已校验）

- ``engine.py`` 是 engine state 的唯一真相
- ``_STATUS_DEFAULTS`` 是 UI status 与 engine state 映射的唯一真相
- ``flow_statuses`` DB 表是 ``_STATUS_DEFAULTS`` 的运行时副本，用户可定制 icon/color/中文名

启动时 ``_validate_status_engine_state_mapping()`` 强制校验 ``_STATUS_DEFAULTS``
所有 ``command`` 引用的 engine state 必须真实存在于 engine.py，避免新加状态时
漏配置。``_STATUS_LEGACY_COMMANDS`` 是历史脏数据兜底，用于把老环境 DB 里残留
的旧 command 值升级为新值，未来所有环境升级稳定后可下线（见模块底部 TODO）。
"""

import json

from sqlalchemy import func, select

from openvort.plugins.vortflow.models import FlowStatus

from .parsers import _parse_json_list


# ---------------------------------------------------------------------------
# Status defaults: UI status name → engine state(s) + 展示元信息
# ---------------------------------------------------------------------------
_STATUS_DEFAULTS: list[dict] = [
    {"name": "收集中", "icon": "◇", "icon_color": "#94a3b8", "command": "submitted", "work_item_types": ["需求"]},
    {"name": "意向", "icon": "○", "icon_color": "#64748b", "command": "intake,review", "work_item_types": ["需求"]},
    {"name": "已拒绝", "icon": "⊗", "icon_color": "#ef4444", "command": "rejected", "work_item_types": []},
    {"name": "设计中", "icon": "✎", "icon_color": "#6366f1", "command": "pm_refine,design", "work_item_types": ["需求"]},
    {"name": "设计完成", "icon": "✓", "icon_color": "#0284c7", "command": "design_done", "work_item_types": ["需求"]},
    {"name": "待开发", "icon": "◉", "icon_color": "#a855f7", "command": "pending_dev", "work_item_types": ["需求"]},
    {"name": "开发中", "icon": "◔", "icon_color": "#3b82f6", "command": "breakdown,dev_assign,in_progress,bugfix", "work_item_types": ["需求"]},
    {"name": "开发完成", "icon": "✓", "icon_color": "#22c55e", "command": "dev_done", "work_item_types": ["需求"]},
    {"name": "测试中", "icon": "⊠", "icon_color": "#ef4444", "command": "testing", "work_item_types": ["需求"]},
    {"name": "测试完成", "icon": "✓", "icon_color": "#7c3aed", "command": "test_done", "work_item_types": ["需求"]},
    {"name": "已测完回归中", "icon": "◔", "icon_color": "#3b82f6", "command": "regression", "work_item_types": ["需求"]},
    {"name": "待发布", "icon": "◔", "icon_color": "#f59e0b", "command": "pending_release", "work_item_types": ["需求"]},
    {"name": "发布完成", "icon": "✓", "icon_color": "#22c55e", "command": "released", "work_item_types": ["需求"]},
    {"name": "已完成", "icon": "✓", "icon_color": "#22c55e", "command": "done", "work_item_types": ["任务", "需求"]},
    {"name": "已取消", "icon": "⊗", "icon_color": "#ef4444", "command": "rejected,closed", "work_item_types": ["任务", "需求"]},
    {"name": "暂搁置", "icon": "⊠", "icon_color": "#64748b", "command": "suspended", "work_item_types": ["需求", "缺陷"]},
    {"name": "待办的", "icon": "○", "icon_color": "#64748b", "command": "todo", "work_item_types": ["任务"]},
    {"name": "进行中", "icon": "◔", "icon_color": "#3b82f6", "command": "in_progress", "work_item_types": ["任务"]},
    {"name": "已验收", "icon": "✓", "icon_color": "#22c55e", "command": "", "work_item_types": []},
    {"name": "待确认", "icon": "○", "icon_color": "#64748b", "command": "open,confirmed", "work_item_types": ["缺陷"]},
    {"name": "已确认", "icon": "○", "icon_color": "#64748b", "command": "confirmed", "work_item_types": []},
    {"name": "修复中", "icon": "◔", "icon_color": "#3b82f6", "command": "fixing", "work_item_types": ["缺陷"]},
    {"name": "已修复", "icon": "✓", "icon_color": "#3b82f6", "command": "resolved", "work_item_types": ["缺陷"]},
    {"name": "已关闭", "icon": "✓", "icon_color": "#64748b", "command": "verified,closed", "work_item_types": ["缺陷"]},
    {"name": "无法复现", "icon": "◔", "icon_color": "#f59e0b", "command": "not_reproducible", "work_item_types": ["缺陷"]},
    {"name": "再次打开", "icon": "⊗", "icon_color": "#ef4444", "command": "reopened", "work_item_types": ["缺陷"]},
    {"name": "设计如此", "icon": "⊠", "icon_color": "#f59e0b", "command": "by_design", "work_item_types": ["缺陷"]},
    {"name": "延期修复", "icon": "▷", "icon_color": "#3b82f6", "command": "deferred", "work_item_types": ["缺陷"]},
    {"name": "待测试", "icon": "circle-minus", "icon_color": "#22d3ee", "command": "pending_test", "work_item_types": ["需求"]},
]

_STATUS_DEFAULTS_BY_NAME: dict[str, dict] = {s["name"]: s for s in _STATUS_DEFAULTS}
_STATUS_COMMAND_MAP: dict[str, str] = {s["name"]: s["command"] for s in _STATUS_DEFAULTS}

# 阶段 F.2（2026-05-07）已删除：原 _STATUS_LEGACY_COMMANDS 用于把 DB 中的历史 command 值
# 在启动时纠正为新值（例如 "测试完成" command="testing" → "test_done"）。
# 校验所有部署环境后确认 flow_statuses 都已升级到当前 _STATUS_COMMAND_MAP 期望值，
# 兜底逻辑下线，避免给新加的状态再叠加 legacy 升级路径。
# 如果未来又出现旧 command 残留，应当通过一次性 SQL 修正而非运行时兜底。


# ---------------------------------------------------------------------------
# F.1 阶段：启动时校验「UI status command 必须引用合法 engine state」
# ---------------------------------------------------------------------------
def _validate_status_engine_state_mapping() -> None:
    """启动时强制校验 _STATUS_DEFAULTS 中所有 command 引用的 engine state 真实存在。

    避免「加新状态时改了 _STATUS_DEFAULTS 但忘改 engine.py」的双轨漂移——
    任何不一致都会让模块 import 失败，将问题前置到启动阶段而非运行时。
    """
    from openvort.plugins.vortflow.engine import BugState, StoryState, TaskState

    all_engine_states: set[str] = (
        {s.value for s in StoryState}
        | {s.value for s in TaskState}
        | {s.value for s in BugState}
    )

    errors: list[str] = []
    for entry in _STATUS_DEFAULTS:
        command = entry.get("command", "")
        if not command:
            continue
        for cmd in command.split(","):
            cmd = cmd.strip()
            if not cmd:
                continue
            if cmd not in all_engine_states:
                errors.append(
                    f"_STATUS_DEFAULTS[{entry['name']!r}].command 引用了未知 engine state: {cmd!r}"
                )

    if errors:
        raise ValueError(
            "vortflow status seed 与 engine 状态机不一致：\n  - "
            + "\n  - ".join(errors)
            + "\n请在 engine.py 中加入对应 enum 值，或修正 _STATUS_DEFAULTS。"
        )


# 模块导入时立即校验，让任何不一致在启动阶段就 hard-fail
_validate_status_engine_state_mapping()


# ---------------------------------------------------------------------------
# 运行时种子 / 升级
# ---------------------------------------------------------------------------
async def _ensure_default_statuses(session):
    """Seed default statuses if table is empty; repair missing defaults for existing records."""
    count_result = await session.execute(
        select(func.count()).select_from(FlowStatus)
    )
    if (count_result.scalar() or 0) == 0:
        for idx, s in enumerate(_STATUS_DEFAULTS):
            status = FlowStatus(
                name=s["name"],
                icon=s["icon"],
                icon_color=s["icon_color"],
                command=s.get("command", ""),
                work_item_types_json=json.dumps(s["work_item_types"], ensure_ascii=False),
                sort_order=idx,
            )
            session.add(status)
        await session.flush()
        return

    result = await session.execute(select(FlowStatus))
    statuses = result.scalars().all()
    existing_by_name = {status.name: status for status in statuses}

    design_status = existing_by_name.get("设计中")
    design_done_status = existing_by_name.get("设计完成")
    if not design_done_status:
        insert_order = (
            (design_status.sort_order or 0) + 1
            if design_status
            else next(
                (idx for idx, item in enumerate(_STATUS_DEFAULTS) if item["name"] == "设计完成"),
                len(statuses),
            )
        )
        for status in statuses:
            if (status.sort_order or 0) >= insert_order:
                status.sort_order = (status.sort_order or 0) + 1

        default_status = _STATUS_DEFAULTS_BY_NAME["设计完成"]
        design_done_status = FlowStatus(
            name=default_status["name"],
            icon=default_status["icon"],
            icon_color=default_status["icon_color"],
            command=default_status["command"],
            work_item_types_json=json.dumps(default_status["work_item_types"], ensure_ascii=False),
            sort_order=insert_order,
        )
        session.add(design_done_status)
        statuses.append(design_done_status)
        existing_by_name["设计完成"] = design_done_status

    if design_status and design_done_status and (design_done_status.sort_order or 0) <= (design_status.sort_order or 0):
        old_order = design_done_status.sort_order or 0
        target_order = (design_status.sort_order or 0) + 1
        for status in statuses:
            if status is design_done_status:
                continue
            current_order = status.sort_order or 0
            if old_order < target_order and old_order < current_order <= target_order:
                status.sort_order = current_order - 1
            elif target_order <= current_order < old_order:
                status.sort_order = current_order + 1
        design_done_status.sort_order = target_order

    # Insert "待开发" after "设计完成" if missing (split out from "开发中")
    pending_dev_status = existing_by_name.get("待开发")
    if not pending_dev_status:
        anchor = design_done_status or design_status
        insert_order = (
            (anchor.sort_order or 0) + 1
            if anchor
            else next(
                (idx for idx, item in enumerate(_STATUS_DEFAULTS) if item["name"] == "待开发"),
                len(statuses),
            )
        )
        for status in statuses:
            if (status.sort_order or 0) >= insert_order:
                status.sort_order = (status.sort_order or 0) + 1

        default_status = _STATUS_DEFAULTS_BY_NAME["待开发"]
        pending_dev_status = FlowStatus(
            name=default_status["name"],
            icon=default_status["icon"],
            icon_color=default_status["icon_color"],
            command=default_status["command"],
            work_item_types_json=json.dumps(default_status["work_item_types"], ensure_ascii=False),
            sort_order=insert_order,
        )
        session.add(pending_dev_status)
        statuses.append(pending_dev_status)
        existing_by_name["待开发"] = pending_dev_status

    if design_done_status and pending_dev_status and (pending_dev_status.sort_order or 0) <= (design_done_status.sort_order or 0):
        old_order = pending_dev_status.sort_order or 0
        target_order = (design_done_status.sort_order or 0) + 1
        for status in statuses:
            if status is pending_dev_status:
                continue
            current_order = status.sort_order or 0
            if old_order < target_order and old_order < current_order <= target_order:
                status.sort_order = current_order - 1
            elif target_order <= current_order < old_order:
                status.sort_order = current_order + 1
        pending_dev_status.sort_order = target_order

    # 仅修补 command 为空（早期种子可能漏 command）和「设计完成/待开发」的展示元数据缺失，
    # 不再做历史 command 值的运行时纠正（F.2 已下线 _STATUS_LEGACY_COMMANDS）。
    for status in statuses:
        expected = _STATUS_COMMAND_MAP.get(status.name, "")
        default_meta = _STATUS_DEFAULTS_BY_NAME.get(status.name)

        if status.command == "" and expected:
            status.command = expected

        if status.name in {"设计完成", "待开发"} and default_meta:
            if not status.icon:
                status.icon = default_meta["icon"]
            if not status.icon_color:
                status.icon_color = default_meta["icon_color"]
            if not _parse_json_list(status.work_item_types_json):
                status.work_item_types_json = json.dumps(default_meta["work_item_types"], ensure_ascii=False)
