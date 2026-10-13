<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { DownOutlined } from "@openvort/vort-ui";
import { Bookmark, SquareCheck, Bug, Activity, CheckCircle2, AlertTriangle, Pause } from "lucide-vue-next";
import PopoverSelect from "@/components/vort-biz/popover-select/PopoverSelect.vue";
import StatusIcon from "./StatusIcon.vue";
import type { WorkItemType, StatusOption } from "./WorkItemTable.types";

export interface StatusFilterGroup {
    type: WorkItemType;
    label?: string;
    options: StatusOption[];
}

// 与 useWorkItemCommon 保持一致的虚拟值，避免循环引用从这里独立声明
const PENDING_VALUE = "__pending";
const PENDING_LABEL = "在手工作项";
const COMPLETED_TODAY_VALUE = "__completed_today";
const COMPLETED_TODAY_LABEL = "当日已完成";
const OVERDUE_VALUE = "__overdue";
const OVERDUE_LABEL = "已逾期";
const STALE_VALUE = "__stale";
const STALE_LABEL = "停滞";
// legacy 合并值：旧视图可能残留，展示时等价于 逾期+停滞 同时选中
const OVERDUE_STALE_VALUE = "__overdue_stale";
const VIRTUAL_VALUES = new Set<string>([
    PENDING_VALUE, COMPLETED_TODAY_VALUE, OVERDUE_VALUE, STALE_VALUE, OVERDUE_STALE_VALUE,
]);

interface Props {
    modelValue: string[];
    /** Single-column mode: pass when no grouping is needed */
    options?: StatusOption[];
    /** Grouped (multi-column) mode: pass to render columns side by side */
    groups?: StatusFilterGroup[];
    placeholder?: string;
    triggerMinWidth?: number;
    /** 在弹窗顶部展示「在手工作项」快捷选项（互斥具体状态） */
    showPendingShortcut?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    options: () => [],
    groups: () => [],
    placeholder: "状态",
    triggerMinWidth: 130,
    showPendingShortcut: false,
});

const emit = defineEmits<{
    "update:modelValue": [value: string[]];
}>();

const dropdownOpen = ref(false);
const searchKeyword = ref("");

// "Cleared by user" tracks the difference between
//   default empty (= all selected) vs the user actively unchecking everything.
const clearedByUser = ref(false);

watch(
    () => props.modelValue,
    (val) => {
        if (val.length > 0) clearedByUser.value = false;
    },
);

const isGrouped = computed(() => props.groups.length > 0);

// 是否处于「在手工作项」模式
const isPendingMode = computed(() => props.modelValue.includes(PENDING_VALUE));

// 是否处于「当日已完成」模式
const isCompletedTodayMode = computed(() => props.modelValue.includes(COMPLETED_TODAY_VALUE));

// legacy 合并值等价于「已逾期」「停滞」同时选中
const hasLegacyOverdueStale = computed(() => props.modelValue.includes(OVERDUE_STALE_VALUE));

// 是否处于「已逾期」模式
const isOverdueMode = computed(() => props.modelValue.includes(OVERDUE_VALUE) || hasLegacyOverdueStale.value);

// 是否处于「停滞」模式
const isStaleMode = computed(() => props.modelValue.includes(STALE_VALUE) || hasLegacyOverdueStale.value);

// 是否处于任意虚拟模式
const isVirtualMode = computed(() =>
    isPendingMode.value || isCompletedTodayMode.value || isOverdueMode.value || isStaleMode.value
);

// 当前具体状态选中值（剔除虚拟值后的真实状态值）
const concreteValues = computed(() => props.modelValue.filter((v) => !VIRTUAL_VALUES.has(v)));

const allOptions = computed<StatusOption[]>(() => {
    if (isGrouped.value) {
        const seen = new Map<string, StatusOption>();
        for (const group of props.groups) {
            for (const opt of group.options) {
                if (!seen.has(opt.value)) seen.set(opt.value, opt);
            }
        }
        return Array.from(seen.values());
    }
    return props.options;
});

const isAllChecked = computed(() => {
    if (clearedByUser.value) return false;
    if (isVirtualMode.value) return false;
    if (!allOptions.value.length) return false;
    return (
        concreteValues.value.length === 0 ||
        allOptions.value.every((o) => concreteValues.value.includes(o.value))
    );
});

const isIndeterminate = computed(() => {
    if (clearedByUser.value) return false;
    if (isVirtualMode.value) return false;
    if (concreteValues.value.length === 0) return false;
    return concreteValues.value.length < allOptions.value.length;
});

const isItemChecked = (value: string) => {
    if (clearedByUser.value) return false;
    if (isVirtualMode.value) return false;
    return concreteValues.value.length === 0 || concreteValues.value.includes(value);
};

// 顶部触发器展示的「主标签」：优先 pending，再 已逾期，再 停滞，再 completed_today，最后第一个具体状态
const triggerLabel = computed(() => {
    if (isPendingMode.value) return PENDING_LABEL;
    if (isOverdueMode.value) return OVERDUE_LABEL;
    if (isStaleMode.value) return STALE_LABEL;
    if (isCompletedTodayMode.value) return COMPLETED_TODAY_LABEL;
    if (!concreteValues.value.length) return props.placeholder;
    const first = concreteValues.value[0];
    const opt = allOptions.value.find((o) => o.value === first);
    return opt?.label || first || props.placeholder;
});

// 多余项数量徽标：虚拟值合并计数
const triggerExtraCount = computed(() => {
    if (isVirtualMode.value) {
        const virtualCount =
            (isPendingMode.value ? 1 : 0) +
            (isCompletedTodayMode.value ? 1 : 0) +
            (isOverdueMode.value ? 1 : 0) +
            (isStaleMode.value ? 1 : 0);
        return Math.max(0, virtualCount - 1);
    }
    return Math.max(0, concreteValues.value.length - 1);
});

const triggerStyle = computed(() => ({
    minWidth: `${props.triggerMinWidth}px`,
}));

const matchesKeyword = (label: string) => {
    const kw = searchKeyword.value.trim().toLowerCase();
    if (!kw) return true;
    return label.toLowerCase().includes(kw);
};

const filteredOptions = computed<StatusOption[]>(() =>
    props.options.filter((opt) => matchesKeyword(opt.label)),
);

const filteredGroups = computed<StatusFilterGroup[]>(() =>
    props.groups.map((group) => ({
        ...group,
        options: group.options.filter((opt) => matchesKeyword(opt.label)),
    })),
);

const dropdownWidth = computed(() => {
    if (!isGrouped.value) return 240;
    const colCount = props.groups.length;
    return Math.max(360, colCount * 180 + 24);
});

const gridColumnCount = computed(() => Math.max(1, props.groups.length));

const toggleItem = (value: string) => {
    // 选中具体状态时，自动退出虚拟模式
    if (isVirtualMode.value) {
        clearedByUser.value = false;
        emit("update:modelValue", [value]);
        return;
    }

    if (clearedByUser.value) {
        clearedByUser.value = false;
        emit("update:modelValue", [value]);
        return;
    }

    if (!concreteValues.value.length) {
        const next = allOptions.value.map((o) => o.value).filter((v) => v !== value);
        emit("update:modelValue", next);
        return;
    }

    const current = [...concreteValues.value];
    const idx = current.indexOf(value);
    if (idx >= 0) {
        current.splice(idx, 1);
        if (current.length === 0) {
            clearedByUser.value = true;
            emit("update:modelValue", []);
            return;
        }
    } else {
        current.push(value);
        if (allOptions.value.every((o) => current.includes(o.value))) {
            emit("update:modelValue", []);
            return;
        }
    }
    emit("update:modelValue", current);
};

const toggleAll = () => {
    // 「全部」点击时退出所有虚拟模式
    if (isAllChecked.value) {
        clearedByUser.value = true;
    } else {
        clearedByUser.value = false;
    }
    emit("update:modelValue", []);
};

const togglePending = () => toggleVirtualValue(PENDING_VALUE);
const toggleCompletedToday = () => toggleVirtualValue(COMPLETED_TODAY_VALUE);

// 把 modelValue 中可能残留的 legacy 合并值展开为两个新值，便于独立开关
const expandLegacyValues = (values: string[]): string[] => {
    if (!values.includes(OVERDUE_STALE_VALUE)) return [...values];
    const next = values.filter((v) => v !== OVERDUE_STALE_VALUE);
    if (!next.includes(OVERDUE_VALUE)) next.push(OVERDUE_VALUE);
    if (!next.includes(STALE_VALUE)) next.push(STALE_VALUE);
    return next;
};

const toggleVirtualValue = (value: string) => {
    clearedByUser.value = false;
    const cur = expandLegacyValues(props.modelValue);
    if (cur.includes(value)) {
        emit("update:modelValue", cur.filter((v) => v !== value));
    } else {
        // 选中虚拟状态时与具体状态互斥，但各虚拟状态之间可并存
        const others = cur.filter((v) => VIRTUAL_VALUES.has(v) && v !== value);
        emit("update:modelValue", [...others, value]);
    }
};

const toggleOverdue = () => toggleVirtualValue(OVERDUE_VALUE);
const toggleStale = () => toggleVirtualValue(STALE_VALUE);

const TYPE_ICON_CLASS: Record<WorkItemType, string> = {
    需求: "work-type-icon-demand",
    任务: "work-type-icon-task",
    缺陷: "work-type-icon-bug",
};

const getTypeIconClass = (type: WorkItemType) => TYPE_ICON_CLASS[type];

const getTypeIcon = (type: WorkItemType) => {
    if (type === "需求") return Bookmark;
    if (type === "任务") return SquareCheck;
    return Bug;
};

defineExpose({
    reset: () => {
        clearedByUser.value = false;
        searchKeyword.value = "";
    },
});
</script>

<template>
    <PopoverSelect
        v-model:open="dropdownOpen"
        v-model:keyword="searchKeyword"
        :show-search="true"
        search-placeholder="搜索..."
        :dropdown-width="dropdownWidth"
        :dropdown-max-height="320"
        :bordered="false"
    >
        <template #trigger="{ open }">
            <div
                class="filter-select-trigger"
                :class="{ active: open }"
                :style="triggerStyle"
                tabindex="0"
                @click.stop="dropdownOpen = !dropdownOpen"
            >
                <div class="flex items-center w-full gap-1.5 min-w-0">
                    <span
                        class="filter-select-value text-sm truncate"
                        :class="
                            props.modelValue.length
                                ? 'text-[var(--vort-text,rgba(0,0,0,0.88))]'
                                : 'text-[var(--vort-text-quaternary,rgba(0,0,0,0.25))]'
                        "
                    >
                        {{ triggerLabel }}
                    </span>
                    <span v-if="triggerExtraCount > 0" class="status-extra-badge">
                        (+{{ triggerExtraCount }})
                    </span>
                    <span
                        class="vort-select-arrow ml-auto"
                        :class="{ 'vort-select-arrow-open': open }"
                    >
                        <DownOutlined />
                    </span>
                </div>
            </div>
        </template>

        <div class="p-2 pt-1">
            <div
                class="status-filter-row"
                :class="{ 'is-active': isAllChecked }"
                @click.stop="toggleAll()"
            >
                <div class="flex items-center gap-3">
                    <vort-checkbox
                        :checked="isAllChecked"
                        :indeterminate="isIndeterminate"
                        @click.stop
                        @update:checked="toggleAll()"
                    />
                    <span class="text-sm text-gray-700 leading-5">全部</span>
                </div>
            </div>

            <div
                v-if="props.showPendingShortcut"
                class="status-filter-row pending-row"
                :class="{ 'is-active': isPendingMode }"
                @click.stop="togglePending()"
            >
                <div class="flex items-center gap-3">
                    <vort-checkbox
                        :checked="isPendingMode"
                        @click.stop
                        @update:checked="togglePending()"
                    />
                    <span class="pending-icon">
                        <Activity :size="13" />
                    </span>
                    <span class="text-sm text-gray-700 leading-5">在手工作项</span>
                    <span class="pending-hint">仅显示未完成</span>
                </div>
            </div>

            <div
                v-if="props.showPendingShortcut"
                class="status-filter-row pending-row"
                :class="{ 'is-active': isCompletedTodayMode }"
                @click.stop="toggleCompletedToday()"
            >
                <div class="flex items-center gap-3">
                    <vort-checkbox
                        :checked="isCompletedTodayMode"
                        @click.stop
                        @update:checked="toggleCompletedToday()"
                    />
                    <span class="pending-icon completed-today-icon">
                        <CheckCircle2 :size="13" />
                    </span>
                    <span class="text-sm text-gray-700 leading-5">当日已完成</span>
                    <span class="pending-hint">仅显示今日已完成</span>
                </div>
            </div>

            <div
                v-if="props.showPendingShortcut"
                class="status-filter-row pending-row"
                :class="{ 'is-active': isOverdueMode }"
                @click.stop="toggleOverdue()"
            >
                <div class="flex items-center gap-3">
                    <vort-checkbox
                        :checked="isOverdueMode"
                        @click.stop
                        @update:checked="toggleOverdue()"
                    />
                    <span class="pending-icon overdue-icon">
                        <AlertTriangle :size="13" />
                    </span>
                    <span class="text-sm text-gray-700 leading-5">已逾期</span>
                    <span class="pending-hint">截止日期已过</span>
                </div>
            </div>

            <div
                v-if="props.showPendingShortcut"
                class="status-filter-row pending-row"
                :class="{ 'is-active': isStaleMode }"
                @click.stop="toggleStale()"
            >
                <div class="flex items-center gap-3">
                    <vort-checkbox
                        :checked="isStaleMode"
                        @click.stop
                        @update:checked="toggleStale()"
                    />
                    <span class="pending-icon stale-icon">
                        <Pause :size="13" />
                    </span>
                    <span class="text-sm text-gray-700 leading-5">停滞</span>
                    <span class="pending-hint">7天无活动·不含逾期</span>
                </div>
            </div>

            <template v-if="!isGrouped">
                <div
                    v-for="opt in filteredOptions"
                    :key="opt.value"
                    class="status-filter-row"
                    :class="{ 'is-active': isItemChecked(opt.value) }"
                    @click.stop="toggleItem(opt.value)"
                >
                    <div class="flex items-center gap-3">
                        <vort-checkbox
                            :checked="isItemChecked(opt.value)"
                            @click.stop
                            @update:checked="toggleItem(opt.value)"
                        />
                        <span :class="opt.iconClass" class="flex items-center">
                            <StatusIcon :name="opt.icon" :size="14" :color="opt.iconColor" />
                        </span>
                        <span class="text-sm text-gray-700 leading-5">{{ opt.label }}</span>
                    </div>
                </div>
            </template>

            <div v-else class="status-filter-grid mt-1">
                <div
                    v-for="group in filteredGroups"
                    :key="group.type"
                    class="status-filter-col"
                >
                    <div class="status-filter-col-header">
                        <span class="work-type-icon" :class="getTypeIconClass(group.type)">
                            <component :is="getTypeIcon(group.type)" :size="11" />
                        </span>
                        <span class="status-filter-col-title">{{ group.label || group.type }}</span>
                    </div>
                    <div
                        v-for="opt in group.options"
                        :key="`${group.type}-${opt.value}`"
                        class="status-filter-row"
                        :class="{ 'is-active': isItemChecked(opt.value) }"
                        @click.stop="toggleItem(opt.value)"
                    >
                        <div class="flex items-center gap-2">
                            <vort-checkbox
                                :checked="isItemChecked(opt.value)"
                                @click.stop
                                @update:checked="toggleItem(opt.value)"
                            />
                            <span :class="opt.iconClass" class="flex items-center shrink-0">
                                <StatusIcon :name="opt.icon" :size="14" :color="opt.iconColor" />
                            </span>
                            <span class="text-sm text-gray-700 leading-5 truncate">
                                {{ opt.label }}
                            </span>
                        </div>
                    </div>
                    <div v-if="group.options.length === 0" class="status-filter-empty">
                        无匹配
                    </div>
                </div>
            </div>
        </div>
    </PopoverSelect>
</template>

<style scoped>
.filter-select-trigger {
    display: flex;
    align-items: center;
    padding: 4px 11px;
    border-radius: 6px;
    border: 1px solid #d9d9d9;
    background: #fff;
    min-height: 32px;
    transition: all 0.3s cubic-bezier(0.645, 0.045, 0.355, 1);
    outline: none;
    cursor: pointer;
}

.filter-select-trigger:hover,
.filter-select-trigger.active {
    border-color: var(--vort-primary, #1456f0);
    background: #fff;
}

.filter-select-trigger:focus-within,
.filter-select-trigger:focus {
    border-color: var(--vort-primary, #1456f0);
    box-shadow: 0 0 0 2px var(--vort-primary-shadow, rgba(20, 86, 240, 0.1));
}

.filter-select-value {
    min-width: 0;
}

.vort-select-arrow {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    color: var(--vort-text-quaternary, rgba(0, 0, 0, 0.25));
    transition: transform var(--vort-transition-colors, 0.2s);
}

.vort-select-arrow-open {
    transform: rotate(180deg);
}

.status-filter-row {
    min-height: 32px;
    padding: 2px 8px;
    border-radius: 6px;
    cursor: pointer;
    transition: background-color 0.15s ease;
}

.status-filter-row:hover {
    background: rgba(0, 0, 0, 0.04);
}

.status-filter-row.is-active {
    background: #f1f5f9;
}

.status-filter-row.pending-row {
    margin-bottom: 4px;
}

.status-filter-row.pending-row.is-active {
    background: var(--vort-primary-bg, rgba(20, 86, 240, 0.08));
}

.pending-icon {
    display: inline-flex;
    align-items: center;
    color: var(--vort-primary, #1456f0);
}

.pending-icon.completed-today-icon {
    color: #10b981;
}

.pending-icon.overdue-icon {
    color: #ef4444;
}

.pending-icon.stale-icon {
    color: #6b7280;
}

.pending-hint {
    margin-left: auto;
    font-size: 11px;
    color: var(--vort-text-quaternary, rgba(0, 0, 0, 0.45));
}

.status-extra-badge {
    flex-shrink: 0;
    margin-left: 2px;
    font-size: 13px;
    color: var(--vort-text, rgba(0, 0, 0, 0.88));
}

.status-filter-grid {
    display: grid;
    grid-template-columns: repeat(v-bind(gridColumnCount), minmax(0, 1fr));
    column-gap: 8px;
    align-items: stretch;
}

.status-filter-col {
    display: flex;
    flex-direction: column;
    min-width: 0;
    padding: 0 4px;
    border-left: 1px solid var(--vort-border-secondary, #f0f0f0);
}

.status-filter-col:first-child {
    border-left: none;
    padding-left: 0;
}

.status-filter-col-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    color: var(--vort-text-secondary, rgba(0, 0, 0, 0.65));
    font-size: 12px;
    font-weight: 500;
}

.status-filter-col-title {
    font-weight: 500;
}

.status-filter-empty {
    padding: 6px 8px;
    color: var(--vort-text-quaternary, rgba(0, 0, 0, 0.35));
    font-size: 12px;
}

.work-type-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 3px;
    font-size: 12px;
    color: #fff;
    flex-shrink: 0;
}

.work-type-icon-demand {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
}

.work-type-icon-task {
    background: linear-gradient(135deg, #0ea5e9 0%, #06b6d4 100%);
}

.work-type-icon-bug {
    background: linear-gradient(135deg, #ef4444 0%, #f97316 100%);
}
</style>
