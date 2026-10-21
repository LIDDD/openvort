<script setup lang="ts">
import { computed } from "vue";
import { Pencil } from "lucide-vue-next";
import PopoverSelect from "@/components/vort-biz/popover-select/PopoverSelect.vue";

interface TagPickerOption {
    label: string;
    value: string;
    color?: string;
}

interface Props {
    modelValue?: string[];
    options?: Array<string | TagPickerOption>;
    disabled?: boolean;
    placeholder?: string;
    searchPlaceholder?: string;
    dropdownWidth?: number | string;
    dropdownMaxHeight?: number;
    bordered?: boolean;
    maxVisibleTags?: number;
    getTagColor?: (tag: string) => string;
    /** Show inline "edit" action on each row; emits edit-tag event on click. */
    enableEdit?: boolean;
    editTitle?: string;
}

const props = withDefaults(defineProps<Props>(), {
    modelValue: () => [],
    options: () => [],
    disabled: false,
    placeholder: "选择标签",
    searchPlaceholder: "搜索标签...",
    dropdownWidth: 240,
    dropdownMaxHeight: 220,
    bordered: true,
    maxVisibleTags: 3,
    getTagColor: undefined,
    enableEdit: false,
    editTitle: "编辑标签",
});

const emit = defineEmits<{
    "update:modelValue": [value: string[]];
    change: [value: string[]];
    "edit-tag": [option: TagPickerOption];
}>();

const open = defineModel<boolean>("open", { default: false });
const keyword = defineModel<string>("keyword", { default: "" });

const normalizedOptions = computed<TagPickerOption[]>(() => {
    return props.options.map((option) => {
        if (typeof option === "string") {
            return {
                label: option,
                value: option
            };
        }
        return option;
    });
});

const filteredOptions = computed(() => {
    const kw = keyword.value.trim().toLowerCase();
    if (!kw) return normalizedOptions.value;
    return normalizedOptions.value.filter((option) => {
        return option.label.toLowerCase().includes(kw) || option.value.toLowerCase().includes(kw);
    });
});

const selectedValues = computed(() => props.modelValue || []);

const selectedOptions = computed(() => {
    return normalizedOptions.value.filter((option) => selectedValues.value.includes(option.value));
});

const visibleOptions = computed(() => selectedOptions.value.slice(0, props.maxVisibleTags));
const hiddenCount = computed(() => Math.max(0, selectedOptions.value.length - visibleOptions.value.length));

const fallbackColor = "#3b82f6";

const getColor = (tag: string) => {
    const matched = normalizedOptions.value.find((option) => option.value === tag);
    if (matched?.color) return matched.color;
    return props.getTagColor?.(tag) || fallbackColor;
};

const toggleOption = (tag: string) => {
    const next = [...selectedValues.value];
    const index = next.indexOf(tag);
    if (index >= 0) {
        next.splice(index, 1);
    } else {
        next.push(tag);
    }
    emit("update:modelValue", next);
    emit("change", next);
};

const handleEditClick = (option: TagPickerOption) => {
    emit("edit-tag", option);
};
</script>

<template>
    <PopoverSelect
        v-model:open="open"
        v-model:keyword="keyword"
        :disabled="disabled"
        :placeholder="placeholder"
        :search-placeholder="searchPlaceholder"
        :show-search="true"
        :dropdown-width="dropdownWidth"
        :dropdown-max-height="dropdownMaxHeight"
        :bordered="bordered"
    >
        <template #trigger="{ open: triggerOpen }">
            <slot
                name="trigger"
                :open="triggerOpen"
                :selected-values="selectedValues"
                :selected-options="selectedOptions"
                :visible-options="visibleOptions"
                :hidden-count="hiddenCount"
            >
                <button type="button" class="tag-picker-default-trigger" :disabled="disabled">
                    <div class="tag-picker-trigger-chips">
                        <template v-if="visibleOptions.length > 0">
                            <span
                                v-for="option in visibleOptions"
                                :key="option.value"
                                class="tag-picker-trigger-chip"
                                :style="{ backgroundColor: getColor(option.value) }"
                            >
                                {{ option.label }}
                            </span>
                            <span v-if="hiddenCount > 0" class="tag-picker-trigger-more">
                                +{{ hiddenCount }}
                            </span>
                        </template>
                        <span v-else class="tag-picker-trigger-placeholder">{{ placeholder }}</span>
                    </div>
                </button>
            </slot>
        </template>

        <div class="tag-picker-content">
            <div
                v-for="option in filteredOptions"
                :key="option.value"
                class="tag-picker-row"
                :class="{ 'is-active': selectedValues.includes(option.value) }"
                @click.stop="toggleOption(option.value)"
            >
                <div class="tag-picker-row-left">
                    <vort-checkbox
                        :checked="selectedValues.includes(option.value)"
                        @click.stop
                        @update:checked="toggleOption(option.value)"
                    />
                    <span
                        class="tag-picker-color-dot"
                        :style="{ backgroundColor: getColor(option.value) }"
                    />
                    <span class="tag-picker-name">{{ option.label }}</span>
                </div>
                <button
                    v-if="enableEdit"
                    type="button"
                    class="tag-picker-edit-btn"
                    :title="editTitle"
                    @click.stop="handleEditClick(option)"
                >
                    <Pencil :size="14" />
                </button>
            </div>
        </div>

        <template v-if="$slots.footer" #footer>
            <slot name="footer" />
        </template>
    </PopoverSelect>
</template>

<style scoped>
.tag-picker-default-trigger {
    width: 100%;
    text-align: left;
}

.tag-picker-trigger-chips {
    display: flex;
    align-items: center;
    gap: 4px;
    overflow: hidden;
    white-space: nowrap;
}

.tag-picker-trigger-chip {
    display: inline-flex;
    align-items: center;
    max-width: 120px;
    padding: 2px 6px;
    border-radius: 4px;
    color: #fff;
    font-size: 12px;
    line-height: 16px;
    overflow: hidden;
    text-overflow: ellipsis;
}

.tag-picker-trigger-more {
    color: #94a3b8;
    font-size: 12px;
    line-height: 16px;
    font-weight: 500;
}

.tag-picker-trigger-placeholder {
    color: var(--vort-text-quaternary, rgba(0, 0, 0, 0.45));
}

.tag-picker-content {
    padding: 0px 4px 8px;
}

.tag-picker-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-height: 32px;
    padding: 2px 8px;
    border-radius: 6px;
    cursor: pointer;
    transition: background-color 0.15s ease;
}

.tag-picker-row:hover {
    background: rgba(0, 0, 0, 0.04);
}

.tag-picker-row.is-active {
    background: #f1f5f9;
}

.tag-picker-row-left {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    flex: 1;
}

.tag-picker-color-dot {
    width: 12px;
    height: 12px;
    border-radius: 9999px;
    flex-shrink: 0;
}

.tag-picker-name {
    color: #334155;
    font-size: 14px;
    line-height: 20px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tag-picker-edit-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    padding: 0;
    border: none;
    background: transparent;
    color: #94a3b8;
    border-radius: 4px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s ease, color 0.15s ease, background-color 0.15s ease;
}

.tag-picker-row:hover .tag-picker-edit-btn,
.tag-picker-edit-btn:focus-visible {
    opacity: 1;
}

.tag-picker-edit-btn:hover {
    color: var(--vort-primary, #1456f0);
    background: rgba(20, 86, 240, 0.08);
}
</style>
