<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle, Clock, Flame, GripVertical, Pause, TrendingUp, X } from "lucide-vue-next";
import type { MemberWorkloadItem } from "@/api";
import Sparkline from "./Sparkline.vue";
import ActivityHeatStrip from "./ActivityHeatStrip.vue";
import MemberCardTooltip from "./MemberCardTooltip.vue";

/**
 * 成员关注卡片。从 MemberWorkloadPanel 抽出，同时承接 Phase 2 新增的：
 * - 在手 7 日 Sparkline
 * - 活动热度 7 格条
 * - 停滞 Badge
 *
 * 不在卡片本身维护拖拽 / 选中等全局状态，由父组件透传。
 */
interface MemberCardMember {
    id: string;
    name: string;
    avatar_url?: string;
}

interface Props {
    member: MemberCardMember;
    workload: MemberWorkloadItem;
    /** 是否被选中（点击高亮） */
    selected?: boolean;
    /** 父组件正在拖拽这张卡片（用于 0.4 透明度反馈） */
    dragging?: boolean;
    /** 头像是否加载失败（外层维护，避免组件卸载丢失态） */
    avatarError?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    selected: false,
    dragging: false,
    avatarError: false,
});

const emit = defineEmits<{
    /** 整张卡片被点击（除删除按钮外） */
    select: [];
    /** 取消关注 */
    remove: [];
    /** 头像加载失败，外层应记录 avatarError */
    "avatar-error": [];
    /** 用户在 hover popover 内点了「发送通知」 */
    "send-notify": [];
    /** 用户点击了需求/任务/缺陷 chip，按类型筛选 */
    "select-type": [type: "需求" | "任务" | "缺陷"];
    /** 用户点击了「逾期」「停滞」风险徽章，按风险筛选 */
    "select-risk": [risk: "overdue" | "stale"];
}>();

// 父组件透传的 attrs（draggable / 拖拽事件等）需要绑定到 .member-card
// 而不是 popover wrapper，否则拖拽和点击会失效
defineOptions({ inheritAttrs: false });

const palette = ["#2f80ed", "#5b8ff9", "#9b59b6", "#27ae60", "#f39c12", "#e67e22", "#16a085", "#8b44ad"];

const avatarBg = computed(() => {
    const name = props.member.name || "?";
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    }
    return palette[hash % palette.length];
});

const avatarLabel = computed(() => {
    const n = (props.member.name || "").trim();
    return n ? n.slice(0, 1).toUpperCase() : "?";
});

const showAvatarImg = computed(() => !!props.member.avatar_url && !props.avatarError);

/** 风险标签是否要显示这一行 */
const showRiskRow = computed(() => {
    const w = props.workload;
    return (w.overdue || 0) > 0
        || (w.urgent || 0) > 0
        || (w.due_soon || 0) > 0
        || (w.stale_count || 0) > 0;
});

/**
 * 卡片上的风险徽章按优先级顺序排列，超过 3 个折叠到「+N」气泡中。
 * 优先级：逾期 > 停滞 > 即将到期 > 紧急；保证最严重的两三类先暴露。
 *
 * 注：stale_count 与 overdue 在后端已互斥（已逾期项不再计入 stale），
 * 因此这里同时显示「逾期」和「停滞」时不会有数字重复。
 */
interface RiskBadge {
    key: "overdue" | "stale" | "soon" | "urgent";
    icon: typeof AlertTriangle;
    count: number;
    cls: string;
    short: string;
    full: string;
}

const riskBadges = computed<RiskBadge[]>(() => {
    const w = props.workload;
    const all: RiskBadge[] = [
        {
            key: "overdue",
            icon: AlertTriangle,
            count: w.overdue || 0,
            cls: "danger",
            short: "逾",
            full: `逾期 ${w.overdue || 0} 项 · 截止日期已过且未完成`,
        },
        {
            key: "stale",
            icon: Pause,
            count: w.stale_count || 0,
            cls: "stale",
            short: "滞",
            full: `停滞 ${w.stale_count || 0} 项 · 超过 7 天没有任何动作（事件 / 评论），不含已逾期项`,
        },
        {
            key: "soon",
            icon: Clock,
            count: w.due_soon || 0,
            cls: "soon",
            short: "近",
            full: `即将到期 ${w.due_soon || 0} 项 · 3 天内截止`,
        },
        {
            key: "urgent",
            icon: Flame,
            count: w.urgent || 0,
            cls: "warn",
            short: "急",
            full: `紧急 ${w.urgent || 0} 项 · 需求 P1/P2 或缺陷严重 1-2`,
        },
    ];
    return all.filter((b) => b.count > 0);
});

/** 第一项（最严重）保留中文短语，其余仅图标 + 数字，节省横向空间 */
const primaryBadge = computed<RiskBadge | null>(() => riskBadges.value[0] || null);
const secondaryBadges = computed<RiskBadge[]>(() => riskBadges.value.slice(1));

/** 风险一句话总览（卡片角落 + tooltip 用） */
const riskSummary = computed(() => {
    const arr = riskBadges.value;
    if (!arr.length) return "";
    return arr
        .map((b) => {
            const label = b.key === "overdue"
                ? "逾期"
                : b.key === "stale"
                    ? "停滞"
                    : b.key === "soon"
                        ? "即将到期"
                        : "紧急";
            return `${label} ${b.count}`;
        })
        .join(" · ");
});

/** 今日完成数：daily_completed 数组的最后一个元素（旧→新顺序，最后一项=今天） */
const todayCompleted = computed(() => {
    const arr = props.workload.daily_completed || [];
    return arr.length ? Number(arr[arr.length - 1] || 0) : 0;
});

/**
 * 流速：最近 7 天完成数 + 与前 7 天的同比。占位在原部门行的位置，
 * 让运营看一眼就能判断成员产能趋势，不必再 hover 浮层。
 */
const completedRecent7d = computed(() => Number(props.workload.completed_recent || 0));
const completedPrev7d = computed(() => Number(props.workload.completed_prev || 0));

const flowDeltaTag = computed<{
    text: string;
    cls: "up" | "down" | "flat";
} | null>(() => {
    if (completedPrev7d.value === 0 && completedRecent7d.value === 0) return null;
    const d = completedRecent7d.value - completedPrev7d.value;
    if (d === 0) return { text: "持平", cls: "flat" };
    if (d > 0) return { text: `+${d}`, cls: "up" };
    return { text: `${d}`, cls: "down" };
});

/** 没有任何完成数据时（前后 7 天均为 0）整行隐藏，避免空占位 */
const flowVisible = computed(() => completedRecent7d.value > 0 || completedPrev7d.value > 0);

const flowTooltip = computed(() => {
    if (!flowVisible.value) return "";
    const r = completedRecent7d.value;
    const p = completedPrev7d.value;
    const d = r - p;
    const deltaStr = d === 0 ? "持平" : d > 0 ? `+${d}` : `${d}`;
    return `近 7 天完成 ${r} 项 · 前 7 天 ${p} 项 · 同比 ${deltaStr}`;
});

/**
 * Sparkline 每个数据点的 hover 标签（从 N-1 天前到今天）。
 * 同时拼出当天的「在手」与「完成」两个数字，配合柱图叠加方便对照。
 */
const pendingHistoryLabels = computed(() => {
    const arr = props.workload.pending_history_7d || [];
    const completed = props.workload.daily_completed || [];
    return arr.map((v, i) => {
        const offset = arr.length - 1 - i;
        const dayLabel = offset === 0 ? "今天" : offset === 1 ? "昨天" : `${offset} 天前`;
        const c = Number(completed[i] || 0);
        const cPart = c > 0 ? ` · 完成 ${c}` : "";
        return `${dayLabel} 在手 ${v}${cPart}`;
    });
});

/** 活动热度每个 cell 的 label，从 N-1 天前到今天 */
const activityLabels = computed(() => {
    const arr = props.workload.activity_7d || [];
    return arr.map((v, i) => {
        const offset = arr.length - 1 - i;
        if (offset === 0) return `今天 ${v} 次`;
        if (offset === 1) return `昨天 ${v} 次`;
        return `${offset} 天前 ${v} 次`;
    });
});

function onAvatarError() {
    emit("avatar-error");
}

function onClickRemove(e: Event) {
    e.stopPropagation();
    emit("remove");
}

function onCardClick() {
    emit("select");
}

function onChipClick(e: Event, chipType: "需求" | "任务" | "缺陷") {
    e.stopPropagation();
    emit("select-type", chipType);
}

/** 逾期 / 停滞徽章可点击，直达对应风险筛选；其余徽章仅展示 */
function isRiskBadgeClickable(key: RiskBadge["key"]): boolean {
    return key === "overdue" || key === "stale";
}

function onRiskBadgeClick(e: Event, key: RiskBadge["key"]) {
    if (!isRiskBadgeClickable(key)) return;
    e.stopPropagation();
    emit("select-risk", key as "overdue" | "stale");
}
</script>

<template>
    <div
        class="member-card-wrapper"
        v-bind="$attrs"
        :class="{ 'is-dragging-wrapper': dragging }"
    >
        <vort-popover
            trigger="hover"
            placement="rightTop"
            :mouse-enter-delay="350"
            :mouse-leave-delay="100"
            :arrow="false"
            overlay-class="vw-mc-tooltip-overlay"
            :disabled="dragging"
        >
            <div
                class="member-card"
                role="button"
                tabindex="0"
                :class="{
                    selected,
                    'is-dragging': dragging,
                }"
                :aria-label="`${member.name} · 在手 ${workload.pending_total} · 点击筛选其工作项`"
                @click="onCardClick"
                @keydown.enter="onCardClick"
                @keydown.space.prevent="onCardClick"
            >
        <span class="member-drag-handle" title="拖拽排序">
            <GripVertical :size="12" />
        </span>
        <button
            class="member-remove-btn"
            title="取消关注"
            draggable="false"
            @click="onClickRemove"
            @mousedown.stop
        >
            <X :size="12" />
        </button>

        <div class="member-card-head">
            <span class="member-avatar" :style="{ backgroundColor: avatarBg }">
                <img
                    v-if="showAvatarImg"
                    :src="member.avatar_url"
                    :alt="member.name"
                    @error="onAvatarError"
                />
                <span v-else>{{ avatarLabel }}</span>
            </span>
            <div class="member-name-block">
                <div class="member-name" :title="member.name">{{ member.name }}</div>
                <div
                    v-if="flowVisible"
                    class="member-flow"
                    :title="flowTooltip"
                >
                    <TrendingUp :size="11" class="member-flow-icon" />
                    <span class="member-flow-text">
                        流速 <strong>{{ completedRecent7d }}</strong>/周
                    </span>
                    <span
                        v-if="flowDeltaTag"
                        class="member-flow-tag"
                        :class="`tone-${flowDeltaTag.cls}`"
                    >{{ flowDeltaTag.text }}</span>
                </div>
            </div>
            <div class="member-total" :title="`今日完成 ${todayCompleted} 项 · 在手 ${workload.pending_total} 项`">
                <span class="member-total-num">
                    <span
                        class="member-total-done"
                        :class="{ 'is-zero': todayCompleted === 0 }"
                    >{{ todayCompleted > 0 ? `+${todayCompleted}` : '0' }}</span>
                    <span class="member-total-sep"> /</span>
                    <span class="member-total-pending">{{ workload.pending_total }}</span>
                </span>
                <span class="member-total-label">完成 / 在手</span>
            </div>
        </div>

        <div v-if="showRiskRow" class="member-meta-row" :title="riskSummary">
            <component
                :is="isRiskBadgeClickable(primaryBadge.key) ? 'button' : 'span'"
                v-if="primaryBadge"
                :type="isRiskBadgeClickable(primaryBadge.key) ? 'button' : undefined"
                class="member-badge"
                :class="[primaryBadge.cls, { 'is-clickable': isRiskBadgeClickable(primaryBadge.key) }]"
                :title="isRiskBadgeClickable(primaryBadge.key) ? `${primaryBadge.full} · 点击筛选` : primaryBadge.full"
                @click="onRiskBadgeClick($event, primaryBadge.key)"
            >
                <component :is="primaryBadge.icon" :size="12" />
                {{ primaryBadge.short }} {{ primaryBadge.count }}
            </component>
            <component
                :is="isRiskBadgeClickable(b.key) ? 'button' : 'span'"
                v-for="b in secondaryBadges"
                :key="b.key"
                :type="isRiskBadgeClickable(b.key) ? 'button' : undefined"
                class="member-badge member-badge-compact"
                :class="[b.cls, { 'is-clickable': isRiskBadgeClickable(b.key) }]"
                :title="isRiskBadgeClickable(b.key) ? `${b.full} · 点击筛选` : b.full"
                @click="onRiskBadgeClick($event, b.key)"
            >
                <component :is="b.icon" :size="11" />
                {{ b.count }}
            </component>
        </div>

        <div class="member-type-row">
            <button class="member-chip story" @click="onChipClick($event, '需求')">需求 {{ workload.by_type.story }}</button>
            <button class="member-chip task" @click="onChipClick($event, '任务')">任务 {{ workload.by_type.task }}</button>
            <button class="member-chip bug" @click="onChipClick($event, '缺陷')">缺陷 {{ workload.by_type.bug }}</button>
        </div>

        <div
            v-if="(workload.pending_history_7d && workload.pending_history_7d.length) || (workload.activity_7d && workload.activity_7d.length)"
            class="member-trend-row"
        >
            <div
                v-if="workload.pending_history_7d && workload.pending_history_7d.length"
                class="member-trend-cell"
            >
                <span class="member-trend-label">7d</span>
                <Sparkline
                    :values="workload.pending_history_7d"
                    :width="56"
                    :height="16"
                    color="#3b82f6"
                    fill-color="rgba(59, 130, 246, 0.12)"
                    mode="area"
                    :labels="pendingHistoryLabels"
                    :secondary-values="workload.daily_completed || []"
                    secondary-color="#10b981"
                />
            </div>
            <div
                v-if="workload.activity_7d && workload.activity_7d.length"
                class="member-trend-cell"
            >
                <span class="member-trend-label">活动</span>
                <ActivityHeatStrip
                    :values="workload.activity_7d"
                    :width="70"
                    :height="10"
                    :labels="activityLabels"
                />
            </div>
        </div>
            </div>

            <template #content>
                <MemberCardTooltip
                    :workload="workload"
                    :member-name="member.name"
                    @send-notify="emit('send-notify')"
                />
            </template>
        </vort-popover>
    </div>
</template>

<style scoped>
.member-card-wrapper {
    display: flex;
    width: 100%;
    min-width: 0;
    /* Stretch to the grid row height so siblings in the same row align */
    height: 100%;
}
.member-card-wrapper > * {
    flex: 1;
    min-width: 0;
}
.member-card-wrapper.is-dragging-wrapper {
    cursor: grabbing;
}

.member-card {
    position: relative;
    background: #fff;
    border-radius: 12px;
    padding: 14px 16px;
    cursor: pointer;
    transition: box-shadow 0.15s, background 0.15s, opacity 0.15s, border-color 0.15s;
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    border: 1px solid transparent;
    width: 100%;
    /* Fill the wrapper height so trend-row can be pinned to the bottom */
    height: 100%;
}
.member-card:hover {
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}
.member-card.selected {
    background: var(--vort-primary-bg, rgba(20, 86, 240, 0.05));
}
.member-card.is-dragging {
    opacity: 0.4;
}

.member-drag-handle {
    position: absolute;
    top: 6px;
    left: 6px;
    width: 20px;
    height: 20px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #cbd5e1;
    border-radius: 4px;
    cursor: grab;
    opacity: 0;
    transition: opacity 0.15s, color 0.15s;
    pointer-events: none;
}
.member-card:hover .member-drag-handle {
    opacity: 1;
}
.member-card.is-dragging .member-drag-handle {
    cursor: grabbing;
}

.member-remove-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 20px;
    height: 20px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: #9ca3af;
    border-radius: 4px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s, background 0.15s;
}
.member-card:hover .member-remove-btn {
    opacity: 1;
}
.member-remove-btn:hover {
    background: #f3f4f6;
    color: #ef4444;
}

.member-card-head {
    display: flex;
    align-items: center;
    gap: 10px;
}

.member-avatar {
    width: 36px;
    height: 36px;
    border-radius: 999px;
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    flex-shrink: 0;
}
.member-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.member-name-block {
    flex: 1;
    min-width: 0;
}
.member-name {
    font-size: 14px;
    font-weight: 500;
    color: #1f2937;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.member-flow {
    margin-top: 2px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    line-height: 1.4;
    color: #6b7280;
    max-width: 100%;
    overflow: hidden;
    white-space: nowrap;
}
.member-flow-icon {
    color: #9ca3af;
    flex-shrink: 0;
}
.member-flow-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.member-flow-text strong {
    color: #1f2937;
    font-weight: 600;
}
.member-flow-tag {
    display: inline-flex;
    align-items: center;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    line-height: 1.6;
    flex-shrink: 0;
}
.member-flow-tag.tone-up {
    background: rgba(34, 197, 94, 0.12);
    color: #15803d;
}
.member-flow-tag.tone-down {
    background: rgba(239, 68, 68, 0.12);
    color: #b91c1c;
}
.member-flow-tag.tone-flat {
    background: rgba(107, 114, 128, 0.12);
    color: #4b5563;
}

.member-total {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    line-height: 1;
    flex-shrink: 0;
}
.member-total-num {
    display: inline-flex;
    align-items: baseline;
    gap: 1px;
    font-weight: 600;
    color: #1f2937;
    white-space: nowrap;
    line-height: 1;
}
.member-total-done {
    font-size: 16px;
    color: #059669;
}
.member-total-done.is-zero {
    color: #cbd5e1;
}
.member-total-sep {
    margin: 0 1px;
    color: #cbd5e1;
    font-size: 16px;
    font-weight: 400;
}
.member-total-pending {
    font-size: 20px;
    color: #1f2937;
}
.member-total-label {
    margin-top: 3px;
    font-size: 11px;
    color: #9ca3af;
    white-space: nowrap;
}

.member-meta-row {
    display: flex;
    align-items: center;
    flex-wrap: nowrap;
    gap: 4px;
    overflow: hidden;
    min-width: 0;
}

.member-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    line-height: 1.7;
    flex-shrink: 0;
    font-weight: 500;
    white-space: nowrap;
    border: none;
    font-family: inherit;
}
.member-badge.is-clickable {
    cursor: pointer;
    transition: opacity 0.15s, box-shadow 0.15s;
}
.member-badge.is-clickable:hover {
    opacity: 0.85;
    box-shadow: 0 0 0 1.5px currentColor;
}
/* 紧凑模式：仅图标 + 数字，节省宽度，避免一行内换行 */
.member-badge-compact {
    gap: 3px;
    padding: 1px 6px;
    font-weight: 600;
}
.member-badge.danger {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
}
.member-badge.warn {
    background: rgba(249, 115, 22, 0.1);
    color: #ea580c;
}
.member-badge.soon {
    background: rgba(245, 158, 11, 0.1);
    color: #b45309;
}
.member-badge.stale {
    background: rgba(107, 114, 128, 0.12);
    color: #4b5563;
}

.member-type-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

.member-chip {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    background: #f3f4f6;
    color: #4b5563;
    line-height: 1.6;
    border: none;
    cursor: pointer;
    transition: opacity 0.15s, box-shadow 0.15s;
}
.member-chip:hover {
    opacity: 0.8;
    box-shadow: 0 0 0 1.5px currentColor;
}
.member-chip.story {
    background: rgba(59, 130, 246, 0.08);
    color: #1d4ed8;
}
.member-chip.task {
    background: rgba(16, 185, 129, 0.08);
    color: #047857;
}
.member-chip.bug {
    background: rgba(244, 63, 94, 0.08);
    color: #be123c;
}
.member-chip.done {
    background: rgba(5, 150, 105, 0.18);
    color: #065f46;
}

.member-trend-row {
    display: flex;
    align-items: center;
    gap: 14px;
    /* Push to the bottom so all cards in the same grid row align this strip */
    margin-top: auto;
    padding-top: 6px;
    border-top: 1px dashed rgba(15, 23, 42, 0.06);
}
.member-trend-cell {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.member-trend-label {
    font-size: 10px;
    color: #9ca3af;
    line-height: 1;
    letter-spacing: 0.02em;
}
</style>
