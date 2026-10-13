<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { DownOutlined, Dropdown, DropdownMenuItem } from "@openvort/vort-ui";
import PopoverSelect from "@/components/vort-biz/popover-select/PopoverSelect.vue";
import WorkItemMemberPicker from "./WorkItemMemberPicker.vue";
import WorkItemStatusFilter, { type StatusFilterGroup } from "./WorkItemStatusFilter.vue";
import type { WorkItemType, StatusOption, MemberOption } from "./WorkItemTable.types";

export interface WorkItemFiltersProps {
    keyword?: string;
    owner?: string[];
    type?: WorkItemType[];
    status?: string[];
    pageTitle?: string;
    createButtonText?: string;
    totalCount?: number;
    memberOptions?: MemberOption[];
    ownerGroups?: Array<{ label: string; members: string[] }>;
    statusOptions?: StatusOption[];
    /** 工作墙等跨类型场景：传入分组数据，状态弹窗按需求/任务/缺陷分列展示 */
    statusGroups?: StatusFilterGroup[];
    /** 在状态弹窗顶部展示「在手工作项」快捷选项（一般工作墙模式启用） */
    showStatusPendingShortcut?: boolean;
    typeOptions?: WorkItemType[];
    showTypeFilter?: boolean;
    /** 标题旁以 tab 形式展示类型筛选（工作墙模式），与 showTypeFilter 互斥 */
    showTypeTabs?: boolean;
    /** 当传入时，新建按钮变为 dropdown，三选一触发 create 事件并附带 type 参数（用于工作墙） */
    createTypeOptions?: WorkItemType[];
    getAvatarBg?: (name: string) => string;
    getAvatarLabel?: (name: string) => string;
    getAvatarUrl?: (name: string) => string;
}

const props = withDefaults(defineProps<WorkItemFiltersProps>(), {
    keyword: "",
    owner: () => [],
    type: () => [],
    status: () => [],
    pageTitle: "缺陷",
    createButtonText: "+ 新建缺陷",
    totalCount: 0,
    memberOptions: () => [],
    ownerGroups: () => [],
    statusOptions: () => [],
    statusGroups: () => [],
    showStatusPendingShortcut: false,
    typeOptions: () => ["缺陷", "需求", "任务"],
    showTypeFilter: true,
    showTypeTabs: false,
    createTypeOptions: () => [],
    getAvatarBg: undefined,
    getAvatarLabel: undefined,
    getAvatarUrl: undefined,
});

const emit = defineEmits<{
    "update:keyword": [value: string];
    "update:owner": [value: string[]];
    "update:type": [value: WorkItemType[]];
    "update:status": [value: string[]];
    search: [];
    reset: [];
    create: [type?: WorkItemType];
}>();

const keyword = computed({
    get: () => props.keyword,
    set: (val) => emit("update:keyword", val)
});

const typeDisplayLabel = computed(() => {
    if (!props.type.length) return "类型";
    return props.type[0] || "类型";
});

const typeExtraCount = computed(() => Math.max(0, props.type.length - 1));

const ownerDropdownOpen = ref(false);
const ownerKeyword = ref("");
const typeDropdownOpen = ref(false);
const typeKeyword = ref("");

const filteredTypeOptions = computed(() => {
    const kw = typeKeyword.value.trim();
    if (!kw) return props.typeOptions;
    return props.typeOptions.filter(t => t.includes(kw));
});

const ownerDisplayLabel = computed(() => {
    if (!props.owner.length) return "";
    const id = props.owner[0];
    const member = props.memberOptions.find(m => m.id === id);
    return member?.name || id || "";
});

const ownerExtraCount = computed(() => Math.max(0, props.owner.length - 1));

// "全不选" 内部状态：区分 "默认全选(props=[])" 与 "用户主动取消全部(props=[])"
const typeClearedByUser = ref(false);

watch(() => props.type, (val) => {
    if (val.length > 0) typeClearedByUser.value = false;
});

const statusFilterRef = ref<{ reset: () => void } | null>(null);

// === Type 视觉状态 ===
const isAllTypeChecked = computed(() => {
    if (typeClearedByUser.value) return false;
    if (!props.typeOptions.length) return false;
    return props.type.length === 0
        || props.typeOptions.every(t => props.type.includes(t));
});

const isTypeIndeterminate = computed(() => {
    if (typeClearedByUser.value) return false;
    if (props.type.length === 0) return false;
    return props.type.length < props.typeOptions.length;
});

const isTypeItemChecked = (value: WorkItemType) => {
    if (typeClearedByUser.value) return false;
    return props.type.length === 0 || props.type.includes(value);
};

const toggleType = (value: WorkItemType) => {
    if (typeClearedByUser.value) {
        typeClearedByUser.value = false;
        emit("update:type", [value]);
        return;
    }

    if (!props.type.length) {
        // 当前视觉全选：取消该项 → 仅勾选其他所有项
        const next = props.typeOptions.filter(t => t !== value);
        emit("update:type", next);
        return;
    }

    const current = [...props.type];
    const idx = current.indexOf(value);
    if (idx >= 0) {
        current.splice(idx, 1);
        if (current.length === 0) {
            typeClearedByUser.value = true;
            emit("update:type", []);
            return;
        }
    } else {
        current.push(value);
        if (props.typeOptions.every(t => current.includes(t))) {
            // 加上后已包含所有项 → 归一化为空数组（全选）
            emit("update:type", []);
            return;
        }
    }
    emit("update:type", current);
};

const toggleAllType = () => {
    if (isAllTypeChecked.value) {
        // 全选 → 全不选
        typeClearedByUser.value = true;
        emit("update:type", []);
    } else {
        // 半选或全不选 → 全选
        typeClearedByUser.value = false;
        emit("update:type", []);
    }
};

// === Type 标题 Tab（工作墙）===
// 与下拉筛选互斥：tab 模式下 type 取值语义为单选 —— [] 代表"所有"，[T] 代表单类型。
const typeTabOptions = computed<{ value: WorkItemType | null; label: string }[]>(() => [
    { value: null, label: "所有" },
    { value: "需求", label: "需求" },
    { value: "任务", label: "任务" },
    { value: "缺陷", label: "缺陷" },
]);

const activeTypeTab = computed<WorkItemType | null>(() => {
    if (typeClearedByUser.value) return null;
    if (props.type.length === 1) {
        const v = props.type[0]!;
        if (v === "需求" || v === "任务" || v === "缺陷") return v;
    }
    return null;
});

const selectTypeTab = (value: WorkItemType | null) => {
    typeClearedByUser.value = false;
    emit("update:type", value ? [value] : []);
};

const onSearch = () => emit("search");
const onReset = () => {
    statusFilterRef.value?.reset();
    typeClearedByUser.value = false;
    emit("reset");
};

const onStatusUpdate = (value: string[]) => emit("update:status", value);
const onCreate = () => emit("create");
const onCreateWithType = (t: WorkItemType) => {
    createDropdownOpen.value = false;
    emit("create", t);
};

const createDropdownOpen = ref(false);
const showCreateDropdown = computed(() => (props.createTypeOptions?.length ?? 0) > 0);
</script>

<template>
    <div class="bg-white rounded-xl p-4">
        <div v-if="!$slots['before-count']" class="title-row flex items-center gap-6 mb-3">
            <h3 class="title-text m-0">{{ props.pageTitle }}</h3>
            <div v-if="props.showTypeTabs" class="type-tabs">
                <button
                    v-for="opt in typeTabOptions"
                    :key="opt.label"
                    type="button"
                    class="type-tab"
                    :class="{ active: activeTypeTab === opt.value }"
                    @click="selectTypeTab(opt.value)"
                >
                    {{ opt.label }}
                </button>
            </div>
        </div>
        <div class="flex flex-wrap items-center gap-3 text-sm">
            <slot name="before-count" />
            <div class="text-gray-600"><span class="text-gray-900 font-medium">共 {{ totalCount }} 项</span></div>
            <div class="w-[180px] shrink-0">
                <VortInput v-model="keyword" placeholder="输入关键词" @keyup.enter="onSearch" />
            </div>

            <WorkItemMemberPicker
                mode="collaborators"
                :collaborators="props.owner"
                :groups="props.ownerGroups"
                :open="ownerDropdownOpen"
                v-model:keyword="ownerKeyword"
                :show-all-option="true"
                :show-unassigned="true"
                unassigned-value="未指派"
                :dropdown-max-height="460"
                :get-avatar-bg="props.getAvatarBg"
                :get-avatar-label="props.getAvatarLabel"
                :get-avatar-url="props.getAvatarUrl"
                @update:open="(open) => ownerDropdownOpen = open"
                @update:collaborators="(val) => emit('update:owner', val)"
            >
                <template #trigger="{ open }">
                    <div
                        class="filter-select-trigger min-w-[130px]"
                        :class="{ active: open }"
                        tabindex="0"
                        @click.stop="ownerDropdownOpen = !ownerDropdownOpen"
                    >
                        <div class="flex items-center w-full gap-1.5 min-w-0">
                            <span class="filter-select-value text-sm truncate" :class="props.owner.length ? 'text-[var(--vort-text,rgba(0,0,0,0.88))]' : 'text-[var(--vort-text-quaternary,rgba(0,0,0,0.25))]'">
                                {{ ownerDisplayLabel || "负责人" }}
                            </span>
                            <span v-if="ownerExtraCount > 0" class="status-extra-badge">(+{{ ownerExtraCount }})</span>
                            <span class="vort-select-arrow ml-auto" :class="{ 'vort-select-arrow-open': open }">
                                <DownOutlined />
                            </span>
                        </div>
                    </div>
                </template>
            </WorkItemMemberPicker>

            <!-- Type Filter -->
            <PopoverSelect
                v-if="props.showTypeFilter"
                v-model:open="typeDropdownOpen"
                v-model:keyword="typeKeyword"
                :show-search="true"
                search-placeholder="搜索..."
                :dropdown-width="200"
                :dropdown-max-height="260"
                :bordered="false"
            >
                <template #trigger="{ open }">
                    <div
                        class="filter-select-trigger min-w-[110px]"
                        :class="{ active: open }"
                        tabindex="0"
                        @click.stop="typeDropdownOpen = !typeDropdownOpen"
                    >
                        <div class="flex items-center w-full gap-1.5 min-w-0">
                            <span class="filter-select-value text-sm truncate" :class="props.type.length ? 'text-[var(--vort-text,rgba(0,0,0,0.88))]' : 'text-[var(--vort-text-quaternary,rgba(0,0,0,0.25))]'">
                                {{ typeDisplayLabel }}
                            </span>
                            <span v-if="typeExtraCount > 0" class="status-extra-badge">(+{{ typeExtraCount }})</span>
                            <span class="vort-select-arrow ml-auto" :class="{ 'vort-select-arrow-open': open }">
                                <DownOutlined />
                            </span>
                        </div>
                    </div>
                </template>

                <div class="p-2 pt-1">
                    <div
                        class="status-filter-row"
                        :class="{ 'is-active': isAllTypeChecked }"
                        @click.stop="toggleAllType()"
                    >
                        <div class="flex items-center gap-3">
                            <vort-checkbox
                                :checked="isAllTypeChecked"
                                :indeterminate="isTypeIndeterminate"
                                @click.stop
                                @update:checked="toggleAllType()"
                            />
                            <span class="text-sm text-gray-700 leading-5">全部</span>
                        </div>
                    </div>
                    <div
                        v-for="group in filteredTypeOptions"
                        :key="group"
                        class="status-filter-row"
                        :class="{ 'is-active': isTypeItemChecked(group) }"
                        @click.stop="toggleType(group)"
                    >
                        <div class="flex items-center gap-3">
                            <vort-checkbox
                                :checked="isTypeItemChecked(group)"
                                @click.stop
                                @update:checked="toggleType(group)"
                            />
                            <span class="text-sm text-gray-700 leading-5">{{ group }}</span>
                        </div>
                    </div>
                </div>
            </PopoverSelect>

            <WorkItemStatusFilter
                ref="statusFilterRef"
                :model-value="props.status"
                :options="props.statusOptions"
                :groups="props.statusGroups"
                :show-pending-shortcut="props.showStatusPendingShortcut"
                @update:model-value="onStatusUpdate"
            />

            <VortButton variant="primary" @click="onSearch">查询</VortButton>
            <VortButton @click="onReset">重置</VortButton>
            <slot name="after-filters" />
            <div class="ml-auto flex items-center gap-2">
                <Dropdown v-if="showCreateDropdown" v-model:open="createDropdownOpen" trigger="click" placement="bottomRight">
                    <VortButton variant="primary">
                        {{ props.createButtonText }}
                        <span class="create-dropdown-arrow ml-1"><DownOutlined /></span>
                    </VortButton>
                    <template #overlay>
                        <DropdownMenuItem
                            v-for="t in props.createTypeOptions"
                            :key="t"
                            @click="onCreateWithType(t)"
                        >
                            <span>{{ t }}</span>
                        </DropdownMenuItem>
                    </template>
                </Dropdown>
                <VortButton v-else variant="primary" @click="onCreate">{{ props.createButtonText }}</VortButton>
                <slot name="extra-actions" />
            </div>
        </div>
    </div>
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
    /* flex: 1; */
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

.ml-auto {
    margin-left: auto;
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

.status-extra-badge {
    flex-shrink: 0;
    margin-left: 2px;
    font-size: 13px;
    color: var(--vort-text, rgba(0, 0, 0, 0.88));
}

.create-dropdown-arrow {
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    line-height: 1;
}

.title-row {
    line-height: 1.4;
}

.title-text {
    font-size: 18px;
    font-weight: 600;
    color: var(--vort-text, rgba(0, 0, 0, 0.88));
    line-height: 1.4;
}

.type-tabs {
    display: inline-flex;
    align-items: center;
    gap: 24px;
}

.type-tab {
    position: relative;
    padding: 4px 0;
    border: none;
    background: transparent;
    font-size: 14px;
    color: var(--vort-text-secondary, #6b7280);
    cursor: pointer;
    transition: color 0.2s;
    line-height: 1.4;
}

.type-tab:hover {
    color: var(--vort-primary, #1456f0);
}

.type-tab.active {
    color: var(--vort-primary, #1456f0);
    font-weight: 500;
}

.type-tab.active::after {
    content: "";
    position: absolute;
    left: 50%;
    bottom: -4px;
    width: 24px;
    height: 2px;
    border-radius: 2px;
    background: var(--vort-primary, #1456f0);
    transform: translateX(-50%);
}
</style>
