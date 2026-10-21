"""通用排序助手——把 sort_by/sort_order 字符串映射到 ORM 列。"""


def _apply_sort(stmt, model, sort_by: str, sort_order: str, default_col=None):
    """Apply dynamic sorting to a SQLAlchemy select statement."""
    col = getattr(model, sort_by, None) if sort_by else None
    if col is not None:
        order_fn = col.asc() if sort_order == "asc" else col.desc()
        return stmt.order_by(order_fn, model.id.desc())
    if default_col is not None:
        return stmt.order_by(default_col.desc(), model.id.desc())
    return stmt.order_by(model.created_at.desc(), model.id.desc())
