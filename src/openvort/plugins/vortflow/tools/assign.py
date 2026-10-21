"""
角色分配工具 — vortflow_assign

分配产品经理、设计师、开发人员、测试人员等角色到需求或任务。
"""

import json

from sqlalchemy import select

from openvort.plugin.base import BaseTool
from openvort.utils.logging import get_logger

log = get_logger("plugins.vortflow.tools.assign")


class AssignTool(BaseTool):
    name = "vortflow_assign"
    description = (
        "为 VortFlow 中的需求/任务/缺陷分配负责人或报告人。"
        "可分配的角色：负责人(assignee)、产品经理(pm，等价于 assignee)、"
        "开发(developer，等价于 assignee)、报告人(reporter，仅缺陷)。"
        "分配后会通知被分配人。"
    )
    required_permission = "vortflow.assign"

    def __init__(self, get_session_factory, notifier):
        self._get_sf = get_session_factory
        self._notifier = notifier

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "实体类型",
                    "enum": ["story", "task", "bug"],
                },
                "entity_id": {"type": "string", "description": "需求/任务/缺陷 ID"},
                "role": {
                    "type": "string",
                    "description": "分配的角色: pm(产品经理)/assignee(负责人) 等价；bug 的 developer 与 assignee 等价；reporter 仅缺陷。",
                    "enum": ["pm", "assignee", "developer", "reporter"],
                },
                "member_id": {"type": "string", "description": "被分配成员的 ID"},
            },
            "required": ["entity_type", "entity_id", "role", "member_id"],
        }

    async def execute(self, params: dict) -> str:
        from openvort.plugins.vortflow.models import FlowBug, FlowEvent, FlowStory, FlowTask

        entity_type = params["entity_type"]
        entity_id = params["entity_id"]
        role = params["role"]
        member_id = params["member_id"]

        # 「负责人」相关角色统一以 assignee_id 为权威字段，并同步覆盖兼容字段，
        # 避免历史「pm 是 X 但已指派给 Y」「assignee 是 X 但 developer 是 Y」的双轨脏数据。
        # 仅 reporter（缺陷报告人）是真正不同语义的独立角色。
        role_field_map = {
            "story": {
                "pm": ["pm_id", "assignee_id"],
                "assignee": ["assignee_id", "pm_id"],
            },
            "task": {
                "assignee": ["assignee_id"],
            },
            "bug": {
                "assignee": ["assignee_id", "developer_id"],
                "developer": ["developer_id", "assignee_id"],
                "reporter": ["reporter_id"],
            },
        }

        model_map = {"story": FlowStory, "task": FlowTask, "bug": FlowBug}

        if entity_type not in model_map:
            return json.dumps({"ok": False, "message": f"不支持的实体类型: {entity_type}"})

        fields = role_field_map.get(entity_type, {})
        field_names = fields.get(role)
        if not field_names:
            return json.dumps({"ok": False, "message": f"{entity_type} 不支持分配角色: {role}"})

        model = model_map[entity_type]
        sf = self._get_sf()

        async with sf() as session:
            result = await session.execute(select(model).where(model.id == entity_id))
            entity = result.scalar_one_or_none()
            if not entity:
                return json.dumps({"ok": False, "message": f"{entity_type} 不存在: {entity_id}"})

            for field_name in field_names:
                setattr(entity, field_name, member_id)
            field_name = field_names[0]

            # Extract caller identity injected by AgentRuntime
            actor_id = params.get("_member_id", "")

            # 记录事件（含操作人）
            event = FlowEvent(
                entity_type=entity_type,
                entity_id=entity_id,
                action="assigned",
                actor_id=actor_id or None,
                detail=json.dumps({"role": role, "member_id": member_id}, ensure_ascii=False),
            )
            session.add(event)
            await session.commit()

            title = entity.title
            project_id = getattr(entity, "project_id", "") or ""

        # 发送通知
        role_names = {
            "pm": "产品经理",
            "assignee": "负责人",
            "developer": "开发人员",
            "reporter": "报告人",
        }
        if self._notifier:
            # role=reporter 不是工作项负责人语义，跳过任务分配通知（避免给报告人发 “你被分配为负责人” 这种误导消息）。
            if role != "reporter":
                await self._notifier.notify_assignment(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    title=title,
                    actor_id=actor_id,
                    new_assignee_id=member_id,
                    project_id=project_id,
                )

        return json.dumps({
            "ok": True,
            "message": f"已将 {entity_type} 「{title}」的{role_names.get(role, role)}分配给 {member_id}",
        }, ensure_ascii=False)
