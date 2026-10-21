<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Select } from "@openvort/vort-ui";
import { getVortflowIteration, getVortflowIterations, type VortflowIterationListParams } from "@/api/vortflow";

/**
 * 迭代选择器选项。
 *
 * 这里保留后端返回的扩展字段（例如 owner_name、start_date），
 * 让使用方在选择后仍可以继续做负责人/计划时间等派生处理。
 */
export interface IterationSelectOption {
    id: string;
    name: string;
    [key: string]: unknown;
}

interface Props {
    modelValue?: string | number | null;
    /** 是否请求 VortFlow 接口；关闭时使用 static-options。 */
    useApi?: boolean;
    projectId?: string;
    projectIds?: string[];
    staticOptions?: IterationSelectOption[];
    /** 当前值的显示名称。当前迭代不在已加载分页中时，用它保持回显。 */
    selectedLabel?: string;
    placeholder?: string;
    searchPlaceholder?: string;
    allowClear?: boolean;
    disabled?: boolean;
    bordered?: boolean;
    size?: "small" | "middle" | "large";
    listHeight?: number;
    class?: string;
}

const props = withDefaults(defineProps<Props>(), {
    modelValue: undefined,
    useApi: true,
    projectId: "",
    projectIds: () => [],
    staticOptions: () => [],
    selectedLabel: "",
    placeholder: "选择迭代",
    searchPlaceholder: "搜索迭代名称或编号",
    allowClear: false,
    disabled: false,
    bordered: true,
    size: "middle",
    listHeight: 256,
    class: "",
});

const emit = defineEmits<{
    "update:modelValue": [value: string | number | undefined];
    change: [value: string | number | undefined, option: any];
    focus: [event: FocusEvent];
    blur: [event: FocusEvent];
    /** 每次分页成功后把已加载的完整选项同步给父组件。 */
    "options-change": [options: IterationSelectOption[]];
}>();

const PAGE_SIZE = 100;
let instanceSeed = 0;
const instanceId = ++instanceSeed;

const loadedOptions = ref<IterationSelectOption[]>([]);
// 当前值可能不在已加载的分页中；单条详情返回后暂存它，保证搜索/分页缓存
// 重置时仍能稳定显示名称。
const selectedDetailOption = ref<IterationSelectOption | null>(null);
const selectedDetailKey = ref("");
const loading = ref(false);
const loaded = ref(false);
const loadError = ref(false);
const currentPage = ref(0);
const total = ref<number | undefined>(undefined);
const lastPageSize = ref(0);
const keyword = ref("");
let requestSequence = 0;
let pendingRequestKey: string | null = null;
let selectedDetailRequestKey: string | null = null;
let selectedDetailRequestSequence = 0;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
let blurResetTimer: ReturnType<typeof setTimeout> | null = null;

const filterKey = computed(() => {
    const ids = (props.projectIds || []).filter(Boolean);
    return `${ids.join(",")}|${props.projectId || ""}`;
});

const popupClass = `vort-iteration-select-popup-${instanceId}`;

const requestContextKey = computed(() => `${filterKey.value}|${keyword.value}`);

const selectedValueKey = computed(() => {
    const id = String(props.modelValue ?? "").trim();
    return `${filterKey.value}|${id}`;
});

const parseTotal = (value: unknown): number | undefined => {
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) return value;
    if (typeof value === "string" && value.trim()) {
        const parsed = Number(value);
        if (Number.isFinite(parsed) && parsed >= 0) return parsed;
    }
    return undefined;
};

const buildParams = (): Omit<VortflowIterationListParams, "page" | "page_size"> => {
    const ids = (props.projectIds || []).filter(Boolean);
    const params: Omit<VortflowIterationListParams, "page" | "page_size"> = {};
    if (ids.length) params.project_ids = ids.join(",");
    else if (props.projectId) params.project_id = props.projectId;
    if (keyword.value.trim()) params.keyword = keyword.value.trim();
    return params;
};

const hasMore = computed(() => {
    if (!props.useApi || !loaded.value) return false;
    if (total.value !== undefined) return loadedOptions.value.length < total.value;
    return lastPageSize.value >= PAGE_SIZE;
});

const visibleOptions = computed<IterationSelectOption[]>(() => {
    const options = [...loadedOptions.value];
    const selectedId = String(props.modelValue ?? "").trim();
    const selectedDetail = selectedDetailKey.value === selectedValueKey.value
        ? selectedDetailOption.value
        : null;
    if (selectedDetail && selectedDetail.id === selectedId) {
        const existingIndex = options.findIndex((item) => String(item.id) === selectedId);
        if (existingIndex >= 0) {
            options[existingIndex] = { ...options[existingIndex], ...selectedDetail };
        } else {
            options.unshift(selectedDetail);
        }
    }
    const selectedName = String(props.selectedLabel || "").trim() || selectedDetail?.name || "";
    if (selectedId && selectedId !== "__unplanned__" && !options.some((item) => String(item.id) === selectedId)) {
        options.unshift({ id: selectedId, name: selectedName || selectedId });
    }
    return options;
});

const selectOptions = computed(() => visibleOptions.value.map((item) => ({
    value: item.id,
    label: item.name,
})));

const staticSelectOptions = computed(() => {
    const options = [...(props.staticOptions || [])];
    const selectedId = String(props.modelValue ?? "").trim();
    const selectedName = String(props.selectedLabel || "").trim();
    if (selectedId && selectedId !== "__unplanned__" && !options.some((item) => String(item.id) === selectedId)) {
        options.unshift({ id: selectedId, name: selectedName || selectedId });
    }
    return options.map((item) => ({ value: item.id, label: item.name }));
});

const optionsForSelect = computed(() => props.useApi ? selectOptions.value : staticSelectOptions.value);

const normalizeDetailOption = (response: any, requestedId: string): IterationSelectOption | null => {
    // request.ts 已经解包 response.data；保留对常见包裹形态的兼容，便于渐进升级。
    const item = response?.item || response?.data || response;
    const id = String(item?.id || requestedId || "").trim();
    const name = String(item?.name || "").trim();
    if (!id || !name || id !== requestedId) return null;
    return {
        ...item,
        id,
        name,
    };
};

const mergeSelectedDetailOption = (item: IterationSelectOption) => {
    const index = loadedOptions.value.findIndex((option) => String(option.id) === item.id);
    if (index >= 0) {
        loadedOptions.value[index] = { ...loadedOptions.value[index], ...item };
    } else {
        loadedOptions.value.unshift(item);
    }
    emit("options-change", loadedOptions.value);
};

const loadSelectedIteration = async () => {
    const selectedId = String(props.modelValue ?? "").trim();
    const key = `${filterKey.value}|${selectedId}`;
    if (!props.useApi || props.disabled || !selectedId || selectedId === "__unplanned__") {
        if (!selectedId || selectedId === "__unplanned__") {
            selectedDetailOption.value = null;
            selectedDetailKey.value = "";
        }
        return;
    }

    // 值变化或项目范围变化后，旧详情不能继续参与回显。
    if (selectedDetailKey.value !== key) {
        selectedDetailOption.value = null;
        selectedDetailKey.value = "";
    }

    const loadedOption = loadedOptions.value.find((item) => String(item.id) === selectedId);
    const loadedName = String(loadedOption?.name || "").trim();
    const selectedLabel = String(props.selectedLabel || "").trim();
    if ((loadedName && loadedName !== selectedId) || (selectedLabel && selectedLabel !== selectedId)) {
        // 父层可能已经提供了名称（例如从表格行数据回显），无需额外请求。
        if (!loadedOption && selectedLabel && selectedLabel !== selectedId) {
            selectedDetailOption.value = { id: selectedId, name: selectedLabel };
            selectedDetailKey.value = key;
        } else if (loadedOption) {
            selectedDetailOption.value = loadedOption;
            selectedDetailKey.value = key;
        }
        return;
    }

    if (selectedDetailKey.value === key && selectedDetailOption.value?.name && selectedDetailOption.value.name !== selectedId) {
        return;
    }
    if (selectedDetailRequestKey === key) return;

    selectedDetailRequestKey = key;
    const sequence = ++selectedDetailRequestSequence;
    try {
        const response = await getVortflowIteration(selectedId);
        if (sequence !== selectedDetailRequestSequence || key !== selectedValueKey.value) return;
        const item = normalizeDetailOption(response, selectedId);
        if (!item) return;
        selectedDetailOption.value = item;
        selectedDetailKey.value = key;
        mergeSelectedDetailOption(item);
    } catch {
        // 详情补齐失败时保留 ID 兜底，用户仍可打开下拉后重试/手动选择。
    } finally {
        if (selectedDetailRequestKey === key) selectedDetailRequestKey = null;
    }
};

const resetLoadedOptions = () => {
    requestSequence += 1;
    pendingRequestKey = null;
    if (searchTimer) {
        clearTimeout(searchTimer);
        searchTimer = null;
    }
    loadedOptions.value = [];
    loading.value = false;
    loaded.value = false;
    loadError.value = false;
    currentPage.value = 0;
    total.value = undefined;
    lastPageSize.value = 0;
    keyword.value = "";
};

const mergeOptions = (items: IterationSelectOption[], replace: boolean) => {
    const source = replace ? items : [...loadedOptions.value, ...items];
    const seen = new Set<string>();
    loadedOptions.value = source.filter((item) => {
        if (!item.id || seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
    });
    emit("options-change", loadedOptions.value);
};

const loadPage = async (reset = false) => {
    if (!props.useApi || props.disabled) return;
    // 同一查询上下文不重复发请求；搜索/重置请求允许打断上一页，
    // 旧响应会通过 sequence + context 校验被丢弃。
    if (loading.value && !reset) return;
    if (!reset && !hasMore.value) return;

    const requestKey = requestContextKey.value;
    if (loading.value && pendingRequestKey === requestKey) return;
    const sequence = ++requestSequence;
    const page = reset ? 1 : currentPage.value + 1;
    if (reset) {
        loadedOptions.value = [];
        currentPage.value = 0;
        total.value = undefined;
        lastPageSize.value = 0;
    }
    loading.value = true;
    pendingRequestKey = requestKey;
    loadError.value = false;
    try {
        const response: any = await getVortflowIterations({
            ...buildParams(),
            page,
            page_size: PAGE_SIZE,
        });
        // 项目或搜索词在请求过程中发生变化时，丢弃旧响应，避免分页串页。
        if (sequence !== requestSequence || requestKey !== requestContextKey.value) return;
        const items = (Array.isArray(response?.items) ? response.items : [])
            .map((item: any) => ({
                ...item,
                id: String(item?.id || ""),
                name: String(item?.name || item?.id || ""),
            }))
            .filter((item: IterationSelectOption) => item.id && item.name);
        mergeOptions(items, reset);
        currentPage.value = page;
        lastPageSize.value = items.length;
        total.value = parseTotal(response?.total);
        loaded.value = true;
    } catch {
        if (sequence === requestSequence && requestKey === requestContextKey.value) {
            loadError.value = true;
            loaded.value = true;
        }
    } finally {
        if (sequence === requestSequence && requestKey === requestContextKey.value) {
            loading.value = false;
            pendingRequestKey = null;
        }
    }
};

const handleSearch = (value: string) => {
    keyword.value = String(value ?? "");
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        // 搜索是明确的用户动作，只重置到匹配结果的第一页。
        void loadPage(true);
    }, 220);
};

let viewport: HTMLElement | null = null;
let bindTimer: ReturnType<typeof setTimeout> | null = null;
let bindAttempts = 0;

const unbindViewport = () => {
    if (viewport) viewport.removeEventListener("scroll", handleViewportScroll);
    viewport = null;
};

const bindViewport = () => {
    bindTimer = null;
    const root = document.querySelector(`.${popupClass}`);
    const nextViewport = root?.querySelector<HTMLElement>(".vort-select-dropdown-viewport") || null;
    if (!nextViewport) {
        if (bindAttempts < 8) {
            bindAttempts += 1;
            bindTimer = setTimeout(bindViewport, 50);
        }
        return;
    }
    unbindViewport();
    viewport = nextViewport;
    viewport.addEventListener("scroll", handleViewportScroll, { passive: true });
};

const scheduleViewportBinding = () => {
    if (typeof document === "undefined") return;
    if (bindTimer) clearTimeout(bindTimer);
    bindAttempts = 0;
    void nextTick(() => {
        bindTimer = setTimeout(bindViewport, 0);
    });
};

const handleViewportScroll = (event: Event) => {
    const target = event.currentTarget as HTMLElement | null;
    if (!target || target.scrollHeight - target.scrollTop - target.clientHeight > 32) return;
    void loadPage(false);
};

const handleUserOpen = () => {
    if (!props.useApi) return;
    // 当前值的名称独立于分页列表补齐；打开下拉时再次触发可覆盖首次请求失败。
    void loadSelectedIteration();
    // 某些非可聚焦的外部元素只会让 VortSelect 关闭弹层而不触发 blur；
    // 下一次用户重新点开时兜底清理上一次的服务端搜索结果。
    if (keyword.value && typeof document !== "undefined") {
        const popup = document.querySelector(`.${popupClass}`);
        if (popup?.getAttribute("data-state") !== "open") resetLoadedOptions();
    }
    // 首次打开或上次请求失败时，均由本次用户打开动作重新拉取第一页。
    if (!loaded.value || loadError.value) void loadPage(true);
    scheduleViewportBinding();
};

const handleFocus = (event: FocusEvent) => {
    handleUserOpen();
    emit("focus", event);
};

const handleBlur = (event: FocusEvent) => {
    // 下拉由组件内部托管，失焦时仅解除旧 DOM 监听，下一次 mousedown 会重新绑定。
    unbindViewport();
    // VortSelect 没有暴露 open-change；若用户搜索后直接点到下拉外，组件内部
    // 会清空搜索框但不会通知父层。延迟一帧确认弹层已关闭，再丢弃旧搜索结果，
    // 避免下次打开时把上一次的过滤结果误当成完整首屏。
    if (keyword.value) {
        if (blurResetTimer) clearTimeout(blurResetTimer);
        blurResetTimer = setTimeout(() => {
            blurResetTimer = null;
            if (typeof document === "undefined") return;
            const popup = document.querySelector(`.${popupClass}`);
            if (popup?.getAttribute("data-state") !== "open") resetLoadedOptions();
        }, 0);
    }
    emit("blur", event);
};

const handleChange = (value: any, option: any) => {
    // 先把选中事件交给父组件，再清理搜索结果。父组件可能需要从已加载
    // 选项中读取 start_date/end_date（缺陷计划时间联动）；若先清理，
    // 通过关键词选中的迭代会在事件处理前丢失日期元数据。
    if (keyword.value && searchTimer) {
        clearTimeout(searchTimer);
        searchTimer = null;
    }
    emit("change", value, option);
    if (keyword.value) {
        resetLoadedOptions();
    }
};

const handleModelValueUpdate = (value: any) => {
    const nextId = String(value ?? "").trim();
    if (nextId !== String(props.modelValue ?? "").trim()) {
        selectedDetailOption.value = null;
        selectedDetailKey.value = "";
    }
    emit("update:modelValue", value);
};

watch(filterKey, () => {
    // 项目筛选变化后不在后台请求；等用户再次打开迭代下拉时才请求新范围。
    resetLoadedOptions();
    selectedDetailOption.value = null;
    selectedDetailKey.value = "";
    void loadSelectedIteration();
});

watch(
    [() => props.modelValue, () => props.selectedLabel, () => props.useApi, () => props.disabled],
    () => void loadSelectedIteration(),
);

onMounted(() => {
    void loadSelectedIteration();
});

onBeforeUnmount(() => {
    // 抽屉/行被销毁时让未完成请求失效，避免响应回写已离开的页面。
    requestSequence += 1;
    selectedDetailRequestSequence += 1;
    pendingRequestKey = null;
    selectedDetailRequestKey = null;
    unbindViewport();
    if (bindTimer) clearTimeout(bindTimer);
    if (searchTimer) clearTimeout(searchTimer);
    if (blurResetTimer) clearTimeout(blurResetTimer);
});
</script>

<template>
    <div class="vort-iteration-select" @mousedown.capture="handleUserOpen">
        <Select
            :model-value="props.modelValue ?? undefined"
            :options="optionsForSelect"
            :placeholder="props.placeholder"
            :search-placeholder="props.searchPlaceholder"
            :show-search="props.useApi"
            :filter-option="false"
            :not-found-content="loading ? '加载中…' : (loadError ? '加载失败，请重新打开下拉重试' : '暂无匹配迭代')"
            :allow-clear="props.allowClear"
            :disabled="props.disabled"
            :bordered="props.bordered"
            :size="props.size"
            :list-height="props.listHeight"
            :popup-class="popupClass"
            :class="props.class"
            @update:model-value="handleModelValueUpdate"
            @change="handleChange"
            @focus="handleFocus"
            @blur="handleBlur"
            @search="handleSearch"
        >
        </Select>
    </div>
</template>

<style scoped>
.vort-iteration-select {
    display: contents;
}

</style>
