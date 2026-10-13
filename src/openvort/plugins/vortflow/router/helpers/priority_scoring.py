"""优先级 score (0-100) 与等级 (1-4) 的双向换算。

映射规则：
- 等级 1 (紧急) → score 80-100，默认 80
- 等级 2 (高)   → score 60-79，默认 60
- 等级 3 (中)   → score 40-59，默认 40
- 等级 4 (低)   → score 20-39，默认 20
- 等级 0 (无)   → score 0-19，默认 0

同等级内 score 越大越优先；等于段起始值时前端不显示具体分数。
"""

PRIORITY_SCORE_DEFAULTS: dict[int, int] = {1: 80, 2: 60, 3: 40, 4: 20, 0: 0}


def priority_level_to_default_score(level: int | None) -> int:
    """将等级 (1=紧急 / 2=高 / 3=中 / 4=低 / 0=无) 转为段起始 score。"""
    if level is None:
        return 0
    return PRIORITY_SCORE_DEFAULTS.get(int(level), 0)


def score_to_priority_level(score: int | None) -> int:
    """将 0-100 score 派生为等级 (1=紧急/2=高/3=中/4=低/0=无)。"""
    if score is None:
        return 0
    s = int(score)
    if s >= 80:
        return 1
    if s >= 60:
        return 2
    if s >= 40:
        return 3
    if s >= 20:
        return 4
    return 0


def priority_score_range_for_level(level: int) -> tuple[int, int]:
    """获取等级对应的 score 区间 [min, max]。"""
    if level == 1:
        return (80, 100)
    if level == 2:
        return (60, 79)
    if level == 3:
        return (40, 59)
    if level == 4:
        return (20, 39)
    return (0, 19)


def normalize_priority_score(score: int | None) -> int:
    """将 score 钳制到 0-100 范围内。"""
    if score is None:
        return 0
    return max(0, min(100, int(score)))


def severity_to_priority_score(severity: int | None) -> int:
    """缺陷 severity (1=致命 2=严重 3=一般 4=轻微) 转 score 默认值。

    复用 priority 等级的映射，便于工作墙混排时按 score 统一排序。
    """
    if severity is None:
        return 0
    return PRIORITY_SCORE_DEFAULTS.get(int(severity), 0)


def estimate_hours_to_priority_score_default(estimate_hours: float | None) -> int:
    """任务无等级列时，用估时映射到段起始 score（与历史前端规则一致）。"""
    if estimate_hours is None:
        return 40
    try:
        h = float(estimate_hours)
    except (TypeError, ValueError):
        return 40
    if h >= 16:
        return 80
    if h >= 8:
        return 60
    if h >= 4:
        return 40
    return 20
