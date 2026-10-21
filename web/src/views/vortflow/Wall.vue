<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ChevronDown } from "lucide-vue-next";
import WorkItemTable from "@/views/vortflow/WorkItemTable.vue";
import MemberWorkloadPanel from "@/views/vortflow/components/MemberWorkloadPanel.vue";
import IterationHealthBar from "@/views/vortflow/components/IterationHealthBar.vue";
import { useVortFlowStore } from "@/stores";
import {
    COMPLETED_TODAY_STATUS_VALUE,
    OVERDUE_STATUS_VALUE,
    PENDING_STATUS_VALUE,
    STALE_STATUS_VALUE,
} from "@/views/vortflow/work-item/useWorkItemCommon";
import { getAllVortflowIterations } from "@/api";
import type { WorkItemType } from "@/components/vort-biz/work-item/WorkItemTable.types";

type WallScope = "all" | "current";

interface IterationItem {
    id: string;
    name: string;
    status: string;
    start_date?: string | null;
    end_date?: string | null;
}

const ITER_ALL = "";
const ITER_ACTIVE = "__active__";
const ITER_UNPLANNED = "__unplanned__";
const VISIBLE_ITER_LIMIT = 3;

const store = useVortFlowStore();

// "全部项目" / "当前项目"，默认全部项目（跨项目）
const scope = ref<WallScope>("all");

const effectiveProjectId = computed(() => (scope.value === "current" ? store.selectedProjectId : ""));

// 传给工作项表格的项目过滤：
// - 当前项目：单项目 project-id（配合迭代下钻）
// - 全部项目：沿用顶部多选筛选范围 project-ids（空数组=真正全部）
const tableProjectId = computed(() => (scope.value === "current" ? store.selectedProjectId : ""));
const tableProjectIds = computed(() => (scope.value === "current" ? [] : store.selectedProjectIds));

const currentProjectName = computed(() => {
    const id = store.selectedProjectId;
    if (!id) return "";
    return store.projects.find((p: { id: string; name: string }) => p.id === id)?.name || "";
});

// ---- 迭代切换 ----

const iterations = ref<IterationItem[]>([]);
const selectedIterationId = ref<string>(store.getIterationId(effectiveProjectId.value));
const iterMoreOpen = ref(false);

const activeIteration = computed<IterationItem | null>(() =>
    iterations.value.find((i) => i.status === "active") || null
);

// 迭代选择器实际生效的 ID（解析 __active__）
const effectiveIterationId = computed<string>(() => {
    if (scope.value !== "current") return ""; // 全部项目模式下不区分迭代
    const v = selectedIterationId.value;
    if (v === ITER_ACTIVE) return activeIteration.value?.id || "";
    return v;
});

// 当前选中的具体迭代（用于显示名）
const selectedIteration = computed<IterationItem | null>(() => {
    const id = effectiveIterationId.value;
    if (!id || id === ITER_UNPLANNED) return null;
    return iterations.value.find((i) => i.id === id) || null;
});

// 是否要展示迭代健康度条：仅当选中"具体迭代"时
const showHealthBar = computed(() => {
    const id = effectiveIterationId.value;
    return Boolean(id) && id !== ITER_UNPLANNED;
});

// 哪些迭代显示为 tab，哪些放在"更多"下拉
const visibleIterations = computed<IterationItem[]>(() => {
    const list = iterations.value;
    if (list.length <= VISIBLE_ITER_LIMIT) return list;
    const head = list.slice(0, VISIBLE_ITER_LIMIT);
    // 如果当前选中的具体迭代不在前几个里，把它顶上来
    if (selectedIteration.value && !head.find((i) => i.id === selectedIteration.value!.id)) {
        return [...list.slice(0, VISIBLE_ITER_LIMIT - 1), selectedIteration.value];
    }
    return head;
});

const moreIterations = computed<IterationItem[]>(() => {
    const visibleSet = new Set(visibleIterations.value.map((i) => i.id));
    return iterations.value.filter((i) => !visibleSet.has(i.id));
});

async function loadIterations() {
    if (!effectiveProjectId.value) {
        iterations.value = [];
        return;
    }
    try {
        const res: any = await getAllVortflowIterations({
            project_id: effectiveProjectId.value,
            page_size: 200,
        });
        const items = (res?.items || []) as IterationItem[];
        items.sort((a, b) => {
            const da = a.start_date ? new Date(a.start_date).getTime() : 0;
            const db = b.start_date ? new Date(b.start_date).getTime() : 0;
            return db - da;
        });
        iterations.value = items;
    } catch {
        iterations.value = [];
    }
}

watch(effectiveProjectId, async () => {
    await loadIterations();
    selectedIterationId.value = store.getIterationId(effectiveProjectId.value);
});

function setIteration(id: string) {
    selectedIterationId.value = id;
    store.setIterationId(effectiveProjectId.value, id);
    iterMoreOpen.value = false;
}

const iterStatusLabel: Record<string, string> = {
    planning: "规划",
    active: "进行中",
    completed: "已完成",
};

// ---- 成员关注联动 ----

const focusedMemberId = ref<string>("");

// 用 participant 而非 owner：与卡片在手数量口径保持一致（包含协作者）。
// vf.participant 在 useWorkItemDataSource 里会被翻译成后端 participant_id 参数，
// 后端匹配口径：需求=assignee||pm||collab；任务=assignee||collab；
// 缺陷=assignee||developer||collab。「创建人/报告人」**不计入参与者**，
// 这样列表与成员卡片「在手 / 当日完成」数字才能对得上。
const tableViewFilters = computed(() => (
    focusedMemberId.value ? { participant: focusedMemberId.value } : {}
));

const memberPanelRef = ref<InstanceType<typeof MemberWorkloadPanel> | null>(null);
const workItemTableRef = ref<InstanceType<typeof WorkItemTable> | null>(null);

function handleSelectMember(memberId: string) {
    // 切换关注成员时，自动把状态筛选项默认为「在手工作项」+「当日已完成」
    // 让用户既能看到该成员的在手工作量，也能看到 ta 今天的产出
    workItemTableRef.value?.setStatusFilter?.(
        memberId ? [PENDING_STATUS_VALUE, COMPLETED_TODAY_STATUS_VALUE] : []
    );
    workItemTableRef.value?.setTypeFilter?.([]);
    focusedMemberId.value = memberId;
}

function handleSelectMemberType(memberId: string, chipType: WorkItemType) {
    workItemTableRef.value?.setStatusFilter?.(
        [PENDING_STATUS_VALUE, COMPLETED_TODAY_STATUS_VALUE]
    );
    workItemTableRef.value?.setTypeFilter?.([chipType]);
    focusedMemberId.value = memberId;
}

// 点击成员卡片上的「逾」「滞」徽章：状态筛选切到对应的单一风险虚拟状态，
// 与卡片上的数字同口径（逾期=截止日已过；停滞=7天无活动且未逾期，两者互斥）
function handleSelectMemberRisk(memberId: string, risk: "overdue" | "stale") {
    workItemTableRef.value?.setStatusFilter?.(
        [risk === "overdue" ? OVERDUE_STATUS_VALUE : STALE_STATUS_VALUE]
    );
    workItemTableRef.value?.setTypeFilter?.([]);
    focusedMemberId.value = memberId;
}

// 全局点击关闭"更多迭代"下拉
function handleClickOutside(e: MouseEvent) {
    if (!iterMoreOpen.value) return;
    const target = e.target as HTMLElement;
    if (!target.closest(".iter-more-wrap")) {
        iterMoreOpen.value = false;
    }
}

onMounted(() => {
    loadIterations();
    document.addEventListener("click", handleClickOutside);
});

onBeforeUnmount(() => {
    document.removeEventListener("click", handleClickOutside);
});
</script>

<template>
    <div class="space-y-3">
        <div class="wall-scope-bar">
            <div class="wall-scope-tabs">
                <button
                    type="button"
                    class="wall-scope-tab"
                    :class="{ active: scope === 'all' }"
                    @click="scope = 'all'"
                >
                    全部项目
                </button>
                <button
                    type="button"
                    class="wall-scope-tab"
                    :class="{ active: scope === 'current' }"
                    :disabled="!store.selectedProjectId"
                    @click="store.selectedProjectId && (scope = 'current')"
                >
                    当前项目
                    <span v-if="scope === 'current' && currentProjectName" class="wall-scope-project">
                        ({{ currentProjectName }})
                    </span>
                </button>
            </div>

            <template v-if="scope === 'current'">
                <div class="wall-scope-divider"></div>
                <div class="wall-scope-tabs">
                    <button
                        type="button"
                        class="wall-scope-tab"
                        :class="{ active: selectedIterationId === ITER_ALL }"
                        @click="setIteration(ITER_ALL)"
                    >
                        全部
                    </button>
                    <button
                        type="button"
                        class="wall-scope-tab"
                        :class="{ active: selectedIterationId === ITER_ACTIVE }"
                        :disabled="!activeIteration"
                        :title="activeIteration ? '当前进行中的迭代' : '当前项目暂无进行中的迭代'"
                        @click="activeIteration && setIteration(ITER_ACTIVE)"
                    >
                        当前迭代
                        <span v-if="selectedIterationId === ITER_ACTIVE && activeIteration" class="wall-scope-project">
                            ({{ activeIteration.name }})
                        </span>
                    </button>
                    <button
                        v-for="iter in visibleIterations"
                        :key="iter.id"
                        type="button"
                        class="wall-scope-tab"
                        :class="{ active: selectedIterationId === iter.id }"
                        @click="setIteration(iter.id)"
                    >
                        {{ iter.name }}
                    </button>
                    <div v-if="moreIterations.length" class="iter-more-wrap">
                        <button
                            type="button"
                            class="wall-scope-tab iter-more-trigger"
                            :class="{ active: iterMoreOpen }"
                            @click="iterMoreOpen = !iterMoreOpen"
                        >
                            更多
                            <ChevronDown :size="12" :class="{ 'iter-arrow-open': iterMoreOpen }" />
                        </button>
                        <Transition name="iter-dropdown">
                            <div v-if="iterMoreOpen" class="iter-more-dropdown">
                                <button
                                    v-for="iter in moreIterations"
                                    :key="iter.id"
                                    type="button"
                                    class="iter-more-item"
                                    :class="{ active: selectedIterationId === iter.id }"
                                    @click="setIteration(iter.id)"
                                >
                                    <span class="iter-name">{{ iter.name }}</span>
                                    <span class="iter-status" :class="`iter-status-${iter.status}`">
                                        {{ iterStatusLabel[iter.status] || iter.status }}
                                    </span>
                                </button>
                            </div>
                        </Transition>
                    </div>
                    <button
                        type="button"
                        class="wall-scope-tab"
                        :class="{ active: selectedIterationId === ITER_UNPLANNED }"
                        @click="setIteration(ITER_UNPLANNED)"
                    >
                        未排期
                    </button>
                </div>
            </template>
        </div>

        <IterationHealthBar
            v-if="showHealthBar"
            :iteration-id="effectiveIterationId"
        />

        <MemberWorkloadPanel
            ref="memberPanelRef"
            :project-id="tableProjectId"
            :project-ids="tableProjectIds"
            :iteration-id="effectiveIterationId"
            :iteration-name="selectedIteration?.name || ''"
            :selected-member-id="focusedMemberId"
            @select-member="handleSelectMember"
            @select-member-type="handleSelectMemberType"
            @select-member-risk="handleSelectMemberRisk"
        />

        <WorkItemTable
            ref="workItemTableRef"
            type=""
            page-title="工作墙"
            create-button-text="+ 新建"
            create-drawer-title="新建工作项"
            detail-drawer-title="工作项详情"
            :project-id="tableProjectId"
            :project-ids="tableProjectIds"
            :iteration-id="effectiveIterationId"
            :view-filters="tableViewFilters"
            use-api
        />
    </div>
</template>

<style scoped>
.wall-scope-bar {
    background: #fff;
    border-radius: 12px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.wall-scope-tabs {
    display: inline-flex;
    background: #f3f4f6;
    border-radius: 8px;
    padding: 4px;
    gap: 4px;
    align-items: center;
}

.wall-scope-tab {
    padding: 6px 16px;
    border: none;
    background: transparent;
    border-radius: 6px;
    color: #6b7280;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    line-height: 1.4;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.wall-scope-tab:hover:not(:disabled) {
    color: var(--vort-primary, #1456f0);
}

.wall-scope-tab.active {
    background: #fff;
    color: var(--vort-primary, #1456f0);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.wall-scope-tab:disabled {
    cursor: not-allowed;
    opacity: 0.5;
}

.wall-scope-project {
    margin-left: 4px;
    color: var(--vort-text-secondary, #6b7280);
    font-size: 12px;
}

.wall-scope-divider {
    width: 1px;
    height: 18px;
    background: #e5e7eb;
}

.iter-more-wrap {
    position: relative;
}

.iter-more-trigger {
    cursor: pointer;
}

.iter-arrow-open {
    transform: rotate(180deg);
    transition: transform 0.2s;
}

.iter-more-dropdown {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    min-width: 180px;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12);
    padding: 4px;
    z-index: 50;
    max-height: 320px;
    overflow-y: auto;
}

.iter-more-item {
    display: flex;
    width: 100%;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    border: none;
    background: transparent;
    text-align: left;
    color: #1e293b;
    font-size: 13px;
    cursor: pointer;
    border-radius: 6px;
    transition: background 0.15s;
    white-space: nowrap;
}

.iter-more-item:hover {
    background: rgba(0, 0, 0, 0.04);
}

.iter-more-item.active {
    background: var(--vort-primary-bg, rgba(20, 86, 240, 0.06));
    color: var(--vort-primary, #1456f0);
}

.iter-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
}

.iter-status {
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 4px;
    background: #f3f4f6;
    color: #6b7280;
}

.iter-status.iter-status-active {
    background: rgba(16, 185, 129, 0.1);
    color: #047857;
}

.iter-status.iter-status-completed {
    background: rgba(107, 114, 128, 0.1);
    color: #4b5563;
}

.iter-status.iter-status-planning {
    background: rgba(59, 130, 246, 0.1);
    color: #1d4ed8;
}

.iter-dropdown-enter-active,
.iter-dropdown-leave-active {
    transition: opacity 0.15s, transform 0.15s;
}

.iter-dropdown-enter-from,
.iter-dropdown-leave-to {
    opacity: 0;
    transform: translateY(-4px);
}
</style>
