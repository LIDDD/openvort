<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { AlertCircle, CalendarDays, TrendingUp } from "lucide-vue-next";
import { getVortflowIterationHealth } from "@/api";

interface Contributor {
    member_id: string;
    name?: string;
    total: number;
    done: number;
}

interface IterationHealth {
    id: string;
    name: string;
    status: string;
    start_date: string | null;
    end_date: string | null;
    duration_days: number;
    elapsed_days: number;
    total: number;
    done: number;
    by_type: {
        story: { total: number; done: number };
        task: { total: number; done: number };
        bug: { total: number; done: number };
    };
    creep_count: number;
    not_estimated_count: number;
    top_contributors: Contributor[];
}

interface Props {
    /** 具体迭代 id；空字符串则不渲染 */
    iterationId: string;
}

const props = defineProps<Props>();

const data = ref<IterationHealth | null>(null);
const loading = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function loadHealth() {
    if (!props.iterationId) {
        data.value = null;
        return;
    }
    loading.value = true;
    try {
        const res: any = await getVortflowIterationHealth(props.iterationId);
        if (res?.error) {
            data.value = null;
        } else {
            data.value = res as IterationHealth;
        }
    } catch (e) {
        console.warn("[IterationHealthBar] load failed", e);
    } finally {
        loading.value = false;
    }
}

const timePercent = computed(() => {
    const d = data.value;
    if (!d || !d.duration_days) return 0;
    return Math.round((d.elapsed_days / d.duration_days) * 100);
});

const donePercent = computed(() => {
    const d = data.value;
    if (!d || !d.total) return 0;
    return Math.round((d.done / d.total) * 100);
});

// 偏离：负值=落后，正值=超前；当 |偏离| < 10 视为正常
const deviation = computed(() => donePercent.value - timePercent.value);

const statusBadge = computed(() => {
    const d = data.value;
    // 规划中：迭代还没真正开始，不评判超前/落后
    if (d?.status === "planning") return { tone: "neutral" as const, text: "未开始" };
    if (d?.status === "completed") return { tone: "neutral" as const, text: "已结束" };
    const dev = deviation.value;
    if (Math.abs(dev) < 10) return { tone: "neutral" as const, text: "进度正常" };
    if (dev <= -10) return { tone: "danger" as const, text: `落后 ${Math.abs(dev)}%` };
    return { tone: "good" as const, text: `超前 ${dev}%` };
});

const iterStatusLabel: Record<string, string> = {
    planning: "规划中",
    active: "进行中",
    completed: "已完成",
};

// 起止日期短格式：04-22
function formatShortDate(iso: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${m}-${day}`;
}

const dateRange = computed<string>(() => {
    const d = data.value;
    if (!d) return "";
    const start = formatShortDate(d.start_date);
    const end = formatShortDate(d.end_date);
    if (start && end) return `${start} ~ ${end}`;
    return start || end || "";
});

// "剩余 N 天" / "已逾期 N 天" / "今日结束" / "未开始"
const timeStateLabel = computed<{ text: string; tone: "neutral" | "good" | "danger" | "warn" } | null>(() => {
    const d = data.value;
    if (!d || !d.start_date || !d.end_date) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const start = new Date(d.start_date);
    start.setHours(0, 0, 0, 0);
    const end = new Date(d.end_date);
    end.setHours(0, 0, 0, 0);
    const dayMs = 24 * 60 * 60 * 1000;

    if (today.getTime() < start.getTime()) {
        const days = Math.ceil((start.getTime() - today.getTime()) / dayMs);
        return { text: `${days} 天后开始`, tone: "neutral" };
    }
    if (today.getTime() > end.getTime()) {
        const days = Math.ceil((today.getTime() - end.getTime()) / dayMs);
        return { text: `已逾期 ${days} 天`, tone: "danger" };
    }
    const remaining = Math.ceil((end.getTime() - today.getTime()) / dayMs);
    if (remaining === 0) return { text: "今日结束", tone: "warn" };
    return {
        text: `剩余 ${remaining} 天`,
        tone: remaining <= 3 ? "warn" : "neutral",
    };
});

const palette = ["#2f80ed", "#5b8ff9", "#9b59b6", "#27ae60", "#f39c12", "#e67e22", "#16a085", "#8b44ad"];
function avatarBg(name: string) {
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    return palette[hash % palette.length];
}
function avatarLabel(name: string) {
    if (!name) return "?";
    return name.trim().slice(0, 1).toUpperCase();
}

watch(() => props.iterationId, () => {
    loadHealth();
}, { immediate: false });

onMounted(() => {
    loadHealth();
    // 60s 轻量轮询：scope creep / 完成数等可能在迭代过程中实时变化
    pollTimer = setInterval(() => {
        if (document.visibilityState === "visible") {
            loadHealth();
        }
    }, 60000);
});

onBeforeUnmount(() => {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
});

defineExpose({ refresh: loadHealth });
</script>

<template>
    <vort-spin :spinning="loading">
        <div v-if="data" class="health-bar">
            <div class="health-section health-left">
                <div class="health-iter-title">
                    <span class="health-iter-name">{{ data.name }}</span>
                    <span class="health-iter-status" :class="`status-${data.status}`">
                        {{ iterStatusLabel[data.status] || data.status }}
                    </span>
                </div>
                <div v-if="dateRange" class="health-time-range">
                    <CalendarDays :size="13" />
                    <span>{{ dateRange }}</span>
                </div>
                <div v-if="timeStateLabel || data.duration_days" class="health-time-state">
                    <span v-if="data.duration_days" class="health-time-elapsed">
                        第 {{ data.elapsed_days }}/{{ data.duration_days }} 天
                    </span>
                    <span
                        v-if="timeStateLabel"
                        class="health-time-tag"
                        :class="`tone-${timeStateLabel.tone}`"
                    >
                        {{ timeStateLabel.text }}
                    </span>
                </div>
                <div v-if="!dateRange && !data.duration_days" class="health-time-state">
                    <span class="health-time-elapsed">未设置时间范围</span>
                </div>
            </div>

            <div class="health-section health-mid">
                <div class="health-progress-head">
                    <span class="health-progress-title">完成度</span>
                    <span class="health-progress-count">{{ data.done }}/{{ data.total }}</span>
                    <span class="health-progress-percent">{{ donePercent }}%</span>
                    <div class="health-deviation" :class="`tone-${statusBadge.tone}`">
                        <TrendingUp :size="12" v-if="statusBadge.tone === 'good'" />
                        <AlertCircle :size="12" v-else-if="statusBadge.tone === 'danger'" />
                        {{ statusBadge.text }}
                    </div>
                </div>
                <div class="health-progress-track" :title="`完成 ${donePercent}% · 时间 ${timePercent}%`">
                    <div class="health-progress-fill" :style="{ width: donePercent + '%' }"></div>
                    <div
                        v-if="data.duration_days && data.status !== 'planning'"
                        class="health-progress-time-marker"
                        :class="{ 'is-end': timePercent >= 95, 'is-start': timePercent <= 5 }"
                        :style="{ left: `min(100%, ${timePercent}%)` }"
                        :title="`今天 · 时间进度 ${timePercent}%`"
                    >
                        <span class="health-progress-time-label">今天</span>
                    </div>
                </div>
            </div>

            <div class="health-section health-right">
                <div class="health-meta-row">
                    <span class="health-meta">
                        <span class="health-meta-label">变更插入</span>
                        <span class="health-meta-num" :class="{ warn: data.creep_count > 0 }">+{{ data.creep_count }}</span>
                    </span>
                    <span class="health-meta">
                        <span class="health-meta-label">未估时</span>
                        <span class="health-meta-num" :class="{ warn: data.not_estimated_count > 0 }">{{ data.not_estimated_count }}</span>
                    </span>
                </div>
                <div v-if="data.top_contributors.length" class="health-contrib">
                    <span class="health-contrib-label">Top 贡献</span>
                    <div class="health-contrib-list">
                        <div
                            v-for="c in data.top_contributors"
                            :key="c.member_id"
                            class="health-contrib-item"
                            :title="`${c.name || '未知'} · ${c.done}/${c.total}`"
                        >
                            <span class="health-contrib-avatar" :style="{ backgroundColor: avatarBg(c.name || c.member_id) }">
                                {{ avatarLabel(c.name || c.member_id) }}
                            </span>
                            <span class="health-contrib-meta">
                                <span class="health-contrib-name">{{ c.name || c.member_id.slice(0, 6) }}</span>
                                <span class="health-contrib-num">{{ c.done }}/{{ c.total }}</span>
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </vort-spin>
</template>

<style scoped>
.health-bar {
    background: #fff;
    border-radius: 12px;
    padding: 12px 16px;
    display: flex;
    align-items: stretch;
    gap: 16px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    flex-wrap: wrap;
}

.health-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
}

.health-left {
    flex: 0 0 auto;
    min-width: 160px;
    justify-content: center;
    border-right: 1px solid #f1f5f9;
    padding-right: 16px;
}

.health-mid {
    flex: 1 1 320px;
    min-width: 280px;
    justify-content: center;
    gap: 0;
    padding: 4px 0 18px 0;
}

.health-right {
    flex: 0 0 auto;
    min-width: 220px;
    justify-content: center;
    border-left: 1px solid #f1f5f9;
    padding-left: 16px;
    gap: 8px;
}

.health-iter-title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.health-iter-name {
    font-size: 14px;
    font-weight: 600;
    color: #1f2937;
}

.health-iter-status {
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 4px;
    background: #f3f4f6;
    color: #6b7280;
}
.health-iter-status.status-active {
    background: rgba(16, 185, 129, 0.1);
    color: #047857;
}
.health-iter-status.status-completed {
    background: rgba(107, 114, 128, 0.1);
    color: #4b5563;
}
.health-iter-status.status-planning {
    background: rgba(59, 130, 246, 0.1);
    color: #1d4ed8;
}

.health-time-range {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: #4b5563;
    font-variant-numeric: tabular-nums;
}

.health-time-state {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    flex-wrap: wrap;
}

.health-time-elapsed {
    color: #9ca3af;
}

.health-time-tag {
    padding: 1px 6px;
    border-radius: 999px;
    font-size: 11px;
    line-height: 1.6;
}
.health-time-tag.tone-neutral {
    background: rgba(107, 114, 128, 0.08);
    color: #4b5563;
}
.health-time-tag.tone-warn {
    background: rgba(245, 158, 11, 0.12);
    color: #b45309;
}
.health-time-tag.tone-danger {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
}
.health-time-tag.tone-good {
    background: rgba(16, 185, 129, 0.1);
    color: #047857;
}

.health-progress-head {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.health-progress-title {
    font-size: 12px;
    color: #6b7280;
}

.health-progress-count {
    font-size: 13px;
    color: #1f2937;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
}

.health-progress-percent {
    font-size: 11px;
    color: #9ca3af;
    font-variant-numeric: tabular-nums;
}

.health-progress-track {
    position: relative;
    height: 8px;
    background: #eef2f7;
    border-radius: 999px;
    overflow: visible;
    margin-top: 6px;
}

.health-progress-fill {
    height: 100%;
    border-radius: 999px;
    background: var(--vort-primary, #1456f0);
    transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.health-progress-time-marker {
    position: absolute;
    top: -3px;
    bottom: -3px;
    width: 2px;
    background: #475569;
    border-radius: 2px;
    transform: translateX(-50%);
    pointer-events: none;
}
.health-progress-time-marker::after {
    content: "";
    position: absolute;
    top: -4px;
    left: 50%;
    transform: translateX(-50%);
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #475569;
}

.health-progress-time-label {
    position: absolute;
    top: calc(100% + 4px);
    left: 50%;
    transform: translateX(-50%);
    font-size: 10px;
    color: #475569;
    white-space: nowrap;
    background: rgba(248, 250, 252, 0.95);
    padding: 0 4px;
    border-radius: 3px;
    line-height: 1.4;
    pointer-events: none;
}
/* 时间贴右端时标签靠右对齐避免溢出 */
.health-progress-time-marker.is-end .health-progress-time-label {
    left: auto;
    right: 0;
    transform: none;
}
/* 时间在最左端（刚开始）时标签靠左 */
.health-progress-time-marker.is-start .health-progress-time-label {
    left: 0;
    transform: none;
}

.health-deviation {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    line-height: 1.6;
}
.health-deviation.tone-neutral {
    background: rgba(107, 114, 128, 0.08);
    color: #6b7280;
}
.health-deviation.tone-danger {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
}
.health-deviation.tone-good {
    background: rgba(16, 185, 129, 0.1);
    color: #047857;
}

.health-meta-row {
    display: flex;
    gap: 16px;
}

.health-meta {
    display: inline-flex;
    flex-direction: column;
    gap: 2px;
}

.health-meta-label {
    font-size: 11px;
    color: #9ca3af;
}

.health-meta-num {
    font-size: 16px;
    font-weight: 600;
    color: #1f2937;
    line-height: 1;
}

.health-meta-num.warn {
    color: #ea580c;
}

.health-contrib {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.health-contrib-label {
    font-size: 11px;
    color: #9ca3af;
}

.health-contrib-list {
    display: flex;
    gap: 12px;
}

.health-contrib-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.health-contrib-avatar {
    width: 22px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    color: #fff;
    font-size: 10px;
    font-weight: 600;
    flex-shrink: 0;
}

.health-contrib-meta {
    display: inline-flex;
    flex-direction: column;
    line-height: 1.1;
}

.health-contrib-name {
    font-size: 12px;
    color: #1f2937;
    max-width: 64px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.health-contrib-num {
    font-size: 11px;
    color: #6b7280;
    font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
    .health-left,
    .health-right {
        border: none;
        padding: 0;
    }
}
</style>
