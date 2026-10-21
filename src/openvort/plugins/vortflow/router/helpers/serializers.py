"""ORM 模型 → 前端响应 dict 的序列化器。"""

import json

from openvort.plugins.vortflow.models import (
    FlowBug,
    FlowIteration,
    FlowProject,
    FlowStatus,
    FlowStory,
    FlowTag,
    FlowTask,
    FlowTestCase,
    FlowTestModule,
    FlowTestPlan,
    FlowVersion,
    FlowView,
)

from .parsers import _parse_attachments, _parse_json_list
from .priority_scoring import (
    estimate_hours_to_priority_score_default,
    priority_level_to_default_score,
    severity_to_priority_score,
)


def _project_dict(r: FlowProject) -> dict:
    return {
        "id": r.id, "name": r.name, "code": r.code, "color": r.color,
        "description": r.description,
        "owner_id": r.owner_id,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _story_dict(r: FlowStory) -> dict:
    score = getattr(r, "priority_score", None)
    if score is None:
        score = priority_level_to_default_score(r.priority)
    return {
        "id": r.id, "title": r.title, "description": r.description,
        "state": r.state, "priority": r.priority,
        "priority_score": score,
        "parent_id": r.parent_id,
        "sort_order": getattr(r, "sort_order", None),
        "project_id": r.project_id, "submitter_id": r.submitter_id,
        "assignee_id": getattr(r, "assignee_id", None),
        "pm_id": r.pm_id,
        "tags": _parse_json_list(r.tags_json),
        "collaborators": _parse_json_list(r.collaborators_json),
        "attachments": _parse_attachments(getattr(r, "attachments_json", "[]")),
        "progress": getattr(r, "progress", None) or 0,
        "plan_start": r.plan_start.isoformat() if getattr(r, "plan_start", None) else None,
        "deadline": r.deadline.isoformat() if r.deadline else None,
        "start_at": r.start_at.isoformat() if getattr(r, "start_at", None) else None,
        "end_at": r.end_at.isoformat() if getattr(r, "end_at", None) else None,
        "test_time": r.test_time.isoformat() if getattr(r, "test_time", None) else None,
        "draft_time": r.draft_time.isoformat() if getattr(r, "draft_time", None) else None,
        "release_time": r.release_time.isoformat() if getattr(r, "release_time", None) else None,
        "repo_id": getattr(r, "repo_id", None) or "",
        "branch": getattr(r, "branch", None) or "",
        "is_archived": getattr(r, "is_archived", False) or False,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _task_dict(r: FlowTask) -> dict:
    score = getattr(r, "priority_score", None)
    if score is None:
        score = estimate_hours_to_priority_score_default(r.estimate_hours)
    return {
        "id": r.id, "title": r.title, "description": r.description,
        "state": r.state, "task_type": r.task_type,
        "priority_score": score,
        "project_id": r.project_id,
        "story_id": r.story_id, "parent_id": r.parent_id,
        "sort_order": getattr(r, "sort_order", None),
        "assignee_id": r.assignee_id, "creator_id": r.creator_id,
        "tags": _parse_json_list(r.tags_json),
        "collaborators": _parse_json_list(r.collaborators_json),
        "attachments": _parse_attachments(getattr(r, "attachments_json", "[]")),
        "progress": getattr(r, "progress", None) or 0,
        "estimate_hours": r.estimate_hours, "actual_hours": r.actual_hours,
        "plan_start": r.plan_start.isoformat() if getattr(r, "plan_start", None) else None,
        "deadline": r.deadline.isoformat() if r.deadline else None,
        "start_at": r.start_at.isoformat() if getattr(r, "start_at", None) else None,
        "end_at": r.end_at.isoformat() if getattr(r, "end_at", None) else None,
        "repo_id": getattr(r, "repo_id", None) or "",
        "branch": getattr(r, "branch", None) or "",
        "is_archived": getattr(r, "is_archived", False) or False,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _bug_dict(r: FlowBug) -> dict:
    score = getattr(r, "priority_score", None)
    if score is None:
        score = severity_to_priority_score(r.severity)
    return {
        "id": r.id, "title": r.title, "description": r.description,
        "state": r.state, "severity": r.severity,
        "priority_score": score,
        "project_id": r.project_id,
        "story_id": r.story_id, "task_id": r.task_id,
        "sort_order": getattr(r, "sort_order", None),
        "reporter_id": r.reporter_id, "assignee_id": r.assignee_id,
        "developer_id": r.developer_id,
        "tags": _parse_json_list(r.tags_json),
        "collaborators": _parse_json_list(r.collaborators_json),
        "attachments": _parse_attachments(getattr(r, "attachments_json", "[]")),
        "estimate_hours": getattr(r, "estimate_hours", None),
        "actual_hours": getattr(r, "actual_hours", None),
        "plan_start": r.plan_start.isoformat() if getattr(r, "plan_start", None) else None,
        "deadline": r.deadline.isoformat() if getattr(r, "deadline", None) else None,
        "start_at": r.start_at.isoformat() if getattr(r, "start_at", None) else None,
        "end_at": r.end_at.isoformat() if getattr(r, "end_at", None) else None,
        "repo_id": getattr(r, "repo_id", None) or "",
        "branch": getattr(r, "branch", None) or "",
        "is_archived": getattr(r, "is_archived", False) or False,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _iteration_dict(r: FlowIteration) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "name": r.name, "goal": r.goal,
        "owner_id": r.owner_id,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "status": r.status,
        "estimate_hours": r.estimate_hours,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _version_dict(r: FlowVersion) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "name": r.name,
        "description": r.description,
        "owner_id": r.owner_id,
        "planned_release_at": r.planned_release_at.isoformat() if r.planned_release_at else None,
        "actual_release_at": r.actual_release_at.isoformat() if r.actual_release_at else None,
        "progress": r.progress,
        "release_date": r.release_date.isoformat() if r.release_date else None,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _view_dict(r: FlowView) -> dict:
    return {
        "id": r.id, "name": r.name,
        "work_item_type": r.work_item_type,
        "scope": r.scope, "owner_id": r.owner_id,
        "filters": json.loads(r.filters_json) if r.filters_json else {},
        "columns": json.loads(r.columns_json) if r.columns_json else [],
        "order": r.view_order,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _tag_dict(r: FlowTag) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "color": r.color,
        "sort_order": r.sort_order,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _status_dict(r: FlowStatus) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "icon": r.icon,
        "icon_color": r.icon_color,
        "command": r.command,
        "work_item_types": _parse_json_list(r.work_item_types_json),
        "sort_order": r.sort_order,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _test_module_dict(m: FlowTestModule) -> dict:
    return {
        "id": m.id,
        "project_id": m.project_id,
        "parent_id": m.parent_id,
        "name": m.name,
        "sort_order": m.sort_order,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _test_case_dict(tc: FlowTestCase, *, maintainer_name: str = "", module_name: str = "", module_path: str = "") -> dict:
    return {
        "id": tc.id,
        "project_id": tc.project_id,
        "module_id": tc.module_id,
        "module_name": module_name,
        "module_path": module_path,
        "title": tc.title,
        "precondition": tc.precondition,
        "notes": tc.notes,
        "case_type": tc.case_type,
        "priority": tc.priority,
        "maintainer_id": tc.maintainer_id,
        "maintainer_name": maintainer_name,
        "review_result": tc.review_result,
        "steps": json.loads(tc.steps_json) if tc.steps_json else [],
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
        "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
    }


def _test_plan_dict(
    tp: FlowTestPlan,
    *,
    owner_name: str = "",
    iteration_name: str = "",
    version_name: str = "",
    total_cases: int = 0,
    executed_cases: int = 0,
    passed: int = 0,
    failed: int = 0,
    blocked: int = 0,
    skipped: int = 0,
) -> dict:
    return {
        "id": tp.id,
        "project_id": tp.project_id,
        "title": tp.title,
        "description": tp.description,
        "status": tp.status,
        "owner_id": tp.owner_id,
        "owner_name": owner_name,
        "iteration_id": tp.iteration_id,
        "iteration_name": iteration_name,
        "version_id": tp.version_id,
        "version_name": version_name,
        "start_date": tp.start_date,
        "end_date": tp.end_date,
        "total_cases": total_cases,
        "executed_cases": executed_cases,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "skipped": skipped,
        "created_at": tp.created_at.isoformat() if tp.created_at else None,
        "updated_at": tp.updated_at.isoformat() if tp.updated_at else None,
    }


# ---- Link-type mappings ----
# story/task/bug 三种类型的 ORM 模型与 dict 序列化器映射，供工作项关联场景使用。
_LINK_TYPE_MODEL = {"story": FlowStory, "task": FlowTask, "bug": FlowBug}
_LINK_TYPE_DICT = {"story": _story_dict, "task": _task_dict, "bug": _bug_dict}
