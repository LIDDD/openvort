<script setup lang="ts">
import { computed } from "vue";

/**
 * 类似 GitHub 贡献图的 7 格活动热度条。每个 cell 对应一天的活动事件数。
 * - 阈值 + 颜色阶梯均可定制；默认 5 档 indigo 色阶
 * - 每个 cell 用 vort-tooltip 显示对应日期的活动数（labels 优先）
 */
interface Props {
    values: number[];
    width?: number;
    height?: number;
    /** 阈值数组（升序）。值 >= thresholds[i] 时落入第 i+1 档 */
    thresholds?: number[];
    /** 颜色阶梯，长度应为 thresholds.length + 1（含空档） */
    colors?: string[];
    /** cell 间距（像素） */
    gap?: number;
    /** 各 cell 的 hover label，长度应等于 values；缺省时回退到 `${value} 次` */
    labels?: string[];
}

const props = withDefaults(defineProps<Props>(), {
    width: 84,
    height: 12,
    thresholds: () => [1, 20, 40, 60],
    colors: () => ["#eef2ff", "#c7d2fe", "#818cf8", "#4f46e5", "#312e81"],
    gap: 2,
    labels: () => [],
});

const cells = computed(() => {
    const n = (props.values || []).length;
    if (!n) return [];
    const totalGap = props.gap * Math.max(0, n - 1);
    const cellW = Math.max(2, (props.width - totalGap) / n);
    return props.values.map((v, i) => {
        let level = 0;
        for (let t = 0; t < props.thresholds.length; t++) {
            if (v >= props.thresholds[t]) level = t + 1;
        }
        const fallback = props.colors[props.colors.length - 1];
        return {
            width: cellW,
            fill: props.colors[level] || fallback,
            title: props.labels[i] || `${v} 次`,
        };
    });
});
</script>

<template>
    <span
        class="vw-heat-strip"
        :style="{
            width: `${width}px`,
            height: `${height}px`,
            gap: `${gap}px`,
        }"
    >
        <vort-tooltip
            v-for="(c, i) in cells"
            :key="i"
            :title="c.title"
            placement="top"
        >
            <span
                class="vw-heat-cell"
                :style="{
                    width: `${c.width}px`,
                    height: `${height}px`,
                    background: c.fill,
                }"
            />
        </vort-tooltip>
    </span>
</template>

<style scoped>
.vw-heat-strip {
    display: inline-flex;
    align-items: center;
    vertical-align: middle;
    line-height: 0;
}
.vw-heat-cell {
    display: inline-block;
    border-radius: 2px;
    cursor: default;
    transition: transform 0.12s ease;
}
.vw-heat-cell:hover {
    transform: scale(1.18);
}
</style>
