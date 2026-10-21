<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ChevronDown, ChevronUp, Plus } from "lucide-vue-next";
import { message } from "@openvort/vort-ui";
import { getMembersSimple, getVortflowMembersWorkload } from "@/api";
import type { MemberWorkloadItem } from "@/api/vortflow";
import { MemberPicker } from "@/components/vort-biz/member-picker";
import MemberCard from "./workload/MemberCard.vue";
import MemberNotifyDialog from "./workload/MemberNotifyDialog.vue";

interface SimpleMember {
    id: string;
    name: string;
    avatar_url?: string;
    is_virtual?: boolean;
    dept?: string;
}

/** 默认空工作量（在 workloadMap 还没拿到该成员数据时占位用） */
function emptyWorkload(memberId: string): MemberWorkloadItem {
    return {
        member_id: memberId,
        pending_total: 0,
        by_type: { story: 0, task: 0, bug: 0 },
        overdue: 0,
        due_soon: 0,
        urgent: 0,
        completed_recent: 0,
        completed_prev: 0,
        avg_lead_time_days: 0,
        team_avg_lead_time_days: 0,
        stale_count: 0,
        activity_7d: [],
        pending_history_7d: [],
        daily_completed: [],
        daily_created: [],
        future_due: [],
        future_overdue_cumulative: [],
    };
}

interface Props {
    /** 当前生效的项目过滤；空表示全部项目 */
    projectId?: string;
    /** 多项目筛选范围；非空时优先于 projectId */
    projectIds?: string[];
    /** 当前生效的迭代过滤；空=全部，'__unplanned__'=未排期，其他=具体迭代 id */
    iterationId?: string;
    /** 当前迭代名（用于面板 hint 文案展示） */
    iterationName?: string;
    /** 父组件下方表格当前筛选的成员，用于卡片高亮 */
    selectedMemberId?: string;
}

const props = withDefaults(defineProps<Props>(), {
    projectId: "",
    projectIds: () => [],
    iterationId: "",
    iterationName: "",
    selectedMemberId: "",
});

const emit = defineEmits<{
    "select-member": [memberId: string];
    "select-member-type": [memberId: string, type: "需求" | "任务" | "缺陷"];
    "select-member-risk": [memberId: string, risk: "overdue" | "stale"];
}>();

const STORAGE_KEY = "vortflow_wall_member_watchlist_v1";
const SORT_STORAGE_KEY = "vortflow_wall_member_sort_v1";

type SortKey =
    | "custom"
    | "overdue"
    | "pending_total"
    | "due_soon"
    | "urgent"
    | "stale_count"
    | "completed_recent";

interface SortOption {
    value: SortKey;
    label: string;
    /** 取该成员卡片的排序权重（越大越靠前） */
    metric?: (w: MemberWorkloadItem) => number;
}

const SORT_OPTIONS: SortOption[] = [
    { value: "custom", label: "自定义排序" },
    { value: "overdue", label: "逾期数", metric: (w) => w.overdue || 0 },
    { value: "pending_total", label: "当日在手量", metric: (w) => w.pending_total || 0 },
    { value: "due_soon", label: "临期数", metric: (w) => w.due_soon || 0 },
    { value: "urgent", label: "紧急数", metric: (w) => w.urgent || 0 },
    { value: "stale_count", label: "停滞数", metric: (w) => w.stale_count || 0 },
    { value: "completed_recent", label: "近期完成", metric: (w) => w.completed_recent || 0 },
];
/**
 * 软提示阈值：超过此人数时弹一次性能 warning，但不阻止保存。
 * 数据加载在后端按 member_ids 批量聚合，瓶颈是 SQL 聚合而非前端，
 * 因此不再做硬上限。当一次性新增导致跨过阈值时给用户一个心理预期。
 */
const SOFT_WARN_THRESHOLD = 50;

const memberIds = ref<string[]>(loadFromStorage());
const memberMap = ref<Record<string, SimpleMember>>({});
const workloadMap = ref<Record<string, MemberWorkloadItem>>({});
const loading = ref(false);
const collapsed = ref(false);
const pickerOpen = ref(false);
const pickerDraft = ref<string[]>([]);
const avatarErrorIds = ref<Record<string, boolean>>({});
const draggedIndex = ref<number | null>(null);
const sortKey = ref<SortKey>(loadSortFromStorage());

// 「发送通知」对话框：把弹窗挂在 panel 这层而不是放进 popover content，
// 否则 hover popover 一关闭弹窗也会被卸载。
const notifyOpen = ref(false);
const notifyTargetId = ref("");

const notifyTarget = computed(() => {
    const id = notifyTargetId.value;
    if (!id) return null;
    const m = memberMap.value[id];
    const w = workloadMap.value[id];
    if (!m) return null;
    return {
        member: {
            id,
            name: m.name || id.slice(0, 6),
            avatarUrl: m.avatar_url || "",
            dept: m.dept || "",
        },
        workload: w
            ? {
                pending_total: w.pending_total || 0,
                overdue: w.overdue || 0,
                due_soon: w.due_soon || 0,
                stale_count: w.stale_count || 0,
            }
            : undefined,
    };
});

function openNotify(memberId: string) {
    notifyTargetId.value = memberId;
    notifyOpen.value = true;
}

function loadFromStorage(): string[] {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr.filter((x) => typeof x === "string" && x) : [];
    } catch {
        return [];
    }
}

function saveToStorage(ids: string[]) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch {
        /* ignore */
    }
}

function loadSortFromStorage(): SortKey {
    try {
        const raw = localStorage.getItem(SORT_STORAGE_KEY);
        if (raw && SORT_OPTIONS.some((o) => o.value === raw)) {
            return raw as SortKey;
        }
    } catch {
        /* ignore */
    }
    return "custom";
}

function saveSortToStorage(key: SortKey) {
    try {
        localStorage.setItem(SORT_STORAGE_KEY, key);
    } catch {
        /* ignore */
    }
}

const isCustomSort = computed(() => sortKey.value === "custom");

function onSortChange(val: SortKey) {
    sortKey.value = val;
    saveSortToStorage(val);
}

async function loadMembers() {
    try {
        const res: any = await getMembersSimple({ size: 500 });
        const all: SimpleMember[] = res?.members || [];
        const map: Record<string, SimpleMember> = {};
        for (const m of all) {
            if (m.id) map[m.id] = m;
        }
        memberMap.value = map;
    } catch {
        /* ignore */
    }
}

async function loadWorkload() {
    if (!memberIds.value.length) {
        workloadMap.value = {};
        return;
    }
    loading.value = true;
    try {
        const items = await getVortflowMembersWorkload({
            member_ids: memberIds.value.join(","),
            project_ids: (props.projectIds && props.projectIds.length) ? props.projectIds.join(",") : undefined,
            project_id: (props.projectIds && props.projectIds.length) ? undefined : (props.projectId || undefined),
            iteration_id: props.iterationId || undefined,
            history_days: 7,
            forecast_days: 7,
        });
        const map: Record<string, MemberWorkloadItem> = {};
        for (const x of items) map[x.member_id] = x;
        workloadMap.value = map;
    } catch (e) {
        console.warn("[MemberWorkloadPanel] load workload failed", e);
    } finally {
        loading.value = false;
    }
}

function openPicker() {
    pickerDraft.value = [...memberIds.value];
    pickerOpen.value = true;
}

function confirmPicker() {
    const valid = pickerDraft.value.filter((id) => !!memberMap.value[id]);
    const next = Array.from(new Set(valid));
    // 仅在「这次保存让人数从未超过阈值变为超过阈值」时弹一次软提示，
    // 避免每次打开-确认都骚扰用户。
    const wasOver = memberIds.value.length > SOFT_WARN_THRESHOLD;
    const isOver = next.length > SOFT_WARN_THRESHOLD;
    if (isOver && !wasOver) {
        message.warning(`关注成员超过 ${SOFT_WARN_THRESHOLD} 人，加载与渲染速度可能会变慢`);
    }
    memberIds.value = next;
    saveToStorage(memberIds.value);
    pickerOpen.value = false;
    loadWorkload();
}

function removeMember(id: string) {
    const next = memberIds.value.filter((x) => x !== id);
    memberIds.value = next;
    saveToStorage(next);
    if (props.selectedMemberId === id) {
        emit("select-member", "");
    }
    if (next.length) {
        loadWorkload();
    } else {
        workloadMap.value = {};
    }
}

function handleClickCard(id: string) {
    if (props.selectedMemberId === id) {
        emit("select-member", "");
    } else {
        emit("select-member", id);
    }
}

function handleChipClick(id: string, chipType: "需求" | "任务" | "缺陷") {
    emit("select-member-type", id, chipType);
}

function handleRiskClick(id: string, risk: "overdue" | "stale") {
    emit("select-member-risk", id, risk);
}

function onDragStart(e: DragEvent, index: number) {
    if (!isCustomSort.value) {
        // Non-custom sort uses computed metric ordering; disable manual drag
        // to avoid producing an order that conflicts with the active sort key.
        e.preventDefault();
        return;
    }
    draggedIndex.value = index;
    if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(index));
    }
}

// Live-reorder on dragenter (fires once per element entry) to avoid the
// jitter that dragover would cause by re-firing repeatedly while hovering.
function onDragEnter(_e: DragEvent, index: number) {
    const from = draggedIndex.value;
    if (from === null || from === index) return;
    const ids = [...memberIds.value];
    if (from < 0 || from >= ids.length) return;
    const moved = ids.splice(from, 1)[0];
    if (!moved) return;
    const target = Math.max(0, Math.min(index, ids.length));
    ids.splice(target, 0, moved);
    memberIds.value = ids;
    draggedIndex.value = target;
}

// dragover must call preventDefault so the drop is allowed.
function onDragOver(e: DragEvent) {
    if (draggedIndex.value === null) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
}

function onDrop(e: DragEvent) {
    e.preventDefault();
    if (draggedIndex.value !== null) {
        saveToStorage(memberIds.value);
    }
    draggedIndex.value = null;
}

function onDragEnd() {
    // Persist final order whether the drop landed on a card or anywhere else.
    if (draggedIndex.value !== null) {
        saveToStorage(memberIds.value);
    }
    draggedIndex.value = null;
}

const cards = computed(() => {
    const list = memberIds.value.map((id, idx) => {
        const m = memberMap.value[id];
        const w = workloadMap.value[id] || emptyWorkload(id);
        return {
            id,
            originalIndex: idx,
            member: {
                id,
                name: m?.name || id.slice(0, 6),
                avatar_url: m?.avatar_url || "",
            },
            workload: w,
            selected: props.selectedMemberId === id,
        };
    });
    const opt = SORT_OPTIONS.find((o) => o.value === sortKey.value);
    if (!opt || !opt.metric) return list;
    const metric = opt.metric;
    return [...list].sort((a, b) => {
        const diff = metric(b.workload) - metric(a.workload);
        if (diff !== 0) return diff;
        // Stable fallback: keep watchlist order for ties.
        return a.originalIndex - b.originalIndex;
    });
});

watch(() => [props.projectId, (props.projectIds || []).join(",")], () => loadWorkload());
watch(() => props.iterationId, () => loadWorkload());

// 60s 轮询刷新：工作项增删改后面板无法感知，靠定时刷新保持数据新鲜。
// 面板折叠、页面不可见、无关注成员时跳过，避免浪费请求。
const POLL_INTERVAL_MS = 60_000;
let pollTimer: ReturnType<typeof setInterval> | null = null;

function startPoll() {
    stopPoll();
    pollTimer = setInterval(() => {
        if (collapsed.value || !memberIds.value.length || document.hidden) return;
        loadWorkload();
    }, POLL_INTERVAL_MS);
}

function stopPoll() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

// 当前生效的迭代标签文案：在迭代模式下展示在标题旁
const iterScopeLabel = computed<string>(() => {
    if (props.iterationId === "__unplanned__") return "未排期";
    if (props.iterationId && props.iterationName) return props.iterationName;
    if (props.iterationId) return "迭代内";
    return "";
});

onMounted(async () => {
    await loadMembers();
    await loadWorkload();
    startPoll();
});

onBeforeUnmount(() => stopPoll());

defineExpose({ refresh: loadWorkload });
</script>

<template>
    <div class="member-workload-panel">
        <div class="panel-header">
            <div class="panel-header-left">
                <button class="collapse-btn" @click="collapsed = !collapsed">
                    <component :is="collapsed ? ChevronDown : ChevronUp" :size="14" />
                </button>
                <span class="panel-title">成员关注</span>
                <span class="panel-count">{{ memberIds.length }} 人</span>
                <span v-if="iterScopeLabel" class="panel-scope-label" :title="`当前显示 ${iterScopeLabel} 范围内的工作量`">
                    · {{ iterScopeLabel }} 内
                </span>
            </div>
            <div v-show="!collapsed && memberIds.length > 0" class="panel-header-right">
                <span class="panel-sort-label">排序</span>
                <vort-select
                    :model-value="sortKey"
                    class="panel-sort-select w-[140px]"
                    size="small"
                    @update:model-value="onSortChange($event as SortKey)"
                >
                    <vort-select-option
                        v-for="opt in SORT_OPTIONS"
                        :key="opt.value"
                        :value="opt.value"
                    >
                        {{ opt.label }}
                    </vort-select-option>
                </vort-select>
            </div>
        </div>

        <div v-show="!collapsed" class="panel-body">
            <vort-spin :spinning="loading">
                <TransitionGroup name="member-card" tag="div" class="member-grid">
                    <MemberCard
                        v-for="card in cards"
                        :key="card.id"
                        :member="card.member"
                        :workload="card.workload"
                        :selected="card.selected"
                        :dragging="isCustomSort && draggedIndex === card.originalIndex"
                        :avatar-error="!!avatarErrorIds[card.id]"
                        :draggable="isCustomSort"
                        @select="handleClickCard(card.id)"
                        @remove="removeMember(card.id)"
                        @avatar-error="avatarErrorIds[card.id] = true"
                        @send-notify="openNotify(card.id)"
                        @select-type="handleChipClick(card.id, $event)"
                        @select-risk="handleRiskClick(card.id, $event)"
                        @dragstart="onDragStart($event, card.originalIndex)"
                        @dragenter="onDragEnter($event, card.originalIndex)"
                        @dragover="onDragOver($event)"
                        @drop="onDrop($event)"
                        @dragend="onDragEnd"
                    />

                    <div
                        key="__add"
                        class="add-card"
                        role="button"
                        tabindex="0"
                        title="添加关注成员"
                        @click="openPicker"
                        @keydown.enter="openPicker"
                        @keydown.space.prevent="openPicker"
                    >
                        <div class="add-card-icon">
                            <Plus :size="18" />
                        </div>
                        <div v-if="!memberIds.length" class="add-card-hint">
                            盯紧成员的在手工作量与风险
                        </div>
                    </div>
                </TransitionGroup>
            </vort-spin>
        </div>

        <vort-dialog
            v-model:open="pickerOpen"
            title="选择关注成员"
            :width="640"
            ok-text="确定"
            @ok="confirmPicker"
        >
            <MemberPicker v-model="pickerDraft" title="已选成员" />
        </vort-dialog>

        <MemberNotifyDialog
            v-if="notifyTarget"
            v-model:open="notifyOpen"
            :member="notifyTarget.member"
            :workload="notifyTarget.workload"
            :project-id="projectId"
        />
    </div>
</template>

<style scoped>
.member-workload-panel {
    background: transparent;
}

.panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 0 4px;
}

.panel-header-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.collapse-btn {
    width: 22px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: #6b7280;
    cursor: pointer;
    border-radius: 4px;
}
.collapse-btn:hover {
    background: rgba(0, 0, 0, 0.04);
    color: #1f2937;
}

.panel-title {
    font-size: 14px;
    font-weight: 600;
    color: #1f2937;
}

.panel-count {
    font-size: 12px;
    color: #9ca3af;
}

.panel-scope-label {
    font-size: 12px;
    color: var(--vort-primary, #1456f0);
    margin-left: 2px;
}

.panel-header-right {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.panel-sort-label {
    font-size: 12px;
    color: #6b7280;
}

.panel-body {
    margin-top: 10px;
}

.member-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 12px;
}

/* TransitionGroup move animation: cards smoothly shift when reordered */
.member-card-move,
.add-card-move {
    transition: transform 0.25s ease;
}

.add-card {
    background: #fff;
    border-radius: 12px;
    cursor: pointer;
    transition: box-shadow 0.15s, color 0.15s;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    min-height: 132px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    color: #6b7280;
    text-align: center;
    padding: 16px;
}
.add-card:hover {
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
    color: var(--vort-primary, #1456f0);
}
.add-card-icon {
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    background: var(--vort-primary-bg, rgba(20, 86, 240, 0.06));
    color: var(--vort-primary, #1456f0);
}
.add-card-text {
    font-size: 13px;
    font-weight: 500;
    color: #1f2937;
}
.add-card-hint {
    font-size: 12px;
    color: #9ca3af;
}
</style>
