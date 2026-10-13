/**
 * 根据工作项创建时的项目上下文解析默认项目。
 *
 * `projectIds` 为空表示「全部项目」，多个值表示跨项目范围，这两种场景都
 * 没有唯一的默认项目；只有恰好一个项目时才允许自动回填。显式传入的
 * `projectId`（例如从项目详情/父工作项打开创建抽屉）优先保留。
 */
export function resolveProjectIdFromScope(
    projectIds?: readonly (string | null | undefined)[],
    explicitProjectId?: string | null,
): string {
    const explicit = String(explicitProjectId ?? "").trim();
    if (explicit) return explicit;

    const ids = Array.from(new Set(
        (projectIds || [])
            .map((id) => String(id ?? "").trim())
            .filter(Boolean),
    ));
    return ids.length === 1 ? ids[0]! : "";
}
