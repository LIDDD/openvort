/** 批量编辑状态时，将展示状态解析为当前工作项类型对应的后端 state。 */
export type BatchWorkItemType = "需求" | "任务" | "缺陷";
export type BatchStatusResolver = (
    workItemType: BatchWorkItemType,
    displayStatus: string,
) => readonly (string | null | undefined)[] | undefined;

const normalizeDisplayStatus = (value: unknown): string => {
    if (typeof value === "string" || typeof value === "number") {
        return String(value).trim();
    }
    if (!value || typeof value !== "object") return "";

    // 某些 Select 实现可能将整个 option 回传；只接受明确的 value/label
    // 标量，避免把对象隐式转换成 "[object Object]" 后误写入后端。
    const option = value as { value?: unknown; label?: unknown };
    for (const candidate of [option.value, option.label]) {
        if (typeof candidate === "string" || typeof candidate === "number") {
            const normalized = String(candidate).trim();
            if (normalized) return normalized;
        }
    }
    return "";
};

export function resolveBatchStatusState(
    workItemType: unknown,
    displayStatus: unknown,
    resolveStates: BatchStatusResolver,
): string | null {
    const type = typeof workItemType === "string" ? workItemType.trim() : "";
    const status = normalizeDisplayStatus(displayStatus);
    if (!type || !status) return null;

    if (type !== "需求" && type !== "任务" && type !== "缺陷") return null;
    const states = resolveStates(type, status);
    if (!Array.isArray(states)) return null;
    const state = states.find((candidate) => {
        if (typeof candidate !== "string" && typeof candidate !== "number") return false;
        return String(candidate).trim().length > 0;
    });
    if (state == null) return null;
    const normalized = String(state).trim();
    return normalized || null;
}
