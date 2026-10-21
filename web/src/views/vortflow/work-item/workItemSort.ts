/** 工作项日期排序的纯函数，供列表数据源和回归测试共用。 */
export type WorkItemSortDirection = "ascend" | "descend";

function parseDateValue(value: unknown): number | null {
    if (value instanceof Date) {
        const timestamp = value.getTime();
        return Number.isFinite(timestamp) ? timestamp : null;
    }
    const text = String(value ?? "").trim();
    if (!text) return null;
    const timestamp = Date.parse(text);
    return Number.isFinite(timestamp) ? timestamp : null;
}

/** 按原始 ISO 时间排序；任一行缺少原始值时沿用原展示值比较。 */
export function compareWorkItemDate<T extends object>(
    a: T,
    b: T,
    rawField: string,
    displayField: string,
    direction: WorkItemSortDirection,
): number {
    const dir = direction === "ascend" ? 1 : -1;
    const rowA = a as Record<string, unknown>;
    const rowB = b as Record<string, unknown>;
    const va = parseDateValue(rowA[rawField]);
    const vb = parseDateValue(rowB[rawField]);

    if (va === null || vb === null) {
        // 兼容没有原始字段的本地行，保持原有排序语义。
        const displayA = String(rowA[displayField] ?? "");
        const displayB = String(rowB[displayField] ?? "");
        if (displayA < displayB) return -1 * dir;
        if (displayA > displayB) return 1 * dir;
        return 0;
    }
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
}
