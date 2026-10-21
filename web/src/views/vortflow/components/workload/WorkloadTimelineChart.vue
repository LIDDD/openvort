<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
    GridComponent,
    LegendComponent,
    MarkAreaComponent,
    MarkLineComponent,
    TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
    BarChart,
    LineChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    MarkLineComponent,
    MarkAreaComponent,
    CanvasRenderer,
]);

/**
 * 成员工作量时间轴图表（hover 浮窗用）。
 *
 * 横轴：过去 N 天 + 今天 + 未来 N 天（默认 7 + 7）。
 * - 过去段（包含今天）：每日完成 + 每日新增（堆叠柱）、每日活动（小细柱），在手数折线
 * - 未来段：每日到期柱、累计逾期折线（虚线）、在手投影折线（虚线）
 *
 * 「在手投影」语义：从今天的 pendingTotal 起，假设按 deadline 依次完成，
 * 每天剩余在手 = 当前在手 - Σ future_due[0..i]。当任务普遍没设 deadline 时，
 * 投影线退化为水平线，至少能直观回答「未来还有多少事压在他手上」。
 *
 * 数据约定：
 * - 所有数组长度由父组件保证（history_days / forecast_days）
 * - 历史数组：旧 → 新；最后一项 = 今天
 * - 未来数组：明天 → 远期；不含今天
 */
interface Props {
    /** 过去 N 天每日完成数（旧→新，最后一项 = 今天） */
    dailyCompleted: number[];
    /** 过去 N 天每日新增数（旧→新） */
    dailyCreated: number[];
    /** 过去 N 天每日活动数（FlowEvent + FlowComment，旧→新） */
    activity?: number[];
    /** 过去 N 天每日在手数（旧→新，最后一项 = 当前在手） */
    pendingHistory: number[];
    /** 未来 N 天每日到期数（明天→远） */
    futureDue: number[];
    /** 未来 N 天每日累计逾期数（含当前已逾期，明天→远） */
    futureOverdueCum: number[];
    /** 当前已逾期数（折线起点） */
    currentOverdue: number;
    /** 当前在手数（用于推算未来在手投影） */
    pendingTotal: number;
    /** 渲染高度（默认 200） */
    height?: number;
}

const props = withDefaults(defineProps<Props>(), {
    activity: () => [],
    height: 200,
});

const elRef = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;

/** 把日期偏移格式化成 M-D；offset=0 表示今天 */
function fmtDay(offset: number): string {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    return `${d.getMonth() + 1}-${d.getDate()}`;
}

const option = computed(() => {
    const histN = props.pendingHistory.length;
    const fwdN = props.futureDue.length;

    // X 轴标签：过去 N 天 → 今天 → 未来 N 天
    const xLabels: string[] = [];
    for (let i = 0; i < histN; i++) {
        const offset = i - (histN - 1);
        xLabels.push(offset === 0 ? "今" : fmtDay(offset));
    }
    for (let i = 0; i < fwdN; i++) {
        xLabels.push(fmtDay(i + 1));
    }

    const completedSeries: (number | null)[] = [
        ...props.dailyCompleted.slice(0, histN),
        ...Array(fwdN).fill(null),
    ];
    const createdSeries: (number | null)[] = [
        ...props.dailyCreated.slice(0, histN),
        ...Array(fwdN).fill(null),
    ];
    const dueSeries: (number | null)[] = [
        ...Array(histN).fill(null),
        ...props.futureDue.slice(0, fwdN),
    ];
    const activityArr = props.activity || [];
    const activitySeries: (number | null)[] = [
        ...activityArr.slice(0, histN),
        ...Array(fwdN).fill(null),
    ];

    // 在手折线（实际）：过去段实线（pendingHistory），今天点 = pendingTotal
    const pendingLine: (number | null)[] = [
        ...props.pendingHistory.slice(0, histN),
        ...Array(fwdN).fill(null),
    ];

    // 在手折线（投影）：今天起按 deadline 依次完成的未来在手量。
    // 当 future_due 普遍为 0 时，退化为水平线 = pendingTotal，至少能告诉用户
    // 「这 N 个任务都还压在他手上」，而不是图上一片空白。
    const pendingProjectionLine: (number | null)[] = Array(histN + fwdN).fill(null);
    pendingProjectionLine[histN - 1] = props.pendingTotal; // 与实际段在「今天」无缝对接
    {
        let remain = props.pendingTotal;
        for (let i = 0; i < fwdN; i++) {
            remain = Math.max(0, remain - (props.futureDue[i] ?? 0));
            pendingProjectionLine[histN + i] = remain;
        }
    }

    // 累计逾期折线：起点是「今天」的当前已逾期，往后是 future_overdue_cumulative
    const overdueCumLine: (number | null)[] = [
        ...Array(histN - 1).fill(null),
        props.currentOverdue,
        ...props.futureOverdueCum.slice(0, fwdN),
    ];

    // 今天用一条 markLine 标出
    const todayIndex = histN - 1;

    return {
        animation: false,
        grid: { left: 6, right: 8, top: 16, bottom: 32, containLabel: true },
        legend: {
            bottom: 2,
            itemWidth: 10,
            itemHeight: 8,
            itemGap: 14,
            textStyle: { fontSize: 11, color: "#6b7280" },
            data: [
                { name: "完成", icon: "rect" },
                { name: "新增", icon: "rect" },
                { name: "到期", icon: "rect" },
                { name: "在手", icon: "circle" },
                { name: "累计逾期", icon: "circle" },
            ],
        },
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "shadow" },
            backgroundColor: "rgba(255,255,255,0.98)",
            borderColor: "rgba(15,23,42,0.08)",
            textStyle: { fontSize: 11, color: "#1f2937" },
            extraCssText: "box-shadow: 0 4px 12px rgba(15,23,42,0.08);",
            formatter: (params: any) => {
                if (!Array.isArray(params) || !params.length) return "";
                const idx = params[0]?.dataIndex ?? 0;
                const label = xLabels[idx] || "";
                const isToday = idx === todayIndex;
                const isFuture = idx > todayIndex;
                const tagText = isToday ? "今天" : isFuture ? "未来" : "过去";
                const lines: string[] = [];
                lines.push(
                    `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">`
                    + `<span style="font-weight:600;color:#1f2937;">${label}</span>`
                    + `<span style="font-size:10px;color:#9ca3af;background:rgba(107,114,128,0.08);padding:0 4px;border-radius:3px;">${tagText}</span>`
                    + `</div>`,
                );
                for (const p of params) {
                    const v = p.value;
                    if (v === null || v === undefined) continue;
                    // 在手·投影：仅未来段展示，且统一展示为「在手」名称（与实际段称谓一致）
                    let displayName = p.seriesName;
                    if (p.seriesName === "在手·投影") {
                        if (!isFuture) continue;
                        displayName = "在手";
                    }
                    lines.push(
                        `<div style="display:flex;align-items:center;justify-content:space-between;gap:14px;">`
                        + `<span style="display:inline-flex;align-items:center;gap:5px;color:#4b5563;">`
                        + `<i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};"></i>`
                        + `${displayName}</span>`
                        + `<span style="font-weight:600;color:#1f2937;">${v}</span>`
                        + `</div>`,
                    );
                }
                return lines.join("");
            },
        },
        xAxis: {
            type: "category",
            data: xLabels,
            axisLabel: {
                fontSize: 10,
                color: "#9ca3af",
                interval: 0,
                formatter: (val: string, idx: number) => {
                    if (idx === todayIndex) return "{today|今}";
                    return val;
                },
                rich: {
                    today: {
                        color: "#1f2937",
                        fontWeight: "bold",
                        backgroundColor: "rgba(20,86,240,0.1)",
                        padding: [2, 4, 2, 4],
                        borderRadius: 3,
                    },
                },
            },
            axisLine: { lineStyle: { color: "#e5e7eb" } },
            axisTick: { show: false },
        },
        yAxis: {
            type: "value",
            minInterval: 1,
            axisLabel: { fontSize: 10, color: "#9ca3af" },
            splitLine: { lineStyle: { color: "rgba(15,23,42,0.05)" } },
            axisLine: { show: false },
            axisTick: { show: false },
        },
        series: [
            {
                name: "完成",
                type: "bar",
                stack: "past",
                data: completedSeries,
                itemStyle: { color: "#22c55e", borderRadius: [2, 2, 0, 0] },
                barMaxWidth: 14,
                z: 4,
            },
            {
                name: "新增",
                type: "bar",
                stack: "past",
                data: createdSeries,
                itemStyle: { color: "#60a5fa", borderRadius: [2, 2, 0, 0] },
                barMaxWidth: 14,
                z: 4,
            },
            {
                name: "到期",
                type: "bar",
                data: dueSeries,
                itemStyle: { color: "#f59e0b", borderRadius: [2, 2, 0, 0] },
                barMaxWidth: 14,
                z: 4,
            },
            // 活动度作为隐藏系列，提供 tooltip 信息但不在图上画太显眼的元素
            {
                name: "活动",
                type: "bar",
                data: activitySeries,
                itemStyle: { color: "rgba(99, 102, 241, 0.18)", borderRadius: [1, 1, 0, 0] },
                barMaxWidth: 4,
                barGap: "-100%",
                z: 1,
                tooltip: { show: true },
            },
            {
                name: "在手",
                type: "line",
                data: pendingLine,
                smooth: true,
                symbol: "circle",
                symbolSize: 5,
                lineStyle: { color: "#475569", width: 1.5 },
                itemStyle: { color: "#475569" },
                z: 10,
                markLine: {
                    silent: true,
                    symbol: ["none", "none"],
                    data: [{ xAxis: todayIndex }],
                    lineStyle: { color: "#1456f0", type: "dashed", opacity: 0.4, width: 1 },
                    label: { show: false },
                },
            },
            {
                // 投影段：未来在手量（按 deadline 计划完成的衰减），与「在手」共用图例
                name: "在手·投影",
                type: "line",
                data: pendingProjectionLine,
                smooth: false,
                symbol: "circle",
                symbolSize: 4,
                lineStyle: { color: "#475569", width: 1.2, type: "dashed", opacity: 0.55 },
                itemStyle: { color: "#475569", opacity: 0.55 },
                z: 9,
            },
            {
                name: "累计逾期",
                type: "line",
                data: overdueCumLine,
                smooth: false,
                symbol: "circle",
                symbolSize: 4,
                lineStyle: { color: "#ef4444", width: 1.5, type: "dashed" },
                itemStyle: { color: "#ef4444" },
                z: 11,
            },
        ],
    };
});

function init() {
    if (!elRef.value) return;
    if (!chart) {
        chart = echarts.init(elRef.value);
        // 切换「在手」图例时联动「在手·投影」隐藏/显示，避免只剩孤零零的投影虚线
        chart.on("legendselectchanged", (params: any) => {
            if (!chart || params?.name !== "在手") return;
            const selected = !!params.selected?.["在手"];
            chart.dispatchAction({
                type: selected ? "legendSelect" : "legendUnSelect",
                name: "在手·投影",
            });
        });
    }
    chart.setOption(option.value, true);
}

let resizeObserver: ResizeObserver | null = null;

onMounted(async () => {
    await nextTick();
    init();
    if (elRef.value && typeof ResizeObserver !== "undefined") {
        resizeObserver = new ResizeObserver(() => chart?.resize());
        resizeObserver.observe(elRef.value);
    }
});

onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    resizeObserver = null;
    if (chart) {
        chart.dispose();
        chart = null;
    }
});

watch(option, () => {
    if (chart) {
        chart.setOption(option.value, true);
    } else {
        init();
    }
}, { deep: true });

defineExpose({
    resize: () => chart?.resize(),
});
</script>

<template>
    <div
        ref="elRef"
        class="vw-timeline-chart"
        :style="{ height: `${height}px` }"
    />
</template>

<style scoped>
.vw-timeline-chart {
    width: 100%;
    min-width: 480px;
}
</style>
