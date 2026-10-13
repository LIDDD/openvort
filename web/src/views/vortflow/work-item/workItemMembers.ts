/** 解析选择器中的姓名/ID，仅允许保留服务端已保存的历史成员 ID。 */
export function resolveCollaboratorIds(
    values: string[],
    getMemberIdByName: (value: string) => string,
    existingIds: string[] = [],
): { ids: string[]; unresolved: string[] } {
    // members.id 使用 UUID hex；不能把历史误存的姓名当成可信 ID 回写。
    const persistedIds = new Set(existingIds.filter((id) => /^[a-f\d]{32}$/i.test(id)));
    const ids = new Set<string>();
    const unresolved: string[] = [];
    for (const value of values) {
        const normalized = value.trim();
        if (!normalized) continue;
        const id = getMemberIdByName(normalized) || (persistedIds.has(normalized) ? normalized : "");
        if (id) ids.add(id);
        else unresolved.push(normalized);
    }
    return { ids: [...ids], unresolved };
}
