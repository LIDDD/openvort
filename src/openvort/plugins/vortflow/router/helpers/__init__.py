"""VortFlow router 共享辅助包。

阶段 E（2026-05-06）拆分：原 1306 行的 ``helpers.py`` 按职责拆为本目录下的多个模块，
通过本 ``__init__`` re-export 维持原 import 路径不变（``from .helpers import xxx``）。

子模块职责：

- ``parsers``           : 时间字符串 / JSON 列表 / 附件 JSON 解析
- ``priority_scoring``  : 优先级 score (0-100) ↔ 等级 (1-4) 双向映射
- ``serializers``       : ORM 模型 → 前端响应 dict（项目/需求/任务/缺陷/迭代/版本/视图/标签/状态/测试模块/测试用例/测试计划）
- ``relations``         : 工作项列表附加迭代/版本/活动度信息
- ``events``            : ``_log_event`` 审计事件写入
- ``state_change``      : ``_apply_state_change`` 统一状态变更副作用
- ``tree_validation``   : story/task 父子层级与 task story 解析校验
- ``sort_helpers``      : ``_apply_sort`` 通用排序
- ``member_helpers``    : ``_resolve_member_name`` 成员显示名解析
- ``tag_helpers``       : 标签使用统计、改名/删除替换、自动同步
- ``status_seed``       : ``_STATUS_DEFAULTS`` 状态种子 + ``_ensure_default_statuses``
                          含阶段 F.1 加入的 engine state 一致性校验
- ``test_helpers``      : 测试模块树查询 + 测试用例与工作项关联解析
- ``progress_calc``     : 父需求/父任务的进度自动汇总
"""

from .events import _log_event
from .member_helpers import _resolve_member_name
from .parsers import _parse_attachments, _parse_dt, _parse_json_list, resolve_project_ids
from .priority_scoring import (
    PRIORITY_SCORE_DEFAULTS,
    estimate_hours_to_priority_score_default,
    normalize_priority_score,
    priority_level_to_default_score,
    priority_score_range_for_level,
    score_to_priority_level,
    severity_to_priority_score,
)
from .progress_calc import (
    _attach_story_progress,
    _attach_task_progress,
    _calc_story_progress,
    _calc_task_progress,
)
from .relations import (
    _attach_activity_info,
    _attach_bug_links,
    _attach_project_names,
    _attach_story_links,
    _attach_story_links_basic,
    _attach_task_links,
)
from .serializers import (
    _LINK_TYPE_DICT,
    _LINK_TYPE_MODEL,
    _bug_dict,
    _iteration_dict,
    _project_dict,
    _status_dict,
    _story_dict,
    _tag_dict,
    _task_dict,
    _test_case_dict,
    _test_module_dict,
    _test_plan_dict,
    _version_dict,
    _view_dict,
)
from .sort_helpers import _apply_sort
from .state_change import _apply_state_change, _build_state_change_config
from .status_seed import (
    _STATUS_COMMAND_MAP,
    _STATUS_DEFAULTS,
    _STATUS_DEFAULTS_BY_NAME,
    _ensure_default_statuses,
)
from .tag_helpers import (
    _collect_used_tag_names,
    _count_tag_usage,
    _replace_tag_in_items,
    _sync_missing_tags,
)
from .test_helpers import (
    _build_module_path,
    _get_descendant_module_ids,
    _resolve_linked_entity,
)
from .tree_validation import (
    _collect_story_descendant_ids,
    _resolve_task_story_and_parent,
    _validate_story_parent,
)


__all__ = [
    # parsers
    "_parse_dt",
    "_parse_json_list",
    "_parse_attachments",
    "resolve_project_ids",
    # priority scoring
    "PRIORITY_SCORE_DEFAULTS",
    "priority_level_to_default_score",
    "score_to_priority_level",
    "priority_score_range_for_level",
    "normalize_priority_score",
    "severity_to_priority_score",
    "estimate_hours_to_priority_score_default",
    # serializers
    "_project_dict",
    "_story_dict",
    "_task_dict",
    "_bug_dict",
    "_iteration_dict",
    "_version_dict",
    "_view_dict",
    "_tag_dict",
    "_status_dict",
    "_test_module_dict",
    "_test_case_dict",
    "_test_plan_dict",
    "_LINK_TYPE_MODEL",
    "_LINK_TYPE_DICT",
    # relations
    "_attach_story_links",
    "_attach_task_links",
    "_attach_bug_links",
    "_attach_story_links_basic",
    "_attach_activity_info",
    "_attach_project_names",
    # events
    "_log_event",
    # state change
    "_build_state_change_config",
    "_apply_state_change",
    # tree validation
    "_validate_story_parent",
    "_collect_story_descendant_ids",
    "_resolve_task_story_and_parent",
    # sort
    "_apply_sort",
    # member
    "_resolve_member_name",
    # tags
    "_count_tag_usage",
    "_replace_tag_in_items",
    "_collect_used_tag_names",
    "_sync_missing_tags",
    # status seed
    "_STATUS_DEFAULTS",
    "_STATUS_DEFAULTS_BY_NAME",
    "_STATUS_COMMAND_MAP",
    "_ensure_default_statuses",
    # test helpers
    "_get_descendant_module_ids",
    "_build_module_path",
    "_resolve_linked_entity",
    # progress calc
    "_calc_task_progress",
    "_calc_story_progress",
    "_attach_story_progress",
    "_attach_task_progress",
]
