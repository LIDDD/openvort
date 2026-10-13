<script setup lang="ts">
import { computed, watch } from "vue";
import PopoverSelect from "@/components/vort-biz/popover-select/PopoverSelect.vue";
import type { Priority, PriorityScore } from "./WorkItemTable.types";

interface Props {
    /** 优先级等级（向后兼容入参；建议使用 score）。 */
    modelValue?: Priority;
    /** 精排分数 0-100；同时传时以 score 为准。 */
    score?: PriorityScore;
    disabled?: boolean;
    /** 是否启用精排滑块（仅需求建议开启；任务/缺陷传 false 时只能选等级标签）。 */
    enableScoreSlider?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
    modelValue: "none",
    score: undefined,
    disabled: false,
    enableScoreSlider: true,
});

const emit = defineEmits<{
    (e: "update:modelValue", value: Priority): void;
    (e: "update:score", value: number): void;
    /** 等级变化（兼容旧用法）。 */
    (e: "change", value: Priority): void;
    /** 精排分数变化（推荐路径，参数为 0-100 整数）。 */
    (e: "change-score", value: number): void;
    (e: "click", event: MouseEvent): void;
}>();

// ============================================================================
// 优先级等级 ↔ score 映射（与 useWorkItemCommon.ts 同步，避免循环依赖）
// 80-100=urgent / 60-79=high / 40-59=medium / 20-39=low / 0-19=none
// 段起始值（默认值）：80 / 60 / 40 / 20 / 0
// ============================================================================

const PRIORITY_DEFAULTS: Record<Priority, number> = {
    urgent: 80,
    high: 60,
    medium: 40,
    low: 20,
    none: 0,
};

const PRIORITY_RANGES: Record<Priority, [number, number]> = {
    urgent: [80, 100],
    high: [60, 79],
    medium: [40, 59],
    low: [20, 39],
    none: [0, 19],
};

const scoreToLevel = (s: number): Priority => {
    if (s >= 80) return "urgent";
    if (s >= 60) return "high";
    if (s >= 40) return "medium";
    if (s >= 20) return "low";
    return "none";
};

const clamp = (n: number) => Math.max(0, Math.min(100, Math.round(n)));

const priorityOptions: Array<{ label: string; value: Priority }> = [
    { label: "紧急", value: "urgent" },
    { label: "高", value: "high" },
    { label: "中", value: "medium" },
    { label: "低", value: "low" },
    { label: "无优先级", value: "none" },
];

const priorityLabelMap: Record<Priority, string> = {
    urgent: "紧急",
    high: "高",
    medium: "中",
    low: "低",
    none: "无优先级",
};

const priorityClassMap: Record<Priority, string> = {
    urgent: "text-red-500 border-red-500 bg-red-50",
    high: "text-amber-500 border-amber-500 bg-amber-50",
    medium: "text-blue-500 border-blue-500 bg-blue-50",
    low: "text-emerald-500 border-emerald-500 bg-emerald-50",
    none: "text-gray-400 border-gray-300 bg-gray-50",
};

const open = defineModel<boolean>("open", { default: false });

// ----------------------------------------------------------------------------
// 当前 score / level：score 优先；没传 score 时取 modelValue 的段起始值。
// ----------------------------------------------------------------------------

const effectiveScore = computed<number>(() => {
    if (props.score != null && !Number.isNaN(Number(props.score))) {
        return clamp(Number(props.score));
    }
    return PRIORITY_DEFAULTS[props.modelValue] ?? 0;
});

const effectiveLevel = computed<Priority>(() => scoreToLevel(effectiveScore.value));

const isDefaultScore = computed<boolean>(
    () => effectiveScore.value === PRIORITY_DEFAULTS[effectiveLevel.value],
);

const triggerLabel = computed(() => {
    const lv = effectiveLevel.value;
    return isDefaultScore.value
        ? priorityLabelMap[lv]
        : `${priorityLabelMap[lv]} ${effectiveScore.value}`;
});

// ----------------------------------------------------------------------------
// 内部 score 由 props.score 单向驱动；emit 后由父组件回写（外部托管）。
// ----------------------------------------------------------------------------

const emitScore = (next: number) => {
    const normalized = clamp(next);
    if (normalized === effectiveScore.value) return;
    const nextLevel = scoreToLevel(normalized);
    emit("update:score", normalized);
    emit("change-score", normalized);
    if (nextLevel !== effectiveLevel.value) {
        emit("update:modelValue", nextLevel);
        emit("change", nextLevel);
    }
};

const handleSelectLevel = (lv: Priority) => {
    if (props.disabled) return;
    const target = PRIORITY_DEFAULTS[lv];
    if (target === effectiveScore.value && lv === effectiveLevel.value) {
        open.value = false;
        return;
    }
    emit("update:modelValue", lv);
    emit("change", lv);
    emitScore(target);
    // 点击等级标签后立即关闭，体验跟旧版一致
    open.value = false;
};

const handleSliderInput = (event: Event) => {
    if (props.disabled) return;
    const target = event.target as HTMLInputElement;
    const next = Number(target.value);
    if (!Number.isFinite(next)) return;
    emitScore(next);
};

const handleNumberInput = (event: Event) => {
    if (props.disabled) return;
    const target = event.target as HTMLInputElement;
    const next = Number(target.value);
    if (!Number.isFinite(next)) return;
    emitScore(next);
};

const handleStep = (delta: number) => {
    if (props.disabled) return;
    emitScore(effectiveScore.value + delta);
};

const handleTriggerClick = (event: MouseEvent) => {
    emit("click", event);
};

// 当 score 由外部更新到新等级时，确保 modelValue 也同步（兜底）。
watch(effectiveLevel, (lv) => {
    if (lv !== props.modelValue) {
        emit("update:modelValue", lv);
    }
});

// 滑块刻度颜色（用渐变标记 5 个区段）
const sliderTrackBg = "linear-gradient(to right,"
    + " #d1d5db 0%, #d1d5db 19%,"
    + " #6ee7b7 19%, #6ee7b7 39%,"
    + " #93c5fd 39%, #93c5fd 59%,"
    + " #fcd34d 59%, #fcd34d 79%,"
    + " #fca5a5 79%, #fca5a5 100%)";
</script>

<template>
    <PopoverSelect
        v-model:open="open"
        :disabled="disabled"
        placeholder="优先级"
        :show-search="false"
        :dropdown-width="enableScoreSlider ? 220 : 140"
        :dropdown-max-height="enableScoreSlider ? 320 : 220"
        :bordered="false"
    >
        <template #trigger>
            <slot>
                <div class="priority-cell-trigger" :class="{ 'is-disabled': disabled }" @click="handleTriggerClick">
                    <span class="priority-pill" :class="priorityClassMap[effectiveLevel]">
                        {{ triggerLabel }}
                    </span>
                </div>
            </slot>
        </template>

        <div class="priority-picker-content">
            <div
                v-for="opt in priorityOptions"
                :key="opt.value"
                class="priority-picker-row"
                :class="{
                    'is-active': effectiveLevel === opt.value,
                    'is-disabled': disabled,
                }"
                @click.stop="handleSelectLevel(opt.value)"
            >
                <span class="priority-pill" :class="priorityClassMap[opt.value]">
                    {{ opt.label }}
                </span>
                <span v-if="effectiveLevel === opt.value && !isDefaultScore" class="priority-row-score">
                    {{ effectiveScore }}
                </span>
            </div>

            <div v-if="enableScoreSlider" class="priority-slider-wrap">
                <div class="priority-slider-row">
                    <input
                        type="range"
                        min="0"
                        max="100"
                        step="1"
                        class="priority-slider"
                        :style="{ background: sliderTrackBg }"
                        :value="effectiveScore"
                        :disabled="disabled"
                        @input="handleSliderInput"
                        @click.stop
                    />
                </div>
                <div class="priority-slider-controls">
                    <button
                        type="button"
                        class="priority-step-btn"
                        :disabled="disabled || effectiveScore <= 0"
                        @click.stop="handleStep(-1)"
                    >
                        −
                    </button>
                    <input
                        type="number"
                        min="0"
                        max="100"
                        class="priority-score-input"
                        :value="effectiveScore"
                        :disabled="disabled"
                        @change="handleNumberInput"
                        @click.stop
                    />
                    <button
                        type="button"
                        class="priority-step-btn"
                        :disabled="disabled || effectiveScore >= 100"
                        @click.stop="handleStep(1)"
                    >
                        +
                    </button>
                </div>
                <div class="priority-slider-tip">数字越大越优先；同等级内可精排</div>
            </div>
        </div>
    </PopoverSelect>
</template>

<style scoped>
.priority-cell-trigger {
    padding: 2px 8px;
    cursor: pointer;
}

.priority-cell-trigger.is-disabled {
    cursor: not-allowed;
    opacity: 0.5;
}

.priority-pill {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    border: 1px solid;
    white-space: nowrap;
}

.priority-picker-content {
    padding: 4px;
}

.priority-picker-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 8px;
    border-radius: 6px;
    cursor: pointer;
    transition: background-color 0.15s ease;
}

.priority-picker-row:hover {
    background: rgba(0, 0, 0, 0.04);
}

.priority-picker-row.is-active {
    background: #eff6ff;
}

.priority-picker-row.is-disabled {
    cursor: not-allowed;
    opacity: 0.5;
}

.priority-row-score {
    font-size: 12px;
    color: #6b7280;
    font-variant-numeric: tabular-nums;
}

.priority-slider-wrap {
    margin-top: 6px;
    padding: 8px 8px 6px;
    border-top: 1px solid #f1f5f9;
}

.priority-slider-row {
    padding: 4px 0 8px;
}

.priority-slider {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 3px;
    outline: none;
    cursor: pointer;
}

.priority-slider:disabled {
    cursor: not-allowed;
    opacity: 0.6;
}

.priority-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #fff;
    border: 2px solid #2563eb;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
    cursor: pointer;
}

.priority-slider::-moz-range-thumb {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #fff;
    border: 2px solid #2563eb;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
    cursor: pointer;
}

.priority-slider-controls {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
}

.priority-step-btn {
    width: 26px;
    height: 26px;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #fff;
    color: #374151;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    user-select: none;
}

.priority-step-btn:hover:not(:disabled) {
    background: #f3f4f6;
}

.priority-step-btn:disabled {
    cursor: not-allowed;
    opacity: 0.4;
}

.priority-score-input {
    width: 56px;
    height: 26px;
    text-align: center;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
}

.priority-score-input:focus {
    outline: none;
    border-color: #2563eb;
}

.priority-slider-tip {
    margin-top: 6px;
    font-size: 11px;
    color: #9ca3af;
    text-align: center;
}
</style>
