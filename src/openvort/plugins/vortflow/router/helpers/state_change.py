"""统一应用工作项状态变更的副作用。

历史背景：状态变更涉及多处副作用：transition 校验 / start_at / end_at 自动维护 /
写 state_changed 事件 / 触发通知。早期 transition endpoint 走完整流程，但
update endpoint 在 body.state 字段直接落库时绕过了所有副作用，导致流转天数无法
统计、状态历史断层、通知不发。本模块把"应用一次状态变更"的核心副作用集中到一处，
由 transition / update 两条入口共享。

- ``strict=True``  : 严格按 ``*_TRANSITIONS`` 表校验非法跳转 → 用于 ``/transition`` 接口
- ``strict=False`` : 不做 transition 表校验（前端目前直接通过 update 改 state，
                     跨段切换是常态），但仍维护时间字段与事件记录 → 用于 ``/update`` 接口

注意：本模块不发通知，调用方在 commit 后自行 ``schedule_notification``，
避免引入 notifier 依赖造成循环 import。
"""

from datetime import datetime

from .events import _log_event


_STATE_CHANGE_CONFIG: dict[str, dict] = {}


def _build_state_change_config() -> dict[str, dict]:
    """惰性构建配置（避免顶层 import 时引入循环依赖）。"""
    if _STATE_CHANGE_CONFIG:
        return _STATE_CHANGE_CONFIG
    from openvort.plugins.vortflow.engine import (
        BUG_CLOSED_STATES,
        BUG_TRANSITIONS,
        BugState,
        STORY_DONE_STATES,
        STORY_TRANSITIONS,
        StoryState,
        TASK_DONE_STATES,
        TASK_TRANSITIONS,
        TaskState,
    )
    _STATE_CHANGE_CONFIG.update({
        "story": {
            "enum": StoryState,
            "transitions": STORY_TRANSITIONS,
            "done_states": STORY_DONE_STATES,
            "working_state": StoryState.IN_PROGRESS.value,
        },
        "task": {
            "enum": TaskState,
            "transitions": TASK_TRANSITIONS,
            "done_states": TASK_DONE_STATES,
            "working_state": TaskState.IN_PROGRESS.value,
        },
        "bug": {
            "enum": BugState,
            "transitions": BUG_TRANSITIONS,
            "done_states": BUG_CLOSED_STATES,
            "working_state": BugState.FIXING.value,
        },
    })
    return _STATE_CHANGE_CONFIG


async def _apply_state_change(
    session,
    *,
    kind: str,
    obj,
    new_state: str,
    actor_id: str = "",
    strict: bool = True,
) -> tuple[bool, str | None, dict, str]:
    """统一应用工作项状态变更的副作用。

    返回 ``(ok, error_message, auto_fields, old_state)``：

    - ``new_state == 当前 state``：直接返回 ``(True, None, {}, old_state)``，不修改 obj
    - ``new_state`` 不在枚举里：返回 ``(False, "...", {}, old_state)``
    - 当前 state 不在枚举里：strict 模式下返回 ``(False, ...)``；lenient 模式下视为
      "未知历史状态"，允许直接迁移到合法目标（修复脏数据通道）
    - strict 模式下转换不在 ``*_TRANSITIONS`` 表中：返回 ``(False, "...", {}, old_state)``
    - 否则修改 ``obj.state`` 并按需自动维护 ``obj.start_at`` / ``obj.end_at``，
      最后写一条 ``state_changed`` 事件；调用方负责 ``schedule_notification`` 与 commit。
    """
    config = _build_state_change_config().get(kind)
    if config is None:
        return False, f"未知的工作项类型: {kind}", {}, getattr(obj, "state", "")

    old_state = obj.state
    if new_state == old_state:
        return True, None, {}, old_state

    state_enum = config["enum"]
    try:
        target = state_enum(new_state)
    except ValueError:
        valid_values = [s.value for s in state_enum]
        return False, (
            f"目标状态非法: {new_state}，可选: {valid_values}"
        ), {}, old_state

    # 历史脏数据中可能存在非枚举值的 old_state（例如中文 "测试中"）。strict 模式
    # 仍然要拒绝这种数据，避免误操作；lenient 模式（前端 update 接口）允许把
    # 这种"未知历史状态"直接修复为合法的目标状态，跳过 transition 表校验。
    current = None
    try:
        current = state_enum(old_state)
    except ValueError:
        if strict:
            return False, (
                f"当前状态 {old_state!r} 已损坏，无法走严格状态机推进，"
                f"请通过编辑接口直接覆盖为合法状态"
            ), {}, old_state

    if strict and current is not None:
        allowed = config["transitions"].get(current, [])
        if target not in allowed:
            allowed_names = [t.value for t in allowed]
            return False, (
                f"不允许从 {current.value} 转换到 {target.value}，可选: {allowed_names}"
            ), {}, old_state

    obj.state = target.value

    now = datetime.now()
    auto_fields: dict = {}
    done_states: set[str] = config["done_states"]
    working_state: str = config["working_state"]

    if target.value == working_state and obj.start_at is None:
        obj.start_at = now
        auto_fields["start_at"] = now.isoformat()
    if target.value in done_states and obj.end_at is None:
        obj.end_at = now
        auto_fields["end_at"] = now.isoformat()
        # 跳过工作中态直接完成时同步补 start_at，使 cycle time 可统计
        if obj.start_at is None:
            obj.start_at = now
            auto_fields["start_at"] = now.isoformat()
    elif (
        old_state in done_states
        and target.value not in done_states
        and obj.end_at is not None
    ):
        auto_fields["end_at_cleared_from"] = obj.end_at.isoformat()
        obj.end_at = None

    event_detail: dict = {"from": old_state, "to": target.value}
    if auto_fields:
        event_detail["auto_fields"] = auto_fields
    if not strict:
        event_detail["lenient"] = True
    await _log_event(
        session, kind, obj.id, "state_changed", event_detail, actor_id=actor_id,
    )

    return True, None, auto_fields, old_state
