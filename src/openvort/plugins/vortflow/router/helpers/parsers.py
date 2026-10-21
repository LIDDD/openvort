"""通用解析辅助：时间字符串 / JSON 列表 / 附件 JSON。"""

import json
from datetime import datetime


def _parse_dt(s: str | None) -> datetime | None:
    """解析 ISO 格式时间字符串为 naive datetime（与数据库 TIMESTAMP WITHOUT TIME ZONE 列对齐）。

    支持的输入格式：
    - 本地日期：``2026-04-29`` / ``2026-04-29T00:00:00``（前端 dayjs.format 标准输出）
    - UTC ISO：``2026-04-29T00:00:00.000Z``（前端 Date.toISOString 输出，含 +00:00）
    - 本地带偏移：``2026-04-29T00:00:00+08:00``

    含 tzinfo 时统一用系统本地时区折算后剥掉 tzinfo，避免「UTC 当本地」直接比对
    导致的 8 小时偏移（参考 work_items.py 中 completed_after 的同款 bug）。
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def resolve_project_ids(project_id: str = "", project_ids: str = "") -> list[str]:
    """归一化项目过滤参数为项目 id 列表。

    - ``project_ids``（逗号分隔，多选）优先级高于单值 ``project_id``。
    - 两者都为空时返回空列表，表示「全部项目」不过滤。
    - 自动去空白、去重并保持出现顺序。
    """
    raw = project_ids if project_ids else project_id
    if not raw:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for part in raw.split(","):
        pid = part.strip()
        if pid and pid not in seen:
            seen.add(pid)
            result.append(pid)
    return result


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    result: list[str] = []
    for item in data:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _parse_attachments(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
