<script setup lang="ts">
import { computed, ref } from "vue";

/**
 * 迷你折线 / 柱状图，专门面向卡片底部嵌入的小尺寸场景（默认 64×16）。
 * - 自动按 max(values) 归一化（min=0，避免负数情况）
 * - 全 0 时显示一条贴底直线
 * - 支持 line / area / bar 三种模式，bar 适合离散事件计数
 * - 当 mode=line/area 时可传 `secondaryValues` 叠加一条对比折线
 *   （独立归一化，不带 area），适合「在手 vs 完成」这类不同量级、
 *   只关心趋势的双线场景
 * - 鼠标悬停时高亮当前数据点（圆点 + 垂直辅助线），并通过 Teleport 在
 *   body 上显示一个 fixed tooltip 展示当天数据，避免被祖先 overflow 裁剪
 */
interface Props {
    values: number[];
    width?: number;
    height?: number;
    color?: string;
    fillColor?: string;
    mode?: "line" | "area" | "bar";
    /** 每个数据点的 hover 文案，长度应等于 values；缺省时回退到 `${value}` */
    labels?: string[];
    /**
     * 可选：第二条对比折线的数据，长度需与 `values` 一致。
     * 仅当 mode=line/area 时生效。次线独立归一化，不影响主线纵轴，
     * 让两组数量级不一致的序列都能撑满高度，专注趋势对比。
     */
    secondaryValues?: number[];
    /** 第二条折线的颜色 */
    secondaryColor?: string;
}

const props = withDefaults(defineProps<Props>(), {
    width: 64,
    height: 16,
    color: "#3b82f6",
    fillColor: "rgba(59, 130, 246, 0.15)",
    mode: "line",
    labels: () => [],
    secondaryValues: () => [],
    secondaryColor: "#10b981",
});

const geom = computed(() => {
    const vs = props.values || [];
    const n = vs.length;
    const w = props.width;
    const h = props.height;
    if (!n) {
        return {
            line: "",
            area: "",
            bars: [] as Array<{ x: number; y: number; w: number; h: number }>,
            secondaryLine: "",
            points: [] as Array<{ x: number; y: number }>,
            secondaryPoints: [] as Array<{ x: number; y: number }>,
        };
    }

    const max = Math.max(...vs, 1);
    const pad = 1;
    const innerH = h - pad * 2;

    if (props.mode === "bar") {
        const cellW = w / n;
        const barW = Math.max(2, cellW - 2);
        const bars = vs.map((v, i) => {
            const ratio = max > 0 ? v / max : 0;
            const bh = Math.max(1, ratio * innerH);
            return {
                x: i * cellW + (cellW - barW) / 2,
                y: h - bh,
                w: barW,
                h: bh,
            };
        });
        const points = bars.map((b) => ({ x: b.x + b.w / 2, y: b.y }));
        return { line: "", area: "", bars, secondaryLine: "", points, secondaryPoints: [] };
    }

    const stepX = n > 1 ? w / (n - 1) : 0;
    const coords = vs.map((v, i) => {
        const x = n === 1 ? w / 2 : i * stepX;
        const ratio = max > 0 ? v / max : 0;
        const y = pad + innerH - ratio * innerH;
        return { x, y };
    });
    const line = coords
        .map((c, i) => (i === 0 ? `M${c.x.toFixed(2)},${c.y.toFixed(2)}` : `L${c.x.toFixed(2)},${c.y.toFixed(2)}`))
        .join(" ");
    const lastX = coords[coords.length - 1]?.x ?? w;
    const area = `${line} L${lastX.toFixed(2)},${h} L${(coords[0]?.x ?? 0).toFixed(2)},${h} Z`;

    // 第二条对比折线：独立归一化，避免量级悬殊导致一条线贴底看不清趋势
    const sv = props.secondaryValues || [];
    let secondaryLine = "";
    let secondaryPoints: Array<{ x: number; y: number }> = [];
    if (sv.length === n) {
        const sMax = Math.max(...sv, 1);
        secondaryPoints = sv.map((v, i) => {
            const x = n === 1 ? w / 2 : i * stepX;
            const ratio = sMax > 0 ? v / sMax : 0;
            const y = pad + innerH - ratio * innerH;
            return { x, y };
        });
        secondaryLine = secondaryPoints
            .map((c, i) => (i === 0 ? `M${c.x.toFixed(2)},${c.y.toFixed(2)}` : `L${c.x.toFixed(2)},${c.y.toFixed(2)}`))
            .join(" ");
    }

    return { line, area, bars: [], secondaryLine, points: coords, secondaryPoints };
});

const wrapperRef = ref<HTMLElement>();
const activeIndex = ref<number>(-1);
const tooltipPos = ref<{ x: number; y: number } | null>(null);

function indexFromOffsetX(offsetX: number) {
    const n = (props.values || []).length;
    if (!n) return -1;
    const w = props.width;
    if (props.mode === "bar") {
        const cellW = w / n;
        const idx = Math.floor(offsetX / cellW);
        return Math.max(0, Math.min(n - 1, idx));
    }
    if (n === 1) return 0;
    const stepX = w / (n - 1);
    const idx = Math.round(offsetX / stepX);
    return Math.max(0, Math.min(n - 1, idx));
}

function onMove(e: MouseEvent) {
    const el = wrapperRef.value;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return;
    const localX = e.clientX - rect.left;
    const offsetX = (localX / rect.width) * props.width;
    const idx = indexFromOffsetX(offsetX);
    activeIndex.value = idx;

    const p = geom.value.points[idx];
    if (!p) {
        tooltipPos.value = null;
        return;
    }
    tooltipPos.value = {
        x: rect.left + (p.x / props.width) * rect.width,
        y: rect.top + (p.y / props.height) * rect.height,
    };
}

function onLeave() {
    activeIndex.value = -1;
    tooltipPos.value = null;
}

const activePoint = computed(() => {
    if (activeIndex.value < 0) return null;
    return geom.value.points[activeIndex.value] || null;
});

const activeSecondaryPoint = computed(() => {
    if (activeIndex.value < 0) return null;
    return geom.value.secondaryPoints[activeIndex.value] || null;
});

const activeLabel = computed(() => {
    const idx = activeIndex.value;
    if (idx < 0) return "";
    const v = props.values?.[idx] ?? 0;
    return props.labels[idx] || `${v}`;
});
</script>

<template>
    <span
        ref="wrapperRef"
        class="vw-sparkline"
        :style="{ width: `${width}px`, height: `${height}px` }"
        @mousemove="onMove"
        @mouseleave="onLeave"
    >
        <svg
            :width="width"
            :height="height"
            :viewBox="`0 0 ${width} ${height}`"
            preserveAspectRatio="none"
            role="img"
        >
            <template v-if="mode === 'bar'">
                <rect
                    v-for="(bar, i) in geom.bars"
                    :key="i"
                    :x="bar.x"
                    :y="bar.y"
                    :width="bar.w"
                    :height="bar.h"
                    :fill="color"
                    :opacity="activeIndex < 0 || activeIndex === i ? 1 : 0.5"
                    rx="0.5"
                />
            </template>
            <template v-else>
                <path
                    v-if="mode === 'area' && geom.area"
                    :d="geom.area"
                    :fill="fillColor"
                    stroke="none"
                />
                <path
                    v-if="geom.line"
                    :d="geom.line"
                    :stroke="color"
                    fill="none"
                    stroke-width="1.2"
                    stroke-linejoin="round"
                    stroke-linecap="round"
                />
                <path
                    v-if="geom.secondaryLine"
                    :d="geom.secondaryLine"
                    :stroke="secondaryColor"
                    fill="none"
                    stroke-width="1.2"
                    stroke-linejoin="round"
                    stroke-linecap="round"
                    opacity="0.95"
                />
            </template>
            <g v-if="activePoint">
                <line
                    :x1="activePoint.x"
                    :x2="activePoint.x"
                    y1="0"
                    :y2="height"
                    :stroke="color"
                    stroke-width="0.6"
                    stroke-dasharray="1.5 1.5"
                    opacity="0.5"
                />
                <circle
                    :cx="activePoint.x"
                    :cy="activePoint.y"
                    r="2.4"
                    :fill="color"
                    stroke="#fff"
                    stroke-width="1"
                />
                <circle
                    v-if="activeSecondaryPoint"
                    :cx="activeSecondaryPoint.x"
                    :cy="activeSecondaryPoint.y"
                    r="2.2"
                    :fill="secondaryColor"
                    stroke="#fff"
                    stroke-width="1"
                />
            </g>
        </svg>
    </span>
    <Teleport to="body">
        <Transition name="vw-sparkline-fade">
            <div
                v-if="tooltipPos && activeLabel"
                class="vw-sparkline-tooltip"
                :style="{
                    left: `${tooltipPos.x}px`,
                    top: `${tooltipPos.y - 10}px`,
                }"
            >
                {{ activeLabel }}
            </div>
        </Transition>
    </Teleport>
</template>

<style scoped>
.vw-sparkline {
    position: relative;
    display: inline-block;
    vertical-align: middle;
    line-height: 0;
}
.vw-sparkline svg {
    display: block;
}
</style>

<style>
.vw-sparkline-tooltip {
    position: fixed;
    background: rgba(15, 23, 42, 0.92);
    color: #fff;
    font-size: 11px;
    line-height: 1.3;
    padding: 3px 8px;
    border-radius: 4px;
    white-space: nowrap;
    pointer-events: none;
    z-index: 2000;
    transform: translate(-50%, -100%);
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.18);
}
.vw-sparkline-tooltip::after {
    content: "";
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 4px solid transparent;
    border-top-color: rgba(15, 23, 42, 0.92);
}
.vw-sparkline-fade-enter-active,
.vw-sparkline-fade-leave-active {
    transition: opacity 0.12s ease;
}
.vw-sparkline-fade-enter-from,
.vw-sparkline-fade-leave-to {
    opacity: 0;
}
</style>
