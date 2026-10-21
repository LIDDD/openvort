"""VortFlow 状态机引擎"""

from enum import Enum
from typing import Any, Callable, Coroutine

from openvort.utils.logging import get_logger

log = get_logger("plugins.vortflow.engine")


# ============ 状态枚举 ============


class StoryState(str, Enum):
    SUBMITTED = "submitted"
    INTAKE = "intake"
    REVIEW = "review"
    REJECTED = "rejected"
    PM_REFINE = "pm_refine"
    DESIGN = "design"
    DESIGN_DONE = "design_done"
    PENDING_DEV = "pending_dev"
    BREAKDOWN = "breakdown"
    DEV_ASSIGN = "dev_assign"
    IN_PROGRESS = "in_progress"
    DEV_DONE = "dev_done"            # 开发完成（等待提测）
    PENDING_TEST = "pending_test"    # 待测试（已提测在排期）
    TESTING = "testing"
    BUGFIX = "bugfix"
    TEST_DONE = "test_done"          # 测试完成（通过测试）
    REGRESSION = "regression"        # 已测完回归中
    PENDING_RELEASE = "pending_release"  # 待发布
    RELEASED = "released"            # 发布完成
    DONE = "done"
    SUSPENDED = "suspended"          # 暂搁置（非终态，可恢复）


class TaskState(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CLOSED = "closed"


class BugState(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    FIXING = "fixing"
    RESOLVED = "resolved"
    VERIFIED = "verified"
    CLOSED = "closed"
    NOT_REPRODUCIBLE = "not_reproducible"
    REOPENED = "reopened"
    BY_DESIGN = "by_design"
    DEFERRED = "deferred"
    SUSPENDED = "suspended"


# ============ 统计用完成态集合 ============

STORY_DONE_STATES: set[str] = {StoryState.DONE.value, StoryState.RELEASED.value}
TASK_DONE_STATES: set[str] = {TaskState.DONE.value, TaskState.CLOSED.value}
BUG_CLOSED_STATES: set[str] = {
    BugState.RESOLVED.value, BugState.VERIFIED.value, BugState.CLOSED.value,
    BugState.NOT_REPRODUCIBLE.value, BugState.BY_DESIGN.value,
}

# 需求的 plan_start / deadline 描述开发排期，而不是测试、发布等完整生命周期。
# 只有仍处于开发完成前的需求才参与 deadline 风险统计；进入待测试或后续状态后退出。
# dev_done 虽然当前团队不使用，但保留为兼容状态，不应被算作开发逾期。
STORY_DEVELOPMENT_PENDING_STATES: set[str] = {
    StoryState.SUBMITTED.value,
    StoryState.INTAKE.value,
    StoryState.REVIEW.value,
    StoryState.PM_REFINE.value,
    StoryState.DESIGN.value,
    StoryState.DESIGN_DONE.value,
    StoryState.PENDING_DEV.value,
    StoryState.BREAKDOWN.value,
    StoryState.DEV_ASSIGN.value,
    StoryState.IN_PROGRESS.value,
}


# ============ 合法转换表 ============

STORY_TRANSITIONS: dict[StoryState, list[StoryState]] = {
    StoryState.SUBMITTED: [StoryState.INTAKE, StoryState.REJECTED],
    StoryState.INTAKE: [StoryState.REVIEW],
    StoryState.REVIEW: [StoryState.PM_REFINE, StoryState.REJECTED],
    StoryState.REJECTED: [StoryState.SUBMITTED],
    StoryState.PM_REFINE: [StoryState.DESIGN],
    StoryState.DESIGN: [StoryState.DESIGN_DONE],
    StoryState.DESIGN_DONE: [StoryState.PENDING_DEV, StoryState.BREAKDOWN],
    StoryState.PENDING_DEV: [StoryState.BREAKDOWN, StoryState.DEV_ASSIGN, StoryState.IN_PROGRESS],
    StoryState.BREAKDOWN: [StoryState.DEV_ASSIGN],
    StoryState.DEV_ASSIGN: [StoryState.IN_PROGRESS],
    StoryState.IN_PROGRESS: [StoryState.DEV_DONE, StoryState.TESTING],
    StoryState.DEV_DONE: [StoryState.PENDING_TEST, StoryState.TESTING],
    StoryState.PENDING_TEST: [StoryState.TESTING],
    StoryState.TESTING: [StoryState.BUGFIX, StoryState.TEST_DONE, StoryState.DONE],
    StoryState.BUGFIX: [StoryState.TESTING],
    StoryState.TEST_DONE: [StoryState.REGRESSION, StoryState.PENDING_RELEASE, StoryState.DONE],
    StoryState.REGRESSION: [StoryState.TESTING, StoryState.PENDING_RELEASE, StoryState.DONE],
    StoryState.PENDING_RELEASE: [StoryState.RELEASED, StoryState.DONE],
    StoryState.RELEASED: [StoryState.DONE],
    StoryState.DONE: [],
    # 暂搁置：从任何非终态状态都可进入；恢复时回到 pending_dev / submitted，或直接关闭/拒绝
    StoryState.SUSPENDED: [
        StoryState.SUBMITTED,
        StoryState.PENDING_DEV,
        StoryState.IN_PROGRESS,
        StoryState.REJECTED,
        StoryState.DONE,
    ],
}

# 允许从这些"活跃"状态进入 SUSPENDED（在转换表里追加，避免上方逐行重复）
for _src in (
    StoryState.SUBMITTED,
    StoryState.INTAKE,
    StoryState.REVIEW,
    StoryState.PM_REFINE,
    StoryState.DESIGN,
    StoryState.DESIGN_DONE,
    StoryState.PENDING_DEV,
    StoryState.BREAKDOWN,
    StoryState.DEV_ASSIGN,
    StoryState.IN_PROGRESS,
    StoryState.DEV_DONE,
    StoryState.PENDING_TEST,
    StoryState.TESTING,
    StoryState.BUGFIX,
    StoryState.TEST_DONE,
    StoryState.REGRESSION,
    StoryState.PENDING_RELEASE,
):
    STORY_TRANSITIONS[_src].append(StoryState.SUSPENDED)
del _src

TASK_TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.TODO: [TaskState.IN_PROGRESS],
    TaskState.IN_PROGRESS: [TaskState.DONE],
    TaskState.DONE: [TaskState.CLOSED, TaskState.IN_PROGRESS],
    TaskState.CLOSED: [],
}

BUG_TRANSITIONS: dict[BugState, list[BugState]] = {
    BugState.OPEN: [BugState.CONFIRMED, BugState.CLOSED, BugState.NOT_REPRODUCIBLE, BugState.BY_DESIGN, BugState.DEFERRED, BugState.SUSPENDED],
    BugState.CONFIRMED: [BugState.FIXING, BugState.NOT_REPRODUCIBLE, BugState.BY_DESIGN, BugState.DEFERRED, BugState.SUSPENDED],
    BugState.FIXING: [BugState.RESOLVED, BugState.DEFERRED],
    BugState.RESOLVED: [BugState.VERIFIED, BugState.FIXING],
    BugState.VERIFIED: [BugState.CLOSED, BugState.REOPENED],
    BugState.CLOSED: [BugState.REOPENED],
    BugState.NOT_REPRODUCIBLE: [BugState.REOPENED, BugState.CLOSED],
    BugState.REOPENED: [BugState.CONFIRMED, BugState.FIXING],
    BugState.BY_DESIGN: [BugState.REOPENED, BugState.CLOSED],
    BugState.DEFERRED: [BugState.FIXING, BugState.REOPENED],
    BugState.SUSPENDED: [BugState.REOPENED, BugState.OPEN],
}


# ============ Transition Hook 类型 ============

TransitionHook = Callable[[str, str, str, dict], Coroutine[Any, Any, None]]
# (entity_type, entity_id, new_state, context) -> None


# ============ FlowEngine ============


class FlowEngine:
    """状态机核心 — 校验转换合法性 + 触发 hooks"""

    def __init__(self):
        self._hooks: list[TransitionHook] = []

    def add_hook(self, hook: TransitionHook) -> None:
        self._hooks.append(hook)

    async def transition_story(self, story_id: str, current: StoryState, target: StoryState, context: dict | None = None) -> bool:
        """推进需求状态"""
        if target not in STORY_TRANSITIONS.get(current, []):
            log.warning(f"Story {story_id}: 非法转换 {current.value} -> {target.value}")
            return False
        await self._fire_hooks("story", story_id, target.value, context or {})
        return True

    async def transition_task(self, task_id: str, current: TaskState, target: TaskState, context: dict | None = None) -> bool:
        """推进任务状态"""
        if target not in TASK_TRANSITIONS.get(current, []):
            log.warning(f"Task {task_id}: 非法转换 {current.value} -> {target.value}")
            return False
        await self._fire_hooks("task", task_id, target.value, context or {})
        return True

    async def transition_bug(self, bug_id: str, current: BugState, target: BugState, context: dict | None = None) -> bool:
        """推进缺陷状态"""
        if target not in BUG_TRANSITIONS.get(current, []):
            log.warning(f"Bug {bug_id}: 非法转换 {current.value} -> {target.value}")
            return False
        await self._fire_hooks("bug", bug_id, target.value, context or {})
        return True

    async def _fire_hooks(self, entity_type: str, entity_id: str, new_state: str, context: dict) -> None:
        for hook in self._hooks:
            try:
                await hook(entity_type, entity_id, new_state, context)
            except Exception as e:
                log.error(f"Transition hook 执行失败: {e}")
