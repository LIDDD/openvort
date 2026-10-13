import { ref, type ComputedRef } from "vue";
import { message } from "@openvort/vort-ui";
import {
    reorderVortflowBug,
    reorderVortflowStory,
    reorderVortflowTask,
} from "@/api";
import type {
    RowItem,
    WorkItemType,
} from "@/components/vort-biz/work-item/WorkItemTable.types";

/**
 * 工作项拖拽：Gitee 风格，按鼠标在行内 y 坐标分三段落点。
 *
 * 落点语义（mode）：
 * - before:    source 落到目标行**上方**（与目标同级 / 同 parent，sort_order < target）
 * - after:     source 落到目标行**下方**（与目标同级 / 同 parent，sort_order > target）
 * - inside:    source 嵌入到目标行内部（成为目标的子或挂载到目标下）
 * - forbidden: 任意被禁止的组合（自身 / 后代 / 跨项目 / 归档 / 反向嵌套等）
 *
 * 跨类型嵌入规则：
 * - 需求 → 需求 inside:  parent_id = target
 * - 任务 → 需求 inside:  story_id = target, parent_id = null
 * - 任务 → 任务 inside:  parent_id = target（同 story 内）
 * - 缺陷 → 需求 inside:  story_id = target, task_id = null
 * - 缺陷 → 任务 inside:  task_id = target, story_id 由后端从 task.story_id 推断
 * - 需求 → 任务/缺陷:   禁止（反向嵌套）
 * - 任务 → 缺陷:       禁止
 * - 缺陷 → 缺陷:       禁止
 *
 * 同级排序（before/after）只在 source.type === target.type 时生效；
 * 跨类型时 before/after 一律降级为 forbidden（语义上无法保证 sort_order 可比）。
 */
export type WorkItemDropMode = "" | "before" | "after" | "inside" | "forbidden";

export const WORK_ITEM_DRAG_MIME = "application/x-vortflow-item";

/** 上 25% → before；下 25% → after；中间 50% → inside */
const INSIDE_THRESHOLD_TOP = 0.25;
const INSIDE_THRESHOLD_BOTTOM = 0.75;

export interface UseWorkItemStoryDragOptions {
    enabled: ComputedRef<boolean>;
    projectId: ComputedRef<string>;
    itemRowsById: Record<string, RowItem>;
    itemChildrenMap: Record<string, RowItem[]>;
    expandedItemIds: Record<string, boolean>;
    expandingItemIds: Record<string, boolean>;
    loadChildItems: (parentId: string, type: WorkItemType, projectId?: string) => Promise<RowItem[]>;
    refreshTable: () => void;
    getVisibleRows: () => RowItem[];
}

export function useWorkItemStoryDrag(options: UseWorkItemStoryDragOptions) {
    const isDragging = ref(false);
    const dragSourceId = ref("");
    const dragSourceType = ref<WorkItemType | "">("");
    const dragSourceProjectId = ref("");
    const dropTargetId = ref("");
    const dropMode = ref<WorkItemDropMode>("");

    const reset = () => {
        isDragging.value = false;
        dragSourceId.value = "";
        dragSourceType.value = "";
        dragSourceProjectId.value = "";
        dropTargetId.value = "";
        dropMode.value = "";
    };

    /** 检查 target 是否在 source 已加载到本地的后代里（仅对需求/任务有意义） */
    const isLocalDescendant = (targetId: string, sourceId: string): boolean => {
        if (!targetId || !sourceId) return false;
        const queue: string[] = [sourceId];
        const visited = new Set<string>();
        while (queue.length) {
            const id = queue.shift()!;
            if (visited.has(id)) continue;
            visited.add(id);
            const children = options.itemChildrenMap[id] || [];
            for (const c of children) {
                const cid = c.backendId || "";
                if (!cid) continue;
                if (cid === targetId) return true;
                queue.push(cid);
            }
        }
        return false;
    };

    const sameProject = (record: RowItem): boolean => {
        const targetProj = record.projectId || "";
        if (!targetProj || !dragSourceProjectId.value) return true;
        return targetProj === dragSourceProjectId.value;
    };

    /** 允许某种 source → target 的嵌入吗 */
    const canEmbed = (sourceType: WorkItemType, targetType: WorkItemType): boolean => {
        if (sourceType === "需求") return targetType === "需求";
        if (sourceType === "任务") return targetType === "需求" || targetType === "任务";
        if (sourceType === "缺陷") return targetType === "需求" || targetType === "任务";
        return false;
    };

    const computeRawMode = (offsetY: number, height: number): WorkItemDropMode => {
        if (height <= 0) return "inside";
        const ratio = offsetY / height;
        if (ratio < INSIDE_THRESHOLD_TOP) return "before";
        if (ratio > INSIDE_THRESHOLD_BOTTOM) return "after";
        return "inside";
    };

    const finalizeMode = (rawMode: WorkItemDropMode, target: RowItem): WorkItemDropMode => {
        if (!target.backendId) return "forbidden";
        if (target.backendId === dragSourceId.value) return "forbidden";
        if (target.isArchived) return "forbidden";
        if (!sameProject(target)) return "forbidden";

        const sourceType = dragSourceType.value as WorkItemType;
        const targetType = target.type as WorkItemType;
        if (!sourceType || !targetType) return "forbidden";

        if (rawMode === "inside") {
            if (!canEmbed(sourceType, targetType)) return "forbidden";
            // 仅对同类型嵌入做后代环路检查（跨类型不构成树循环）
            if (sourceType === targetType && isLocalDescendant(target.backendId, dragSourceId.value)) {
                return "forbidden";
            }
            return "inside";
        }
        // before / after：只允许同类型同级排序
        if (sourceType !== targetType) return "forbidden";
        // Bug lists are ordered by created_at desc on the backend (no longer by
        // sort_order), so sibling reorder has no visible effect for bugs.
        // Disable it to avoid "drag did nothing" confusion; inside-embed still works.
        if (sourceType === "缺陷") return "forbidden";
        // 目标的 parent 不能是 source 的后代（拖到自己后代附近）
        const targetParentId = target.parentId || "";
        if (targetParentId && isLocalDescendant(targetParentId, dragSourceId.value)) {
            return "forbidden";
        }
        return rawMode;
    };

    // ---------- Drag start ----------

    const onSourceDragStart = (event: DragEvent, record: RowItem) => {
        if (!options.enabled.value) return;
        if (!record.backendId) return;
        if (record.isArchived) {
            event.preventDefault();
            return;
        }
        isDragging.value = true;
        dragSourceId.value = record.backendId;
        dragSourceType.value = record.type;
        dragSourceProjectId.value = record.projectId || "";
        try {
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData(WORK_ITEM_DRAG_MIME, record.backendId);
                event.dataTransfer.setData("text/plain", record.title || record.backendId);
            }
        } catch {
            // ignore browser-specific dataTransfer restrictions
        }
    };

    const onSourceDragEnd = () => {
        reset();
    };

    const bindDragSource = (record: RowItem) => {
        if (!options.enabled.value || record.isArchived) return {};
        return {
            draggable: true,
            onDragstart: (e: DragEvent) => onSourceDragStart(e, record),
            onDragend: onSourceDragEnd,
        };
    };

    // ---------- Drop target ----------

    const onRowDragOver = (event: DragEvent, record: RowItem) => {
        if (!isDragging.value) return;
        if (!record.backendId) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";

        const currentTarget = event.currentTarget as HTMLElement | null;
        if (!currentTarget) return;
        const rect = currentTarget.getBoundingClientRect();
        const offsetY = event.clientY - rect.top;
        const rawMode = computeRawMode(offsetY, rect.height);
        const mode = finalizeMode(rawMode, record);

        dropTargetId.value = record.backendId;
        dropMode.value = mode;
    };

    const onRowDragLeave = (event: DragEvent, record: RowItem) => {
        if (dropTargetId.value !== record.backendId) return;
        const related = event.relatedTarget as Node | null;
        const current = event.currentTarget as Node | null;
        if (current && related && current.contains(related)) return;
        dropTargetId.value = "";
        dropMode.value = "";
    };

    const onRowDrop = async (event: DragEvent, record: RowItem) => {
        event.preventDefault();
        event.stopPropagation();
        const mode = dropMode.value;
        const sourceId = dragSourceId.value;
        const sourceType = dragSourceType.value as WorkItemType;
        reset();
        if (!sourceId || !sourceType) return;
        if (mode === "forbidden" || !mode) {
            message.warning("无法放置到这里");
            return;
        }
        if (mode === "inside") {
            await commitDropInside(sourceId, sourceType, record);
        } else if (mode === "before") {
            await commitDropAdjacent(sourceId, sourceType, record, "before");
        } else if (mode === "after") {
            await commitDropAdjacent(sourceId, sourceType, record, "after");
        }
    };

    const bindRowDropTarget = (record: RowItem) => {
        if (!options.enabled.value) return {};
        return {
            onDragover: (e: DragEvent) => onRowDragOver(e, record),
            onDragenter: (e: DragEvent) => onRowDragOver(e, record),
            onDragleave: (e: DragEvent) => onRowDragLeave(e, record),
            onDrop: (e: DragEvent) => onRowDrop(e, record),
        };
    };

    const dropTargetClass = (record: RowItem) => {
        if (!record.backendId) return "";
        if (record.backendId !== dropTargetId.value) return "";
        if (dropMode.value === "before") return "story-drop-before";
        if (dropMode.value === "after") return "story-drop-after";
        if (dropMode.value === "inside") return "story-drop-inside";
        if (dropMode.value === "forbidden") return "story-drop-forbidden";
        return "";
    };

    // ---------- Commit ----------

    /** 在 record 同级前/后查找同 parent 且同类型的最近邻居 */
    const findSiblingNeighbor = (
        target: RowItem,
        direction: "before" | "after",
    ): RowItem | null => {
        const rows = options.getVisibleRows();
        const idx = rows.findIndex((r) => r.backendId && r.backendId === target.backendId);
        if (idx < 0) return null;
        const targetParent = target.parentId || "";
        const targetType = target.type;
        const step = direction === "before" ? -1 : 1;
        for (let i = idx + step; i >= 0 && i < rows.length; i += step) {
            const row = rows[i]!;
            if (!row.backendId) continue;
            if (row.backendId === dragSourceId.value) continue;
            if (row.type !== targetType) return null;
            const rowParent = row.parentId || "";
            if (rowParent !== targetParent) return null;
            return row;
        }
        return null;
    };

    const callReorderApi = async (
        sourceType: WorkItemType,
        sourceId: string,
        payload: any,
    ): Promise<any> => {
        if (sourceType === "需求") {
            return reorderVortflowStory(sourceId, payload);
        }
        if (sourceType === "任务") {
            return reorderVortflowTask(sourceId, payload);
        }
        return reorderVortflowBug(sourceId, payload);
    };

    const commitDropInside = async (
        sourceId: string,
        sourceType: WorkItemType,
        target: RowItem,
    ) => {
        if (!target.backendId) return;
        const targetType = target.type as WorkItemType;
        const payload: Record<string, any> = {};
        if (sourceType === "需求") {
            payload.parent_id = target.backendId;
        } else if (sourceType === "任务") {
            if (targetType === "需求") {
                payload.story_id = target.backendId;
                payload.parent_id = null;
            } else if (targetType === "任务") {
                payload.parent_id = target.backendId;
            }
        } else if (sourceType === "缺陷") {
            if (targetType === "需求") {
                payload.story_id = target.backendId;
                payload.task_id = null;
            } else if (targetType === "任务") {
                payload.task_id = target.backendId;
                // story_id 由后端从 task.story_id 推断
            }
        }

        try {
            const res: any = await callReorderApi(sourceType, sourceId, payload);
            if (res?.error || res?.detail) throw new Error(res.error || res.detail);
            message.success(`已挂到「${target.title || "工作项"}」下`);
            await refreshAfterMove({
                sourceType,
                oldParentId: options.itemRowsById[sourceId]?.parentId || "",
                newParentId: targetType === "需求" || targetType === "任务" ? target.backendId : "",
            });
        } catch (err: any) {
            message.error(extractErrorMessage(err) || "移动失败");
        }
    };

    const commitDropAdjacent = async (
        sourceId: string,
        sourceType: WorkItemType,
        target: RowItem,
        direction: "before" | "after",
    ) => {
        if (!target.backendId) return;
        const neighbor = findSiblingNeighbor(target, direction);
        const payload: Record<string, any> = {};
        if (direction === "before") {
            payload.before_id = target.backendId;
            if (neighbor?.backendId) payload.after_id = neighbor.backendId;
        } else {
            payload.after_id = target.backendId;
            if (neighbor?.backendId) payload.before_id = neighbor.backendId;
        }
        try {
            const res: any = await callReorderApi(sourceType, sourceId, payload);
            if (res?.error || res?.detail) throw new Error(res.error || res.detail);
            const newParentId = target.parentId || "";
            const oldParentId = options.itemRowsById[sourceId]?.parentId || "";
            await refreshAfterMove({
                sourceType,
                oldParentId,
                newParentId,
                preserveExpand: oldParentId === newParentId,
            });
            if (oldParentId !== newParentId) {
                message.success("已挪到目标位置");
            }
        } catch (err: any) {
            message.error(extractErrorMessage(err) || "移动失败");
        }
    };

    const refreshAfterMove = async (params: {
        sourceType: WorkItemType;
        oldParentId: string;
        newParentId: string;
        preserveExpand?: boolean;
    }) => {
        const { sourceType, oldParentId, newParentId, preserveExpand } = params;
        if (oldParentId && oldParentId !== newParentId) {
            delete options.itemChildrenMap[oldParentId];
            const oldParent = options.itemRowsById[oldParentId];
            if (oldParent && (oldParent.childrenCount || 0) > 0) {
                oldParent.childrenCount = (oldParent.childrenCount || 0) - 1;
            }
            if (options.expandedItemIds[oldParentId] && oldParent) {
                options.expandingItemIds[oldParentId] = true;
                try {
                    await options.loadChildItems(oldParentId, sourceType, oldParent.projectId);
                } catch {
                    // 失败由表格 refresh 兜底
                } finally {
                    options.expandingItemIds[oldParentId] = false;
                }
            }
        }
        if (newParentId && oldParentId !== newParentId) {
            delete options.itemChildrenMap[newParentId];
            const newParent = options.itemRowsById[newParentId];
            if (newParent) {
                newParent.childrenCount = (newParent.childrenCount || 0) + 1;
            }
            options.expandingItemIds[newParentId] = true;
            try {
                await options.loadChildItems(newParentId, sourceType, newParent?.projectId);
            } catch {
                // ignore
            } finally {
                options.expandingItemIds[newParentId] = false;
            }
            options.expandedItemIds[newParentId] = true;
        }
        if (preserveExpand && newParentId && oldParentId === newParentId) {
            delete options.itemChildrenMap[newParentId];
            if (options.expandedItemIds[newParentId]) {
                const parent = options.itemRowsById[newParentId];
                options.expandingItemIds[newParentId] = true;
                try {
                    await options.loadChildItems(newParentId, sourceType, parent?.projectId);
                } catch {
                    // ignore
                } finally {
                    options.expandingItemIds[newParentId] = false;
                }
            }
        }
        options.refreshTable();
    };

    return {
        isDragging,
        dragSourceId,
        dropTargetId,
        dropMode,
        bindDragSource,
        bindRowDropTarget,
        dropTargetClass,
    };
}

function extractErrorMessage(err: any): string {
    const data = err?.response?.data;
    if (data && typeof data === "object") {
        if (typeof data.error === "string") return data.error;
        if (typeof data.detail === "string") return data.detail;
    }
    if (typeof err?.message === "string") return err.message;
    return "";
}
