"""Skill 管理路由（管理员：内置 + 公共）"""

import io
import json as _json
import os
import re
import shutil
import tempfile
import uuid
import zipfile

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select

from openvort.db.models import MemberSkill, PostSkill, Skill
from openvort.skill.directories import SkillDirectoryManager
from openvort.skill.loader import _parse_skill_file
from openvort.web.deps import get_db_session_factory, get_skill_loader

router = APIRouter()


def _parse_tags(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        return _json.loads(raw)
    except Exception:
        return []


class CreateSkillRequest(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    skill_type: str = "workflow"
    tags: list[str] = []


class UpdateSkillRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    skill_type: str | None = None
    tags: list[str] | None = None


@router.get("/tags")
async def list_tags():
    """列出所有已使用的标签"""
    factory = get_db_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(Skill.tags).where(Skill.scope.in_(["builtin", "public", "marketplace"]))
        )
        rows = result.scalars().all()

    tag_set: set[str] = set()
    for raw in rows:
        for tag in _parse_tags(raw):
            if tag:
                tag_set.add(tag)

    return {"tags": sorted(tag_set)}


@router.get("/directories")
async def list_skill_directories():
    """列出所有 Skill 扫描目录"""
    directories = SkillDirectoryManager.get_all_directories()
    return {"directories": directories}


@router.post("/upload")
async def upload_skill(file: UploadFile):
    """上传 .skill 包（zip 格式），解压到用户目录并立即同步入库，无需重启"""
    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="文件不是有效的 zip/.skill 包")

    user_dir = SkillDirectoryManager.get_directory("user")
    if not user_dir or not user_dir.path:
        raise HTTPException(status_code=500, detail="用户 skill 目录不可用")

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        tmp_path = Path(tmp).resolve()

        # [fix] Zip Slip: 解压前校验每个成员路径不逃出 tmp 目录，并拒绝绝对路径和软链
        for info in zf.infolist():
            member = info.filename
            if member.startswith("/") or ".." in member.split("/"):
                raise HTTPException(status_code=400, detail=f"zip 包含非法路径: {member}")
            # 拒绝 Unix 符号链接（external_attr 高 16 位为 Unix 权限，0xA000 = symlink）
            if (info.external_attr >> 16) & 0xF000 == 0xA000:
                raise HTTPException(status_code=400, detail=f"zip 包含符号链接: {member}")
            resolved = (tmp_path / member).resolve()
            if not str(resolved).startswith(str(tmp_path) + os.sep) and resolved != tmp_path:
                raise HTTPException(status_code=400, detail=f"zip 包含路径穿越: {member}")
        zf.extractall(tmp_path)

        # 递归找 SKILL.md
        skill_md = next(tmp_path.rglob("SKILL.md"), None)
        if skill_md is None:
            raise HTTPException(status_code=400, detail="zip 包中未找到 SKILL.md")

        parsed = _parse_skill_file(skill_md)
        if not parsed or not parsed.get("name"):
            raise HTTPException(status_code=400, detail="SKILL.md 解析失败或缺少 name 字段")

        skill_name = parsed["name"]

        # [fix] 路径穿越：skill name 只允许安全字符，并二次验证目标路径在 user dir 内
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", skill_name):
            raise HTTPException(status_code=400, detail=f"skill name 含非法字符: {skill_name!r}")
        target_dir = (user_dir.path / skill_name).resolve()
        user_dir_resolved = user_dir.path.resolve()
        if not str(target_dir).startswith(str(user_dir_resolved) + os.sep):
            raise HTTPException(status_code=400, detail="skill name 导致路径越界")

        # SKILL.md 的父目录就是要复制的 skill 根目录
        skill_root = skill_md.parent
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(skill_root, target_dir)

    # 立即同步入库，无需重启
    loader = get_skill_loader()
    await loader._sync_user_to_db()

    factory = get_db_session_factory()
    async with factory() as db:
        result = await db.execute(select(Skill).where(Skill.name == skill_name, Skill.scope == "personal"))
        row = result.scalar_one_or_none()

    return {
        "success": True,
        "name": skill_name,
        "description": parsed.get("description", ""),
        "id": row.id if row else None,
    }


@router.get("")
async def list_skills(skill_type: str = "", tag: str = ""):
    """列出所有 Skill（builtin + public），可按 tag 筛选"""
    factory = get_db_session_factory()
    async with factory() as db:
        stmt = select(Skill).where(Skill.scope.in_(["builtin", "public", "marketplace"]))
        if skill_type:
            stmt = stmt.where(Skill.skill_type == skill_type)
        stmt = stmt.order_by(Skill.sort_order, Skill.name)
        result = await db.execute(stmt)
        rows = result.scalars().all()

    items = []
    for s in rows:
        tags = _parse_tags(s.tags)
        if tag and tag not in tags:
            continue
        items.append({
            "id": s.id, "name": s.name, "description": s.description,
            "scope": s.scope, "skill_type": s.skill_type, "tags": tags,
            "enabled": s.enabled,
        })

    return {"skills": items}


@router.get("/{skill_id}")
async def get_skill(skill_id: str):
    """获取 Skill 详情（含完整 markdown 内容）"""
    factory = get_db_session_factory()
    async with factory() as db:
        row = await db.get(Skill, skill_id)
    if not row:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {
        "id": row.id, "name": row.name, "description": row.description,
        "content": row.content, "scope": row.scope, "skill_type": row.skill_type,
        "tags": _parse_tags(row.tags), "enabled": row.enabled,
    }


@router.post("")
async def create_skill(req: CreateSkillRequest):
    """创建公共 Skill"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="名称不能为空")

    factory = get_db_session_factory()
    async with factory() as db:
        existing = await db.execute(
            select(Skill).where(Skill.name == req.name, Skill.scope.in_(["builtin", "public"]))
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Skill '{req.name}' 已存在")

        skill = Skill(
            id=uuid.uuid4().hex,
            name=req.name,
            description=req.description,
            content=req.content,
            scope="public",
            skill_type=req.skill_type,
            tags=_json.dumps(req.tags, ensure_ascii=False) if req.tags else "",
        )
        db.add(skill)
        await db.commit()

    return {"success": True, "id": skill.id}


@router.put("/{skill_id}")
async def update_skill(skill_id: str, req: UpdateSkillRequest):
    """更新 Skill 内容（仅公共 Skill 可编辑）"""
    factory = get_db_session_factory()
    async with factory() as db:
        row = await db.get(Skill, skill_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        if row.scope == "builtin":
            raise HTTPException(status_code=403, detail="内置 Skill 不可编辑")
        if row.scope == "personal":
            raise HTTPException(status_code=403, detail="请通过成员技能接口编辑")

        if req.name is not None:
            row.name = req.name
        if req.description is not None:
            row.description = req.description
        if req.content is not None:
            row.content = req.content
        if req.skill_type is not None:
            row.skill_type = req.skill_type
        if req.tags is not None:
            row.tags = _json.dumps(req.tags, ensure_ascii=False)
        await db.commit()

    return {"success": True}


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str):
    """删除 Skill（仅公共 Skill 可删除）"""
    factory = get_db_session_factory()
    async with factory() as db:
        row = await db.get(Skill, skill_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        if row.scope == "builtin":
            raise HTTPException(status_code=403, detail="内置 Skill 不可删除")
        if row.scope == "personal":
            raise HTTPException(status_code=403, detail="请通过成员技能接口删除")

        await db.execute(delete(MemberSkill).where(MemberSkill.skill_id == skill_id))
        await db.execute(delete(PostSkill).where(PostSkill.skill_id == skill_id))
        await db.delete(row)
        await db.commit()

    return {"success": True}


@router.post("/{skill_id}/toggle")
async def toggle_skill(skill_id: str):
    """启用/禁用 Skill"""
    factory = get_db_session_factory()
    async with factory() as db:
        row = await db.get(Skill, skill_id)
        if not row:
            raise HTTPException(status_code=404, detail="Skill 不存在")

        row.enabled = not row.enabled
        await db.commit()
        new_state = row.enabled

    return {"success": True, "enabled": new_state}


@router.get("/{skill_id}/generate-content-prompt")
async def generate_skill_content_prompt(skill_id: str):
    """生成 AI 创建/优化 Skill 内容的 prompt，前端跳转 chat 页使用"""
    factory = get_db_session_factory()
    async with factory() as db:
        skill = await db.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill 不存在")

    prompt = (
        f"请为 Skill「{skill.name}」生成专业、详细的技能描述内容。\n\n"
        f"现有信息：\n"
        f"- 名称：{skill.name}\n"
        f"- 描述：{skill.description or '暂无'}\n\n"
        f"请生成一份完整的 Skill 内容（Markdown 格式），包括：\n"
        f"1. 技能概述\n"
        f"2. 适用场景\n"
        f"3. 使用方法/最佳实践\n"
        f"4. 注意事项\n\n"
        f"要求：内容要专业、实用，能帮助 AI 员工更好地执行相关任务。"
    )
    return {"prompt": prompt}
