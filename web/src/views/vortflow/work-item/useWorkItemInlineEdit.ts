import { computed, nextTick, reactive, ref, unref, type Ref } from "vue";
import { message } from "@openvort/vort-ui";
import { resolveCollaboratorIds } from "./workItemMembers";
import type {
    Priority,
    Status,
    DateRange,
    RowItem,
} from "@/components/vort-biz/work-item/WorkItemTable.types";
import {
    clampPriorityScore,
    isRowPendingForDeadline,
    priorityToDefaultScore,
    scoreToPriority,
} from "./useWorkItemCommon";

export interface UseWorkItemInlineEditOptions {
    useApi: Ref<boolean> | boolean;
    syncRecordUpdateToApi: (record: RowItem, patch: any) => Promise<void>;
    syncRecordStatusToApi: (record: RowItem, status: Status) => Promise<void>;
    getMemberIdByName: (name: string) => string;
    mapBackendPriority: any;
    toBackendPriorityLevel: (p: Priority) => number;
    toTaskEstimateHours: (p: Priority) => number;
    getBackendStatesByDisplayStatus: (type: string, status: Status) => string[];
    dynamicTagOptions: Ref<string[]>;
    baseTagOptions: Ref<string[]> | string[];
    tagDefinitions?: Ref<Array<{ id: string; name: string; color: string }>>;
    priorityModel: Record<string, Priority>;
    priorityScoreModel: Record<string, number>;
    tagsModel: Record<string, string[]>;
    collaboratorsModel: Record<string, string[]>;
    planTimeModel: Record<string, any>;
    normalizeDateValue: (value: unknown) => string;
    /** Called after a tag was created / updated so callers can reload tag definitions. */
    onTagsChanged?: () => void | Promise<void>;
    /** Called after a tag was renamed; receives oldName and newName. Optional. */
    onTagRenamed?: (oldName: string, newName: string) => void | Promise<void>;
}

export function useWorkItemInlineEdit(options: UseWorkItemInlineEditOptions) {
    const {
        syncRecordUpdateToApi,
        syncRecordStatusToApi,
        getMemberIdByName,
        dynamicTagOptions,
        baseTagOptions,
        priorityModel,
        priorityScoreModel,
        tagsModel,
        collaboratorsModel,
        planTimeModel,
        normalizeDateValue,
    } = options;

    // --- Picker open state maps ---
    const priorityPickerOpenMap = reactive<Record<string, boolean>>({});
    const tagPickerOpenMap = reactive<Record<string, boolean>>({});
    const statusPickerOpenMap = reactive<Record<string, boolean>>({});
    const ownerPickerOpenMap = reactive<Record<string, boolean>>({});
    const collaboratorsPickerOpenMap = reactive<Record<string, boolean>>({});

    // --- Plan time state ---
    const openPlanTimeFor = ref<string | null>(null);
    const planTimePickerOpen = ref(false);
    const planTimePrevValue = ref<DateRange>([]);
    const planTimeCommitted = ref(false);

    // --- Tag dialog state ---
    const tagDialogOpen = ref(false);
    const tagDialogMode = ref<"add" | "edit">("add");
    const tagDialogData = ref<{ id?: string; name?: string; color?: string }>({});
    const newTagTargetRecord = ref<RowItem | null>(null);
    const newTagTargetText = ref<string[] | undefined>(undefined);

    // --- Cell interaction helpers ---
    const getInteractiveCellKey = (record: RowItem) =>
        String(record.workNo || record.backendId || "");

    const isCellBackgroundClick = (event: Event) => {
        const target = event.target as HTMLElement | null;
        const currentTarget = event.currentTarget as HTMLElement | null;
        return !!target && !!currentTarget && target === currentTarget;
    };

    const openCellPickerOnBackgroundClick = (
        record: RowItem,
        event: Event,
        openMap: Record<string, boolean>,
    ) => {
        if (!isCellBackgroundClick(event)) return;
        openMap[getInteractiveCellKey(record)] = true;
    };

    // --- Priority ---
    const getRowPriority = (record: RowItem, text?: Priority): Priority => {
        return priorityModel[record.workNo] || text || record.priority;
    };

    const getRowPriorityScore = (record: RowItem): number => {
        const cached = priorityScoreModel[record.workNo];
        if (cached != null) return cached;
        const fromRow = (record as any).priorityScore;
        if (fromRow != null) return Number(fromRow);
        return priorityToDefaultScore(record.priority);
    };

    /** 通过 score 设置优先级（三类型均传 priority_score；缺陷同步 severity） */
    const selectPriorityScore = async (record: RowItem, score: number) => {
        const workNo = record.workNo;
        const prevScore = getRowPriorityScore(record);
        const prevLevel = getRowPriority(record, record.priority);
        const newScore = clampPriorityScore(score);
        const newLevel = scoreToPriority(newScore);

        priorityScoreModel[workNo] = newScore;
        priorityModel[workNo] = newLevel;
        record.priority = newLevel;
        (record as any).priorityScore = newScore;

        try {
            await syncRecordUpdateToApi(record, { priority_score: newScore });
        } catch (error: any) {
            priorityScoreModel[workNo] = prevScore;
            priorityModel[workNo] = prevLevel;
            record.priority = prevLevel;
            (record as any).priorityScore = prevScore;
            message.error(error?.message || "优先级同步失败");
            return;
        }
    };

    /** 兼容：按等级设置优先级（自动取段起始值作为 score）。 */
    const selectPriority = async (record: RowItem, value: Priority) => {
        await selectPriorityScore(record, priorityToDefaultScore(value));
    };

    // --- Status ---
    const getRowStatus = (record: RowItem, text?: Status): Status => {
        return text || record.status;
    };

    const selectRowStatus = async (record: RowItem, value: Status) => {
        const prev = record.status;
        record.status = value;
        if (prev !== value) {
            try {
                await syncRecordStatusToApi(record, value);
            } catch (error: any) {
                record.status = prev;
                message.error(error?.message || "状态同步失败");
                return;
            }
        }
    };

    // --- Owner ---
    const getRowOwner = (record: RowItem, text?: string): string => {
        return text || record.owner || "未指派";
    };

    const selectRowOwner = async (record: RowItem, value: string) => {
        const prev = record.owner;
        const nextOwner = value || "未指派";
        record.owner = nextOwner;
        if (prev !== nextOwner) {
            const memberId = value ? getMemberIdByName(value) : "";
            if (value && !memberId) {
                record.owner = prev;
                message.error("未找到负责人对应的成员ID，无法同步");
                return;
            }
            try {
                // 所有类型的「负责人」统一写 assignee_id；需求同步 pm_id、缺陷同步 developer_id，
                // 与 useWorkItemCrud / BatchPropertyEditor / 后端 owner 口径保持一致，避免双字段分叉。
                if (record.type === "需求") {
                    await syncRecordUpdateToApi(record, {
                        assignee_id: memberId || null,
                        pm_id: memberId || null,
                    });
                } else if (record.type === "缺陷") {
                    await syncRecordUpdateToApi(record, {
                        assignee_id: memberId || null,
                        developer_id: memberId || null,
                    });
                } else {
                    await syncRecordUpdateToApi(record, { assignee_id: memberId || null });
                }
            } catch (error: any) {
                record.owner = prev;
                message.error(error?.message || "负责人同步失败");
                return;
            }
        }
    };

    // --- Collaborators ---
    const getRowCollaborators = (record: RowItem, text?: string[]): string[] => {
        return collaboratorsModel[record.workNo] || text || record.collaborators || [];
    };

    const setRowCollaborators = async (record: RowItem, nextCollaborators: string[]) => {
        const prev = [...getRowCollaborators(record, record.collaborators)];
        const { ids, unresolved } = resolveCollaboratorIds(
            nextCollaborators, getMemberIdByName, record.collaboratorIds,
        );
        if (unresolved.length > 0) {
            message.error(`未识别的协作人：${unresolved.join("、")}，请重新选择`);
            return;
        }
        collaboratorsModel[record.workNo] = [...nextCollaborators];
        record.collaborators = [...nextCollaborators];
        try {
            await syncRecordUpdateToApi(record, { collaborators: ids });
            record.collaboratorIds = [...ids];
        } catch (error: any) {
            collaboratorsModel[record.workNo] = prev;
            record.collaborators = prev;
            message.error(error?.message || "协作者同步失败");
        }
    };

    // --- Tags ---
    // Fallback palette only used when a tag has no backend definition (e.g. legacy free-form tag
    // strings still attached to a row). Backend-defined tags always use their persisted color.
    const FALLBACK_TAG_PALETTE = [
        "#ef4444", "#d946ef", "#eab308", "#22c55e",
        "#3b82f6", "#f97316", "#14b8a6", "#8b5cf6",
    ];

    const getTagColor = (name: string): string => {
        const defs = options.tagDefinitions?.value;
        if (defs) {
            const match = defs.find(t => t.name === name);
            if (match?.color) return match.color;
        }
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
        return FALLBACK_TAG_PALETTE[hash % FALLBACK_TAG_PALETTE.length]!;
    };

    const getRowTags = (record: RowItem, text?: string[]): string[] => {
        return tagsModel[record.workNo] || text || [];
    };

    const rowTagOptions = computed(() => dynamicTagOptions.value.length ? dynamicTagOptions.value : unref(baseTagOptions));

    const setRowTags = async (record: RowItem, nextTags: string[]) => {
        const prev = [...getRowTags(record, record.tags)];
        tagsModel[record.workNo] = [...nextTags];
        record.tags = [...nextTags];
        try {
            await syncRecordUpdateToApi(record, { tags: nextTags });
        } catch (error: any) {
            tagsModel[record.workNo] = prev;
            record.tags = prev;
            message.error(error?.message || "标签同步失败");
        }
    };

    const openCreateTagDialog = (record?: RowItem | null, text?: string[]) => {
        newTagTargetRecord.value = record || null;
        newTagTargetText.value = text;
        tagDialogMode.value = "add";
        tagDialogData.value = {};
        tagDialogOpen.value = true;
    };

    const openEditTagDialog = (option: { value: string; label?: string; color?: string }) => {
        const defs = options.tagDefinitions?.value || [];
        const def = defs.find(t => t.name === option.value);
        if (!def?.id) {
            message.warning("该标签暂未持久化，无法编辑。请刷新页面后重试");
            return;
        }
        newTagTargetRecord.value = null;
        newTagTargetText.value = undefined;
        tagDialogMode.value = "edit";
        tagDialogData.value = { id: def.id, name: def.name, color: def.color };
        tagDialogOpen.value = true;
    };

    const handleTagDialogSaved = async (saved: { id: string; name: string; color: string }) => {
        const mode = tagDialogMode.value;
        const previousName = mode === "edit" ? tagDialogData.value.name : undefined;

        if (options.onTagsChanged) {
            try {
                await options.onTagsChanged();
            } catch { /* swallow refresh errors; UI keeps previous data */ }
        }

        if (mode === "edit" && previousName && saved.name && previousName !== saved.name) {
            // Backend already replaced tag references in items; reflect that locally so cached
            // rows pick up the new name without waiting for a full reload.
            for (const workNo of Object.keys(tagsModel)) {
                const list = tagsModel[workNo];
                if (Array.isArray(list) && list.includes(previousName)) {
                    tagsModel[workNo] = list.map(t => (t === previousName ? saved.name : t));
                }
            }
            // Drop the renamed tag from dynamicTagOptions so collectTagOptions / baseTagOptions
            // become the source of truth on the next refresh; meanwhile inject the new name.
            const idx = dynamicTagOptions.value.indexOf(previousName);
            if (idx >= 0) {
                const next = [...dynamicTagOptions.value];
                next.splice(idx, 1);
                if (!next.includes(saved.name)) next.push(saved.name);
                dynamicTagOptions.value = next;
            }
            if (options.onTagRenamed) {
                try { await options.onTagRenamed(previousName, saved.name); } catch { /* ignore */ }
            }
        }

        if (mode === "add" && saved.name) {
            // Surface the newly-created tag in the picker immediately, ahead of the next
            // collectTagOptions pass triggered by table refresh.
            if (dynamicTagOptions.value.length && !dynamicTagOptions.value.includes(saved.name)) {
                dynamicTagOptions.value = [...dynamicTagOptions.value, saved.name];
            }
            if (newTagTargetRecord.value) {
                const currentTags = getRowTags(newTagTargetRecord.value, newTagTargetText.value);
                if (!currentTags.includes(saved.name)) {
                    await setRowTags(newTagTargetRecord.value, [...currentTags, saved.name]);
                }
            }
        }

        newTagTargetRecord.value = null;
        newTagTargetText.value = undefined;
        tagDialogOpen.value = false;
    };

    // --- Plan time ---
    const onPlanTimeChange = async (record: RowItem, value?: any) => {
        const workNo = record.workNo;
        const isClearing = !value || value.length === 0 || (value.length === 2 && !value[0] && !value[1]);
        if (isClearing) {
            planTimeCommitted.value = true;
            const prev = [...planTimePrevValue.value] as DateRange;
            planTimeModel[workNo] = ["", ""];
            record.planTime = ["", ""];
            openPlanTimeFor.value = null;
            try {
                await syncRecordUpdateToApi(record, { plan_start: "", deadline: "" });
            } catch (error: any) {
                planTimeModel[workNo] = prev;
                record.planTime = prev;
                message.error(error?.message || "计划时间清空失败");
            }
            return;
        }
        if (value.length !== 2) return;
        const start = normalizeDateValue(value[0]);
        const end = normalizeDateValue(value[1]);
        if (!start || !end) return;
        planTimeCommitted.value = true;
        const prev = [...planTimePrevValue.value] as DateRange;
        planTimeModel[workNo] = [start, end];
        record.planTime = [start, end];
        openPlanTimeFor.value = null;
        try {
            await syncRecordUpdateToApi(record, { plan_start: start, deadline: end });
        } catch (error: any) {
            planTimeModel[workNo] = prev;
            record.planTime = prev;
            message.error(error?.message || "计划时间同步失败");
        }
    };

    const onPlanTimeOpenChange = (record: RowItem, open: boolean) => {
        if (!open && openPlanTimeFor.value === record.workNo && !planTimeCommitted.value) {
            const workNo = record.workNo;
            planTimeModel[workNo] = [...planTimePrevValue.value];
            record.planTime = [...planTimePrevValue.value];
            openPlanTimeFor.value = null;
        }
    };

    const getRowPlanTime = (record: RowItem, text?: DateRange): DateRange => {
        return planTimeModel[record.workNo] || text || record.planTime;
    };

    const DONE_STATUSES = new Set(["已关闭", "已完成", "已修复", "发布完成", "测试完成", "开发完成"]);

    const getRowPlanTimeText = (record: RowItem, text?: DateRange): string => {
        const value = getRowPlanTime(record, text);
        const start = normalizeDateValue(value[0]);
        const end = normalizeDateValue(value[1]);
        if (!start && !end) return "-";
        const currentYear = String(new Date().getFullYear());
        const stripYear = (d: string) => d.slice(5);
        if (!end) {
            return (start.startsWith(currentYear) ? stripYear(start) : start) + " 开始";
        }
        if (!start) return "~" + (end.startsWith(currentYear) ? stripYear(end) : end);
        const startYear = start.slice(0, 4);
        const endYear = end.slice(0, 4);
        if (startYear === endYear) {
            const isCurrentYear = startYear === currentYear;
            return `${isCurrentYear ? stripYear(start) : start}~${stripYear(end)}`;
        }
        return `${start}~${end}`;
    };

    const getRowOverdueInfo = (record: RowItem, text?: DateRange): { days: number; completed: boolean } | null => {
        const value = getRowPlanTime(record, text);
        const end = normalizeDateValue(value[1]);
        if (!end) return null;
        // 需求计划时间只覆盖开发阶段；进入待测试或后续状态后不再展示开发逾期。
        if (record.type === "需求" && !isRowPendingForDeadline(record)) return null;
        const endDate = new Date(end + "T00:00:00");
        const isDone = DONE_STATUSES.has(record.status);
        const refDate = new Date();
        if (isDone && record._updatedAtRaw) {
            refDate.setTime(new Date(record._updatedAtRaw).getTime());
        }
        refDate.setHours(0, 0, 0, 0);
        const diffDays = Math.floor((refDate.getTime() - endDate.getTime()) / 86400000);
        if (diffDays <= 0) return null;
        return { days: diffDays, completed: isDone };
    };

    /**
     * 工作项停滞判定：与成员级 stale_count 口径一致。
     * - 仅在「在手」状态下计算（已完成/已关闭/已取消等终态不展示）
     * - 默认 7 天无 Event/Comment（last_activity_at）即视为停滞
     */
    const STALE_DAYS = 7;
    const getRowStaleInfo = (record: RowItem): { days: number } | null => {
        if (DONE_STATUSES.has(record.status)) return null;
        const lastRaw = record._lastActivityAtRaw || record._updatedAtRaw;
        if (!lastRaw) return null;
        const lastTs = new Date(lastRaw).getTime();
        if (Number.isNaN(lastTs)) return null;
        const diffDays = Math.floor((Date.now() - lastTs) / 86400000);
        if (diffDays < STALE_DAYS) return null;
        return { days: diffDays };
    };

    const togglePlanTimeMenu = (workNo: string, record?: RowItem, text?: DateRange) => {
        const willOpen = openPlanTimeFor.value !== workNo;
        if (willOpen) {
            const value = record ? getRowPlanTime(record, text) : undefined;
            const start = normalizeDateValue(value?.[0]);
            const end = normalizeDateValue(value?.[1]);
            if (start && end) {
                planTimeModel[workNo] = [start, end];
            }
            planTimePrevValue.value = planTimeModel[workNo] ? [...planTimeModel[workNo]] : [];
            planTimeCommitted.value = false;
            planTimePickerOpen.value = false;
            openPlanTimeFor.value = workNo;
            nextTick(() => {
                planTimePickerOpen.value = true;
            });
        } else {
            planTimePickerOpen.value = false;
            openPlanTimeFor.value = null;
        }
    };

    return {
        priorityPickerOpenMap,
        tagPickerOpenMap,
        statusPickerOpenMap,
        ownerPickerOpenMap,
        collaboratorsPickerOpenMap,

        getInteractiveCellKey,
        isCellBackgroundClick,
        openCellPickerOnBackgroundClick,

        getRowPriority,
        getRowPriorityScore,
        selectPriority,
        selectPriorityScore,
        getRowStatus,
        selectRowStatus,
        getRowOwner,
        selectRowOwner,
        getRowCollaborators,
        setRowCollaborators,
        getRowTags,
        setRowTags,
        rowTagOptions,
        getRowPlanTimeText,
        getRowOverdueInfo,
        getRowStaleInfo,
        onPlanTimeChange,
        onPlanTimeOpenChange,
        getRowPlanTime,
        togglePlanTimeMenu,

        getTagColor,
        openCreateTagDialog,
        openEditTagDialog,
        handleTagDialogSaved,
        tagDialogOpen,
        tagDialogMode,
        tagDialogData,

        openPlanTimeFor,
        planTimePickerOpen,
        planTimePrevValue,
        planTimeCommitted,
    };
}
