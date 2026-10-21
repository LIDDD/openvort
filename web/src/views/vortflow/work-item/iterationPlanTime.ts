/**
 * 根据迭代日期生成缺陷的计划时间。
 *
 * 计划时间与迭代的自动联动目前只对缺陷开放；需求和任务仍保留用户
 * 手动维护的计划时间，避免改变既有行为。
 */
export type IterationPlanTime = [string, string];

export interface IterationDateOption {
    id?: string | number | null;
    start_date?: unknown;
    end_date?: unknown;
}

const toDateText = (value: unknown): string => {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        const year = value.getFullYear();
        const month = String(value.getMonth() + 1).padStart(2, "0");
        const day = String(value.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }
    const text = String(value ?? "").trim();
    if (!text) return "";
    // 后端返回 ISO 时间；只取日期部分，避免浏览器时区转换导致跨日。
    const match = text.match(/^(\d{4}-\d{2}-\d{2})/);
    return match?.[1] || "";
};

/**
 * 返回应写入缺陷计划时间的日期范围；无法联动时返回 null。
 * 迭代只有一侧日期时，沿用已有创建表单的补齐规则复制到另一侧。
 */
export function resolveBugIterationPlanTime(
    workItemType: string | undefined,
    iterationId: unknown,
    options: readonly IterationDateOption[] = [],
): IterationPlanTime | null {
    if (workItemType !== "缺陷") return null;
    const id = String(iterationId ?? "").trim();
    if (!id || id === "__unplanned__") return null;

    const matching = options.filter((item) => String(item?.id ?? "").trim() === id);
    // 同一迭代可能同时来自当前下拉和表格缓存；优先使用带有效日期的条目。
    const iteration = matching.find((item) => toDateText(item.start_date) || toDateText(item.end_date)) || matching[0];
    if (!iteration) return null;
    const start = toDateText(iteration.start_date);
    const end = toDateText(iteration.end_date);
    if (!start && !end) return null;
    return [start || end, end || start];
}
