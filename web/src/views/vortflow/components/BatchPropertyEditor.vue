<script setup lang="ts">
import { ref, computed, watch, type Ref } from "vue";
import { Button, Select, SelectOption, Dialog, Input, Divider, message } from "@openvort/vort-ui";
import WorkItemPriority from "@/components/vort-biz/work-item/WorkItemPriority.vue";
import WorkItemStatus from "@/components/vort-biz/work-item/WorkItemStatus.vue";
import WorkItemMemberPicker from "@/components/vort-biz/work-item/WorkItemMemberPicker.vue";
import WorkItemTagPicker from "@/components/vort-biz/work-item/WorkItemTagPicker.vue";
import IterationSelect, { type IterationSelectOption } from "@/components/vort-biz/work-item/IterationSelect.vue";
import { CircleMinus, Plus } from "lucide-vue-next";
import type { RowItem, WorkItemType, StatusOption } from "@/components/vort-biz/work-item/WorkItemTable.types";
import { useWorkItemCommon, priorityToDefaultScore } from "../work-item/useWorkItemCommon";
import {
    updateVortflowStory, updateVortflowTask, updateVortflowBug,
    getVortflowVersions, getVortflowStories,
    getVortgitRepos,
    addVortflowIterationStory, addVortflowIterationTask, addVortflowIterationBug,
    removeVortflowIterationStory, removeVortflowIterationTask, removeVortflowIterationBug,
} from "@/api";
import { useVortFlowStore } from "@/stores";
import { resolveBatchStatusState } from "../work-item/batchStatusMapping";

interface Props {
    selectedRows: RowItem[];
    workItemType?: WorkItemType;
    statusOptions?: StatusOption[];
}

const props = withDefaults(defineProps<Props>(), {
    workItemType: "缺陷",
    statusOptions: () => [],
});

const emit = defineEmits<{
    submit: [changes: PropertyChange[]];
    cancel: [];
    done: [];
}>();

const open = defineModel<boolean>("open", { default: false });

export interface PropertyChange {
    property: string;
    operator: "set" | "clear";
    value: any;
}

const {
    ownerGroups, memberOptions, toBackendPriorityLevel,
    getBackendStatesByDisplayStatus, getMemberIdByName,
    toTaskEstimateHours,
    getEnrichedOwnerGroups, defaultCollapsedGroups, recordRecentMember,
} = useWorkItemCommon();

const vortFlowStore = useVortFlowStore();

const batchEnrichedGroups = ref<{ label: string; members: string[] }[]>([]);
const batchEnrichedCollapsed = ref<string[]>([]);
const batchActiveGroups = computed(() =>
    batchEnrichedGroups.value.length > 0 ? batchEnrichedGroups.value : ownerGroups.value,
);

const submitting = ref(false);

// vort-range-picker / vort-date-picker(无 valueFormat 场景) v-model 是 Date 对象，
// 这里统一格式化成 YYYY-MM-DD，避免直接拼字符串得到 "Tue Apr 28 2026..." 这种后端无法解析的格式。
const toBackendDateString = (value: unknown): string | null => {
    if (value == null || value === "") return null;
    if (value instanceof Date && !isNaN(value.getTime())) {
        const y = value.getFullYear();
        const m = String(value.getMonth() + 1).padStart(2, "0");
        const d = String(value.getDate()).padStart(2, "0");
        return `${y}-${m}-${d}`;
    }
    if (typeof value === "string") {
        const trimmed = value.trim();
        if (!trimmed) return null;
        if (/^\d{4}-\d{2}-\d{2}/.test(trimmed)) return trimmed;
        const parsed = new Date(trimmed);
        if (!Number.isNaN(parsed.getTime())) return toBackendDateString(parsed);
    }
    return null;
};

const repoOptions = ref<{ label: string; value: string }[]>([]);
const iterationOptions = ref<{ label: string; value: string }[]>([]);
const versionOptions = ref<{ label: string; value: string }[]>([]);
const storyOptions = ref<{ label: string; value: string }[]>([]);

const selectedProjectIds = computed(() => [...new Set(
    (props.selectedRows || []).map((row) => String(row.projectId || "")).filter(Boolean),
)]);
const iterationProjectId = computed(() => {
    if (selectedProjectIds.value.length === 1) return selectedProjectIds.value[0] || "";
    return selectedProjectIds.value.length ? "" : (vortFlowStore.selectedProjectId || "");
});

const handleIterationOptionsChange = (options: IterationSelectOption[]) => {
    const merged = new Map(iterationOptions.value.map((item) => [String(item.value), item]));
    for (const item of options || []) {
        const id = String(item?.id || "");
        const name = String(item?.name || "");
        if (id && name) merged.set(id, { label: name, value: id });
    }
    iterationOptions.value = [...merged.values()];
};

const getIterationLabel = (value: unknown) => {
    const id = String(value || "");
    return iterationOptions.value.find((item) => String(item.value) === id)?.label || id;
};

const loadDynamicOptions = async () => {
    iterationOptions.value = [];
    const projectId = vortFlowStore.selectedProjectId || undefined;
    const [repoRes, verRes, storyRes] = await Promise.allSettled([
        getVortgitRepos({ project_id: projectId, page_size: 200 }),
        getVortflowVersions({ project_id: projectId, page_size: 200 }),
        getVortflowStories({ project_id: projectId, page_size: 200 }),
    ]);
    if (repoRes.status === "fulfilled") {
        const items = (repoRes.value as any)?.items || [];
        repoOptions.value = items.map((r: any) => ({ label: r.name || r.full_name, value: r.id }));
    }
    if (verRes.status === "fulfilled") {
        const items = (verRes.value as any)?.items || [];
        versionOptions.value = items.map((v: any) => ({ label: v.name, value: v.id }));
    }
    if (storyRes.status === "fulfilled") {
        const items = (storyRes.value as any)?.items || [];
        storyOptions.value = items.map((s: any) => ({ label: s.title, value: s.id }));
    }
};

const allTagOptions = computed(() => {
    const set = new Set<string>();
    for (const row of props.selectedRows) {
        for (const tag of row.tags || []) {
            if (tag) set.add(tag);
        }
    }
    const defaults = ["客户需求", "演示站", "运营需求", "待开会确认", "已发布", "高优先", "稳定性", "UI优化"];
    for (const t of defaults) set.add(t);
    return [...set];
});

watch(open, (v) => {
    if (v) {
        nextId.value = 1;
        changeRows.value = [{ id: 0, property: "priority", operator: "set", value: null }];
        loadDynamicOptions();
        const pid = vortFlowStore.selectedProjectId || "";
        getEnrichedOwnerGroups(pid).then((groups) => {
            batchEnrichedGroups.value = groups;
            batchEnrichedCollapsed.value = defaultCollapsedGroups(groups);
        });
    }
});

const PROPERTY_OPTIONS = [
    { label: "优先级", value: "priority" },
    { label: "工作项状态", value: "status" },
    { label: "负责人", value: "owner" },
    { label: "协作者", value: "collaborators" },
    { label: "标签", value: "tags" },
    { label: "计划时间", value: "planTime" },
    { label: "预计工时", value: "estimateHours" },
    { label: "关联仓库", value: "repo" },
    { label: "关联版本", value: "version" },
    { label: "关联迭代", value: "iteration" },
    { label: "实际开始时间", value: "startAt" },
    { label: "实际结束时间", value: "endAt" },
    { label: "父工作项", value: "parentId" },
];

interface ChangeRow {
    id: number;
    property: string;
    operator: "set" | "clear";
    value: any;
}

const nextId = ref(1);
const changeRows = ref<ChangeRow[]>([
    { id: 0, property: "priority", operator: "set", value: null },
]);

const addRow = () => {
    const usedProps = new Set(changeRows.value.map(r => r.property));
    const available = PROPERTY_OPTIONS.find(o => !usedProps.has(o.value));
    if (available) {
        changeRows.value.push({ id: nextId.value++, property: available.value, operator: "set", value: null });
    }
};

const removeRow = (id: number) => {
    if (changeRows.value.length <= 1) return;
    changeRows.value = changeRows.value.filter(r => r.id !== id);
};

const availableProperties = (currentProp: string) => {
    const used = new Set(changeRows.value.map(r => r.property));
    return PROPERTY_OPTIONS.filter(o => o.value === currentProp || !used.has(o.value));
};

const projectGroups = computed(() => {
    const groups: Record<string, { name: string; items: RowItem[] }> = {};
    for (const row of props.selectedRows) {
        const pid = row.projectId || "_no_project";
        const pname = row.projectName || "未关联项目";
        if (!groups[pid]) groups[pid] = { name: pname, items: [] };
        groups[pid].items.push(row);
    }
    return Object.values(groups);
});

const buildPatch = (change: PropertyChange, row: RowItem): Record<string, any> => {
    const patch: Record<string, any> = {};
    const val = change.operator === "clear" ? null : change.value;
    switch (change.property) {
        case "priority": {
            const level = val ? toBackendPriorityLevel(val) : 4;
            const score = val ? priorityToDefaultScore(val) : 20;
            patch.priority_score = score;
            if (row.type === "缺陷") {
                patch.severity = level;
            } else if (row.type === "需求") {
                patch.priority = level;
            }
            break;
        }
        case "status": {
            const state = resolveBatchStatusState(
                row.type || props.workItemType,
                val,
                getBackendStatesByDisplayStatus,
            );
            if (!state) {
                const typeLabel = row.type || props.workItemType || "当前工作项";
                const statusLabel = typeof val === "object" && val !== null
                    ? String((val as any).label || (val as any).value || "")
                    : String(val || "");
                throw new Error(`「${statusLabel}」不适用于${typeLabel}，无法同步`);
            }
            patch.state = state;
            break;
        }
        case "owner": {
            // 所有类型统一写 assignee_id；需求同步 pm_id、缺陷同步 developer_id，避免老字段残留分叉。
            // ID 解析失败时一律置 null 而不是把名字当 ID，避免后端把名字写到 assignee_id 字段，
            // 造成「负责人=张三这个字符串」式的脏数据，进而导致企微通知静默失败。
            const memberId = val ? getMemberIdByName(val) || null : null;
            patch.assignee_id = memberId;
            if (row.type === "需求") patch.pm_id = memberId;
            else if (row.type === "缺陷") patch.developer_id = memberId;
            break;
        }
        case "collaborators": {
            // 协作人列表必须是 member_id 数组而非显示名，否则会被原样存进 collaborators_json，
            // 后续状态变更/字段变更通知会拿名字当 recipient_id 投递，IM 发不出去且没日志。
            const names: string[] = Array.isArray(val) ? val.filter(Boolean) : [];
            patch.collaborators = names
                .map((n) => getMemberIdByName(n))
                .filter((id): id is string => Boolean(id));
            break;
        }
        case "tags":
            patch.tags = val || [];
            break;
        case "planTime":
            if (val && Array.isArray(val) && val.length === 2) {
                patch.plan_start = toBackendDateString(val[0]);
                patch.deadline = toBackendDateString(val[1]);
            } else {
                patch.plan_start = null;
                patch.deadline = null;
            }
            break;
        case "estimateHours":
            patch.estimate_hours = val ? Number(val) : 0;
            break;
        case "startAt":
            patch.start_at = toBackendDateString(val);
            break;
        case "endAt":
            patch.end_at = toBackendDateString(val);
            break;
        case "repo":
            patch.repo_id = val;
            break;
        case "parentId":
            patch.parent_id = val;
            break;
        case "version":
        case "iteration":
            break;
    }
    return patch;
};

const applyIterationChange = async (row: RowItem, change: PropertyChange) => {
    const id = String(row.backendId || "").trim();
    if (!id) return;
    const newIterationId = change.operator === "clear" ? null : (change.value as string);
    const oldIterationId = row.iterationId || "";
    if (oldIterationId === (newIterationId || "")) return;
    if (oldIterationId) {
        try {
            if (row.type === "需求") await removeVortflowIterationStory(oldIterationId, id);
            else if (row.type === "任务") await removeVortflowIterationTask(oldIterationId, id);
            else if (row.type === "缺陷") await removeVortflowIterationBug(oldIterationId, id);
        } catch { /* old link may already be gone */ }
    }
    if (newIterationId) {
        if (row.type === "需求") await addVortflowIterationStory(newIterationId, { story_id: id });
        else if (row.type === "任务") await addVortflowIterationTask(newIterationId, { task_id: id });
        else if (row.type === "缺陷") await addVortflowIterationBug(newIterationId, { bug_id: id });
    }
};

const handleSubmit = async () => {
    const allChanges: PropertyChange[] = changeRows.value
        .filter(r => r.operator === "clear" || r.value != null)
        .map(r => ({ property: r.property, operator: r.operator, value: r.value }));
    if (allChanges.length === 0) {
        message.warning("请至少选择一个要修改的属性");
        return;
    }
    const iterationChange = allChanges.find(c => c.property === "iteration");
    const fieldChanges = allChanges.filter(c => c.property !== "version" && c.property !== "iteration");
    submitting.value = true;
    let successCount = 0;
    let failCount = 0;
    try {
        for (const row of props.selectedRows) {
            const id = String(row.backendId || "").trim();
            if (!id) continue;
            try {
                if (fieldChanges.length > 0) {
                    const merged: Record<string, any> = {};
                    for (const c of fieldChanges) Object.assign(merged, buildPatch(c, row));
                    if (Object.keys(merged).length > 0) {
                        if (row.type === "需求") await updateVortflowStory(id, merged);
                        else if (row.type === "任务") await updateVortflowTask(id, merged);
                        else if (row.type === "缺陷") await updateVortflowBug(id, merged);
                    }
                }
                if (iterationChange) await applyIterationChange(row, iterationChange);
                successCount++;
            } catch { failCount++; }
        }
        if (failCount > 0) message.warning(`成功 ${successCount} 项，失败 ${failCount} 项`);
        else message.success(`已批量修改 ${successCount} 个工作项`);
        emit("submit", allChanges);
        emit("done");
        open.value = false;
    } finally {
        submitting.value = false;
    }
};

const handleCancel = () => {
    open.value = false;
    emit("cancel");
};
</script>

<template>
    <Dialog v-model:open="open" title="修改属性" width="720px" @cancel="handleCancel">
        <div class="batch-editor">
            <div v-if="projectGroups.length" class="selected-summary">
                <div v-for="group in projectGroups" :key="group.name" class="project-group-tag">
                    <span class="group-name">{{ group.name }}</span>
                    <span class="group-detail">{{ workItemType }} {{ group.items.length }} 个</span>
                </div>
            </div>
            <div v-else class="empty-hint">请先在表格中选中要修改的工作项</div>

            <Divider style="margin: 12px 0" />

            <div class="change-rows">
                <div v-for="row in changeRows" :key="row.id" class="change-row">
                    <Select v-model="row.property">
                        <SelectOption
                            v-for="opt in availableProperties(row.property)"
                            :key="opt.value"
                            :value="opt.value"
                        >{{ opt.label }}</SelectOption>
                    </Select>

                    <Select v-model="row.operator">
                        <SelectOption value="set">修改为</SelectOption>
                        <SelectOption value="clear">清空</SelectOption>
                    </Select>

                    <div v-if="row.operator === 'set'" class="value-editor">
                        <WorkItemPriority
                            v-if="row.property === 'priority'"
                            :model-value="row.value || 'medium'"
                            :enable-score-slider="false"
                            @change="(v) => row.value = v"
                        />
                        <WorkItemStatus
                            v-else-if="row.property === 'status'"
                            :model-value="row.value || ''"
                            :options="statusOptions"
                            @change="(v) => row.value = v"
                        />
                        <WorkItemMemberPicker
                            v-else-if="row.property === 'owner'"
                            mode="owner"
                            :owner="row.value || ''"
                            :groups="batchActiveGroups"
                            :default-collapsed="batchEnrichedCollapsed"
                            @update:owner="(v) => { row.value = v; if (v) recordRecentMember(v); }"
                        />
                        <WorkItemMemberPicker
                            v-else-if="row.property === 'collaborators'"
                            mode="collaborators"
                            :collaborators="row.value || []"
                            :groups="batchActiveGroups"
                            :default-collapsed="batchEnrichedCollapsed"
                            @update:collaborators="(v) => { row.value = v; v.forEach(recordRecentMember); }"
                        />
                        <WorkItemTagPicker
                            v-else-if="row.property === 'tags'"
                            :model-value="row.value || []"
                            :options="allTagOptions"
                            @change="(v) => row.value = v"
                        />
                        <vort-range-picker
                            v-else-if="row.property === 'planTime'"
                            v-model="row.value"
                            size="small"
                            format="YYYY-MM-DD"
                            separator="~"
                            :placeholder="['开始日期', '结束日期']"
                            allow-clear
                            style="width: 100%"
                        />
                        <vort-date-picker
                            v-else-if="row.property === 'startAt' || row.property === 'endAt'"
                            :model-value="row.value || ''"
                            size="small"
                            value-format="YYYY-MM-DD"
                            placeholder="选择日期"
                            allow-clear
                            style="width: 100%"
                            @change="(v: any) => row.value = v"
                        />
                        <vort-input-number
                            v-else-if="row.property === 'estimateHours'"
                            v-model="row.value"
                            :min="0"
                            placeholder="小时数"
                        />
                        <Select
                            v-else-if="row.property === 'repo'"
                            v-model="row.value"
                            size="small"
                            placeholder="请选择仓库"
                            allow-clear
                        >
                            <SelectOption v-for="o in repoOptions" :key="o.value" :value="o.value">{{ o.label }}</SelectOption>
                        </Select>
                        <IterationSelect
                            v-else-if="row.property === 'iteration'"
                            v-model="row.value"
                            :project-id="iterationProjectId"
                            :project-ids="selectedProjectIds"
                            :selected-label="getIterationLabel(row.value)"
                            size="small"
                            placeholder="请选择迭代"
                            allow-clear
                            @options-change="handleIterationOptionsChange"
                        />
                        <Select
                            v-else-if="row.property === 'version'"
                            v-model="row.value"
                            size="small"
                            placeholder="请选择版本"
                            allow-clear
                        >
                            <SelectOption v-for="o in versionOptions" :key="o.value" :value="o.value">{{ o.label }}</SelectOption>
                        </Select>
                        <Select
                            v-else-if="row.property === 'parentId'"
                            v-model="row.value"
                            size="small"
                            placeholder="请选择父工作项"
                            allow-clear
                            show-search
                            :filter-option="(input: string, option: any) => (option?.label || '').toLowerCase().includes(input.toLowerCase())"
                        >
                            <SelectOption v-for="o in storyOptions" :key="o.value" :value="o.value" :label="o.label">{{ o.label }}</SelectOption>
                        </Select>
                        <Input v-else v-model="row.value" size="small" placeholder="请输入" />
                    </div>
                    <div v-else class="value-placeholder">将清空该字段</div>

                    <button type="button" class="remove-row-btn" @click="removeRow(row.id)">
                        <CircleMinus :size="18" />
                    </button>
                </div>
            </div>

            <button
                v-if="changeRows.length < PROPERTY_OPTIONS.length"
                type="button"
                class="add-row-btn"
                @click="addRow"
            >
                <Plus :size="14" />
                <span>修改更多属性</span>
            </button>
        </div>

        <template #footer>
            <div class="flex justify-end gap-2">
                <Button @click="handleCancel">取消</Button>
                <Button type="primary" :loading="submitting" @click="handleSubmit">确认修改</Button>
            </div>
        </template>
    </Dialog>
</template>

<style scoped>
.batch-editor {
    max-height: 500px;
    overflow-y: auto;
}
.selected-summary {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.project-group-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: #f5f5f5;
    border-radius: 4px;
    font-size: 13px;
}
.group-name {
    font-weight: 500;
    color: #333;
}
.group-detail {
    color: #888;
    font-size: 12px;
}
.empty-hint {
    text-align: center;
    color: #999;
    font-size: 13px;
    padding: 8px 0;
}
.change-rows {
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.change-row {
    display: grid;
    grid-template-columns: 150px 110px 1fr 32px;
    gap: 8px;
    align-items: center;
    font-size: 13px;
}
.change-row :deep(.vort-select-selector) {
    font-size: 13px !important;
    min-height: 32px !important;
}
.value-editor {
    min-width: 0;
    min-height: 32px;
    display: flex;
    align-items: stretch;
    border: 1px solid var(--vort-border, #d9d9d9);
    border-radius: var(--vort-border-radius-sm, 4px);
    overflow: hidden;
    transition: border-color 0.2s;
}
.value-editor:hover {
    border-color: var(--vort-primary);
}
.value-editor > :deep(*) {
    width: 100%;
    flex: 1;
    min-width: 0;
}

.value-editor :deep(.vort-select) {
    width: 100%;
    height: 100%;
}
.value-editor :deep(.vort-select-selector) {
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    height: 100% !important;
}
.value-editor :deep(.vort-select-focused .vort-select-selector),
.value-editor :deep(.vort-select:hover .vort-select-selector) {
    border: none !important;
    box-shadow: none !important;
}

.value-editor :deep(.vort-input),
.value-editor :deep(.vort-input-number),
.value-editor :deep(.vort-input-affix-wrapper) {
    width: 100%;
    height: 100%;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}
.value-editor :deep(.vort-input:focus),
.value-editor :deep(.vort-input-focused),
.value-editor :deep(.vort-input-number:focus),
.value-editor :deep(.vort-input-affix-wrapper-focused) {
    box-shadow: none !important;
}

.value-editor :deep(.vort-datepicker-selector),
.value-editor :deep(.vort-rangepicker-selector) {
    width: 100% !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}
/* Range picker: fixed 32px row height + flex centering so the value stays vertically centered;
   let start/end inputs size to content to avoid the 80px truncation under the "small" size. */
.value-editor :deep(.vort-rangepicker-selector) {
    display: flex !important;
    align-items: center !important;
    height: 32px !important;
    min-height: 32px !important;
    box-sizing: border-box !important;
    --_input-width: auto;
}
.value-editor :deep(.vort-rangepicker-input) {
    display: inline-flex !important;
    align-items: center !important;
    width: auto;
    min-width: 0;
}
/* Single date picker fills the container height */
.value-editor :deep(.vort-datepicker-selector) {
    height: 100% !important;
}
.value-editor :deep(.vort-datepicker-focused),
.value-editor :deep(.vort-rangepicker-focused) {
    border: none !important;
    box-shadow: none !important;
}

.value-editor :deep(.vort-input-number) {
    width: 100%;
    height: 100%;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}
.value-editor :deep(.vort-input-number:hover),
.value-editor :deep(.vort-input-number-focused) {
    border: none !important;
    box-shadow: none !important;
}

.value-editor :deep(.vort-popover-select-trigger) {
    width: 100%;
    height: 100%;
    border: none !important;
    box-shadow: none !important;
    background: transparent;
}
.value-editor :deep(.priority-cell-trigger) {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    padding: 0 8px;
    cursor: pointer;
}
.value-editor :deep(.priority-pill) {
    border-color: transparent !important;
}
.value-editor :deep(.status-cell-trigger) {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    padding: 0 8px;
    cursor: pointer;
}
.value-editor :deep(.member-picker-default-trigger),
.value-editor :deep(.tag-picker-default-trigger) {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    padding: 0 8px;
    background: transparent;
    border: none;
    cursor: pointer;
}
.value-placeholder {
    font-size: 13px;
    color: var(--vort-text-tertiary, rgba(0, 0, 0, 0.45));
    padding: 0 11px;
    min-height: 32px;
    display: flex;
    align-items: center;
    border: 1px solid var(--vort-border, #d9d9d9);
    border-radius: var(--vort-border-radius-sm, 4px);
}
.remove-row-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: none;
    background: transparent;
    color: var(--vort-error, #ff4d4f);
    cursor: pointer;
    opacity: 0.6;
    transition: opacity 0.15s;
    flex-shrink: 0;
}
.remove-row-btn:hover {
    opacity: 1;
}
.add-row-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 8px 0;
    border: none;
    background: transparent;
    color: var(--vort-primary);
    cursor: pointer;
    font-size: 13px;
    transition: opacity 0.2s;
}
.add-row-btn:hover {
    opacity: 0.8;
}
</style>
