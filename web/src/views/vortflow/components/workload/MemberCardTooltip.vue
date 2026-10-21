<script setup lang="ts">
import { computed } from "vue";
import { Activity, AlertTriangle, Pause, Send, TrendingUp } from "lucide-vue-next";
import type { MemberWorkloadItem } from "@/api/vortflow";
import WorkloadTimelineChart from "./WorkloadTimelineChart.vue";

/**
 * 成员卡片 hover 浮层内容：
 *
 * 1) 顶部 KPI 4 宫格：在手 / 7 日完成 / 平均流转 / 停滞
 * 2) 中部时间轴图表：过去 7 + 今 + 未来 7
 *    - 过去段：完成 / 新增（堆叠柱）+ 在手折线（实线）
 *    - 未来段：到期柱 + 在手投影折线（虚线，按 deadline 衰减）+ 累计逾期折线
 *    在手投影让用户能直观看到「未来还有多少事压在他手上」，即便任务都没设 deadline
 *    投影也会退化为水平线，至少不会让未来段一片空白。
 * 3) 底部状态行：流速同比 / 流转 vs 团队均值 / 停滞文案
 *
 * 注：原 WIP 健康度（基于固定阈值的饱和度）已下线——单一阈值套不同岗位
 * 假阳性过高，改由「逾期 / 即将到期 / 停滞」等业务事件驱动告警。
 */
interface Props {
    workload: MemberWorkloadItem;
    memberName?: string;
}

const props = withDefaults(defineProps<Props>(), {
    memberName: "",
});

const emit = defineEmits<{
    /** 用户点击「发送通知」按钮，由父组件弹出对话框（避免 popover 自动收起影响弹窗生命周期） */
    "send-notify": [];
}>();

function onSendNotifyClick(e: MouseEvent) {
    // 阻止冒泡到外层卡片，否则会触发卡片选中
    e.stopPropagation();
    emit("send-notify");
}

const completedRecent = computed(() => props.workload.completed_recent || 0);
const completedPrev = computed(() => props.workload.completed_prev || 0);
const completedDelta = computed(() => completedRecent.value - completedPrev.value);

const completedDeltaTag = computed<{
    text: string;
    cls: "up" | "down" | "flat";
} | null>(() => {
    if (completedPrev.value === 0 && completedRecent.value === 0) return null;
    const d = completedDelta.value;
    if (d === 0) return { text: "持平", cls: "flat" };
    if (d > 0) return { text: `+${d}`, cls: "up" };
    return { text: `${d}`, cls: "down" };
});

const personalLead = computed(() => Number(props.workload.avg_lead_time_days || 0));
const teamLead = computed(() => Number(props.workload.team_avg_lead_time_days || 0));

const leadCompareTag = computed<{
    text: string;
    cls: "fast" | "slow" | "same";
} | null>(() => {
    if (personalLead.value <= 0 || teamLead.value <= 0) return null;
    const ratio = personalLead.value / teamLead.value;
    if (ratio < 0.85) return { text: "比团队快", cls: "fast" };
    if (ratio > 1.15) return { text: "比团队慢", cls: "slow" };
    return { text: "与团队持平", cls: "same" };
});

const staleCount = computed(() => props.workload.stale_count || 0);
const overdueCount = computed(() => props.workload.overdue || 0);
const dueSoonCount = computed(() => props.workload.due_soon || 0);
const pendingTotal = computed(() => props.workload.pending_total || 0);

const dailyCompleted = computed(() => props.workload.daily_completed || []);
const dailyCreated = computed(() => props.workload.daily_created || []);
const pendingHistory = computed(() => props.workload.pending_history_7d || []);
const activityArr = computed(() => props.workload.activity_7d || []);
const futureDue = computed(() => props.workload.future_due || []);
const futureOverdueCum = computed(() => props.workload.future_overdue_cumulative || []);

/** 是否拿到了图表所需的数据 */
const chartReady = computed(() => {
    return pendingHistory.value.length > 0 && futureDue.value.length > 0;
});

/** 把数字简洁化展示，避免 0 看起来像缺数据 */
function fmt(n: number): string {
    return String(n);
}
</script>

<template>
    <div class="vw-mc-tooltip" role="tooltip">
        <div v-if="memberName" class="vw-mc-tooltip-head">
            <span class="vw-mc-tooltip-name">{{ memberName }}</span>
            <span class="vw-mc-tooltip-sub">健康仪表盘 · 过去 7 / 未来 7 天</span>
        </div>

        <!-- KPI 4 宫格 -->
        <div class="vw-mc-kpi-grid">
            <div class="vw-mc-kpi">
                <div class="vw-mc-kpi-label">在手</div>
                <div class="vw-mc-kpi-value">{{ fmt(pendingTotal) }}</div>
            </div>
            <div class="vw-mc-kpi">
                <div class="vw-mc-kpi-label">7d 完成</div>
                <div class="vw-mc-kpi-value">
                    {{ fmt(completedRecent) }}
                    <span
                        v-if="completedDeltaTag"
                        class="vw-mc-kpi-delta"
                        :class="`tone-${completedDeltaTag.cls}`"
                    >{{ completedDeltaTag.text }}</span>
                </div>
            </div>
            <div class="vw-mc-kpi">
                <div class="vw-mc-kpi-label">平均流转</div>
                <div class="vw-mc-kpi-value">
                    <template v-if="personalLead > 0">
                        {{ personalLead }}<span class="vw-mc-kpi-unit">d</span>
                    </template>
                    <template v-else>
                        <span class="vw-mc-kpi-empty">—</span>
                    </template>
                </div>
            </div>
            <div class="vw-mc-kpi" :class="{ 'is-warn': staleCount > 0 }">
                <div class="vw-mc-kpi-label">停滞</div>
                <div class="vw-mc-kpi-value">{{ fmt(staleCount) }}</div>
            </div>
        </div>

        <!-- 时间轴图表 -->
        <div v-if="chartReady" class="vw-mc-chart-wrap">
            <WorkloadTimelineChart
                :daily-completed="dailyCompleted"
                :daily-created="dailyCreated"
                :activity="activityArr"
                :pending-history="pendingHistory"
                :future-due="futureDue"
                :future-overdue-cum="futureOverdueCum"
                :current-overdue="overdueCount"
                :pending-total="pendingTotal"
                :height="200"
            />
        </div>
        <div v-else class="vw-mc-faint vw-mc-chart-empty">
            正在加载工作量数据...
        </div>

        <!-- 状态行：把流速 / 流转 / 风险 重要文案集中放底部 -->
        <div class="vw-mc-meta">
            <div v-if="completedDeltaTag" class="vw-mc-meta-row">
                <TrendingUp :size="11" class="vw-mc-meta-icon" />
                <span class="vw-mc-meta-text">
                    流速 <strong>{{ completedRecent }}</strong> 件 / 周
                    <span class="vw-mc-tag" :class="`tone-${completedDeltaTag.cls}`">同比 {{ completedDeltaTag.text }}</span>
                </span>
            </div>

            <div v-if="leadCompareTag" class="vw-mc-meta-row">
                <Activity :size="11" class="vw-mc-meta-icon" />
                <span class="vw-mc-meta-text">
                    流转 <strong>{{ personalLead }}</strong> 天
                    <span class="vw-mc-faint">（团队均值 {{ teamLead }}）</span>
                    <span
                        class="vw-mc-tag"
                        :class="`tone-${leadCompareTag.cls === 'fast' ? 'up' : leadCompareTag.cls === 'slow' ? 'down' : 'flat'}`"
                    >{{ leadCompareTag.text }}</span>
                </span>
            </div>

            <div v-if="overdueCount > 0 || staleCount > 0 || dueSoonCount > 0" class="vw-mc-meta-row">
                <AlertTriangle :size="11" class="vw-mc-meta-icon vw-mc-meta-icon-danger" />
                <span class="vw-mc-meta-text">
                    <span v-if="overdueCount > 0" class="vw-mc-risk danger">
                        逾期 {{ overdueCount }}
                    </span>
                    <span v-if="dueSoonCount > 0" class="vw-mc-risk warn">
                        即将到期 {{ dueSoonCount }}
                    </span>
                    <span v-if="staleCount > 0" class="vw-mc-risk stale">
                        <Pause :size="10" />
                        停滞 {{ staleCount }}
                    </span>
                </span>
            </div>

            <div v-else-if="completedRecent > 0 && overdueCount === 0 && staleCount === 0" class="vw-mc-meta-row vw-mc-good">
                <Activity :size="11" class="vw-mc-meta-icon" />
                <span class="vw-mc-meta-text">无逾期 / 无停滞，状态良好</span>
            </div>
        </div>

        <!--
            底部操作栏：当前只有「发送通知」一个动作。复用工作项里的通知功能，
            但场景换成"提醒成员关注他自己的在手工作量"，不绑定具体工作项。
        -->
        <div class="vw-mc-actions">
            <button
                type="button"
                class="vw-mc-notify-btn"
                title="向该成员发送一条工作量提醒/催办"
                @click="onSendNotifyClick"
                @mousedown.stop
            >
                <Send :size="12" />
                发送通知
            </button>
        </div>
    </div>
</template>

<style scoped>
.vw-mc-tooltip {
    width: 100%;
    color: #1f2937;
    font-size: 12px;
    line-height: 1.6;
}

.vw-mc-tooltip-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding-bottom: 6px;
    margin-bottom: 8px;
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}
.vw-mc-tooltip-name {
    font-weight: 600;
    color: #1f2937;
    font-size: 13px;
}
.vw-mc-tooltip-sub {
    font-size: 10px;
    color: #9ca3af;
    letter-spacing: 0.04em;
}

/* ===== KPI 宫格 ===== */
.vw-mc-kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    margin-bottom: 8px;
}
.vw-mc-kpi {
    background: rgba(15, 23, 42, 0.03);
    border-radius: 6px;
    padding: 6px 8px;
    line-height: 1.2;
}
.vw-mc-kpi.is-warn {
    background: rgba(239, 68, 68, 0.06);
}
.vw-mc-kpi-label {
    font-size: 10px;
    color: #9ca3af;
}
.vw-mc-kpi-value {
    margin-top: 2px;
    font-size: 16px;
    font-weight: 600;
    color: #1f2937;
    display: flex;
    align-items: baseline;
    gap: 4px;
}
.vw-mc-kpi-unit {
    font-size: 11px;
    font-weight: 400;
    color: #6b7280;
    margin-left: 1px;
}
.vw-mc-kpi-empty {
    color: #cbd5e1;
}
.vw-mc-kpi-delta {
    font-size: 10px;
    font-weight: 500;
    padding: 0 4px;
    border-radius: 3px;
    line-height: 1.5;
}
.vw-mc-kpi-delta.tone-up {
    background: rgba(34, 197, 94, 0.12);
    color: #15803d;
}
.vw-mc-kpi-delta.tone-down {
    background: rgba(239, 68, 68, 0.12);
    color: #b91c1c;
}
.vw-mc-kpi-delta.tone-flat {
    background: rgba(107, 114, 128, 0.12);
    color: #4b5563;
}

/* ===== 图表区 ===== */
.vw-mc-chart-wrap {
    margin: 4px 0 8px;
    padding: 4px 0 0;
    border-top: 1px dashed rgba(15, 23, 42, 0.06);
}
.vw-mc-chart-empty {
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 6px 0 8px;
    border: 1px dashed rgba(15, 23, 42, 0.08);
    border-radius: 6px;
}

/* ===== 底部 meta ===== */
.vw-mc-meta {
    border-top: 1px dashed rgba(15, 23, 42, 0.06);
    padding-top: 6px;
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.vw-mc-meta-row {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    font-size: 11px;
    color: #4b5563;
    line-height: 1.6;
}
.vw-mc-meta-icon {
    color: #9ca3af;
    margin-top: 2px;
    flex-shrink: 0;
}
.vw-mc-meta-icon-danger {
    color: #ef4444;
}
.vw-mc-meta-text {
    flex: 1;
    min-width: 0;
    display: inline-flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
}
.vw-mc-meta-text strong {
    color: #1f2937;
    font-weight: 600;
}
.vw-mc-good {
    color: #16a34a;
}
.vw-mc-good .vw-mc-meta-icon {
    color: #16a34a;
}

.vw-mc-faint {
    color: #9ca3af;
    font-size: 11px;
}

.vw-mc-tag {
    display: inline-flex;
    align-items: center;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 10px;
    line-height: 1.6;
    font-weight: 500;
    margin-left: 2px;
}
.vw-mc-tag.tone-up {
    background: rgba(34, 197, 94, 0.12);
    color: #15803d;
}
.vw-mc-tag.tone-down {
    background: rgba(239, 68, 68, 0.12);
    color: #b91c1c;
}
.vw-mc-tag.tone-flat {
    background: rgba(107, 114, 128, 0.12);
    color: #4b5563;
}

.vw-mc-risk {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 500;
}
.vw-mc-risk.danger {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
}
.vw-mc-risk.warn {
    background: rgba(245, 158, 11, 0.1);
    color: #b45309;
}
.vw-mc-risk.stale {
    background: rgba(107, 114, 128, 0.12);
    color: #4b5563;
}

/* ===== 操作区 ===== */
.vw-mc-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed rgba(15, 23, 42, 0.06);
}

.vw-mc-notify-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid var(--vort-primary, #1456f0);
    background: #fff;
    color: var(--vort-primary, #1456f0);
    font-size: 12px;
    font-weight: 500;
    line-height: 1.6;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
}
.vw-mc-notify-btn:hover {
    background: var(--vort-primary, #1456f0);
    color: #fff;
}
</style>

<!--
  非 scoped 样式：覆盖 vort-popover 默认 max-width: 320px，让健康仪表盘有足够横向空间放
  时间轴图表（14 天 = 历史 7 + 今 + 未来 7，需要 ≥ 500px 才舒展）
-->
<style>
.vort-popover.vw-mc-tooltip-overlay {
    max-width: 560px !important;
    width: 560px;
    padding: 14px !important;
}

@media (max-width: 768px) {
    .vort-popover.vw-mc-tooltip-overlay {
        max-width: 92vw !important;
        width: 92vw;
    }
}
</style>
