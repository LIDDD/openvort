<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, watchEffect } from "vue";
import dayjs from "dayjs";
import { useRoute, useRouter } from "vue-router";
import { ProTable, TableCell } from "@/components/vort-biz";
import { message, dialog, Pagination } from "@openvort/vort-ui";
import WorkItemMemberPicker from "@/components/vort-biz/work-item/WorkItemMemberPicker.vue";
import WorkItemPriority from "@/components/vort-biz/work-item/WorkItemPriority.vue";
import WorkItemStatus from "@/components/vort-biz/work-item/WorkItemStatus.vue";
import WorkItemTagPicker from "@/components/vort-biz/work-item/WorkItemTagPicker.vue";
import IterationSelect from "@/components/vort-biz/work-item/IterationSelect.vue";
import WorkItemFilters from "@/components/vort-biz/work-item/WorkItemFilters.vue";
import WorkItemDetail from "./work-item/WorkItemDetail.vue";
import WorkItemCreate from "./work-item/WorkItemCreate.vue";
import MoreActionsDropdown from "./components/MoreActionsDropdown.vue";
import BatchPropertyEditor from "./components/BatchPropertyEditor.vue";
import ImportDialog from "./components/ImportDialog.vue";
import ImportRecordDialog from "./components/ImportRecordDialog.vue";
import ColumnFilterPopover from "@/components/vort-biz/pro-table/ColumnFilterPopover.vue";
import type { ColumnFilterValue } from "@/components/vort-biz/pro-table/ColumnFilterPopover.vue";
import ViewSelector from "./components/ViewSelector.vue";
import ViewManageDialog from "./components/ViewManageDialog.vue";
import ViewCreateDialog from "./components/ViewCreateDialog.vue";
import ColumnSettingsDialog from "./components/ColumnSettingsDialog.vue";
import TagEditDialog from "./components/TagEditDialog.vue";
import { GanttTimeline, GanttDivider } from "./gantt";
import ViewModeToggle from "./gantt/ViewModeToggle.vue";
import type { GanttZoomLevel } from "./gantt";
import type { ViewMode } from "./gantt/ViewModeToggle.vue";
import { useVortFlowStore } from "@/stores";
import { useVortFlowViews } from "./composables/useVortFlowViews";
import { useWorkItemExport } from "./composables/useWorkItemExport";
import { useWorkItemColumns } from "./composables/useWorkItemColumns";
import { useWorkItemViewState } from "./composables/useWorkItemViewState";
import { useWorkItemDataSource, SORT_FIELD_MAP } from "./composables/useWorkItemDataSource";
import { useWorkItemColumnFilters } from "./composables/useWorkItemColumnFilters";
import { useWorkItemMetadata } from "./composables/useWorkItemMetadata";
import { useWorkItemCrud } from "./composables/useWorkItemCrud";
import { useWorkItemDetailPanel } from "./composables/useWorkItemDetailPanel";
import { useWorkItemFieldEditors } from "./composables/useWorkItemFieldEditors";
import { useWorkItemGantt } from "./composables/useWorkItemGantt";
import { normalizeVirtualStatusValues, useWorkItemCommon } from "./work-item/useWorkItemCommon";
import { useWorkItemInlineEdit } from "./work-item/useWorkItemInlineEdit";
import { useWorkItemDraft } from "./work-item/useWorkItemDraft";
import { useWorkItemStoryDrag } from "./work-item/useWorkItemStoryDrag";
import { resolveProjectIdFromScope } from "./work-item/projectScope";
import type {
    WorkItemType,
    Priority,
    WorkItemTableProps,
    ViewFilters,
    NewBugForm,
    RowItem,
    StatusOption,
} from "@/components/vort-biz/work-item/WorkItemTable.types";

const props = withDefaults(defineProps<WorkItemTableProps>(), {
    pageTitle: "缺陷",
    createButtonText: "+ 新建缺陷",
    createDrawerTitle: "新建缺陷",
    detailDrawerTitle: "缺陷详情",
    descriptionPlaceholder: "请填写缺陷描述",
    useApi: true,
    projectId: "",
    viewFilters: () => ({}),
});

const route = useRoute();
const router = useRouter();
const vortFlowStore = useVortFlowStore();

const currentWorkItemType = computed(() => (props.type as "需求" | "任务" | "缺陷") || null);
// 视图状态 key：单类型用类型名；工作墙用 "wall" 独立持久化
const viewTypeKey = computed<"需求" | "任务" | "缺陷" | "wall">(
    () => currentWorkItemType.value || "wall"
);
const currentViewId = computed(() => vortFlowStore.getViewId(viewTypeKey.value));
const onViewChange = (viewId: string) => {
    vortFlowStore.setViewId(viewTypeKey.value, viewId);
};
const viewManageOpen = ref(false);
const viewCreateOpen = ref(false);

const { views: mergedViews, activeViewFilters: builtInViewFilters } = useVortFlowViews(viewTypeKey.value);

const isArchivedView = computed(() => Boolean((builtInViewFilters.value as Record<string, any>)?.archived));

// --- Common & Draft ---

const {
    memberOptions, ownerGroups, getStatusOptionsByType, priorityOptions,
    getAvatarBg, getAvatarLabel, getMemberAvatarUrl,
    loadMemberOptions, getMemberIdByName, getMemberNameById,
    getWorkItemTypeIconClass, getWorkItemTypeIcon,
    mapBackendStateToStatus, mapBackendPriority, mapBackendPriorityScore, formatCnTime, formatDate,
    toBackendPriorityLevel, toTaskEstimateHours, getBackendStatesByDisplayStatus,
    bugStatusFilterOptions, demandStatusFilterOptions, taskStatusFilterOptions, loadStatusOptions,
    getEnrichedOwnerGroups, defaultCollapsedGroups, recordRecentMember,
} = useWorkItemCommon();

const { saveDraft, loadDraft, clearDraft } = useWorkItemDraft();

// --- Filters & helpers ---

const keyword = ref("");
const owner = ref<string[]>([]);
const type = ref<WorkItemType[]>([]);
const status = ref<string[]>([]);
const totalCount = ref(0);
// 「包含已归档」开关：开启后常规视图同时展示归档+未归档；
// 「已归档」视图下无意义（本身只看归档），故渲染时隐藏并在下发时屏蔽。
const includeArchived = ref(false);

const resolveActiveType = (): WorkItemType => {
    if (props.type) return props.type;
    if (type.value.length === 1) {
        const v = type.value[0];
        if (v === "需求" || v === "任务" || v === "缺陷") return v;
    }
    return "缺陷";
};

const allStatusFilterOptions: StatusOption[] = Array.from(
    new Map(
        [...demandStatusFilterOptions, ...taskStatusFilterOptions, ...bugStatusFilterOptions].map((item) => [item.value, item])
    ).values()
);
const currentStatusFilterOptions = computed(() => getStatusOptionsByType(resolveActiveType()));

// 工作墙下按需求/任务/缺陷分组传给状态筛选弹窗
const statusFilterGroups = computed(() => {
    if (props.type) return [];
    return [
        { type: "需求" as WorkItemType, options: getStatusOptionsByType("需求") },
        { type: "任务" as WorkItemType, options: getStatusOptionsByType("任务") },
        { type: "缺陷" as WorkItemType, options: getStatusOptionsByType("缺陷") },
    ];
});

const normalizeDateValue = (value: unknown): string => {
    if (value instanceof Date) return formatDate(value);
    if (typeof value === "string") {
        const direct = value.trim();
        if (/^\d{4}-\d{2}-\d{2}$/.test(direct)) return direct;
        const parsed = new Date(direct);
        if (!Number.isNaN(parsed.getTime())) return formatDate(parsed);
    }
    return "";
};

const getActiveProjectId = (): string => props.projectId || vortFlowStore.selectedProjectId || "";

const tableEnrichedGroups = ref<{ label: string; members: string[] }[]>([]);
const tableEnrichedCollapsed = ref<string[]>([]);
const tableActiveGroups = computed(() =>
    tableEnrichedGroups.value.length > 0 ? tableEnrichedGroups.value : ownerGroups.value,
);
const refreshTableEnrichedGroups = () => {
    const pid = getActiveProjectId();
    if (pid) {
        getEnrichedOwnerGroups(pid).then((groups) => {
            tableEnrichedGroups.value = groups;
            tableEnrichedCollapsed.value = defaultCollapsedGroups(groups);
        });
    }
};

const onAvatarError = (e: Event) => {
    const el = e.target as HTMLImageElement | null;
    if (el) el.style.display = "none";
};

// --- Metadata ---

const {
    apiProjects, apiIterations, apiRepos, apiTagDefinitions,
    baseTagOptions, dynamicTagOptions, dynamicIterationOptions, dynamicVersionOptions,
    branchOptionsMap, branchLoadingMap, remoteTemplates,
    getDescriptionTemplate, getRepoNameById, getBranchOptions,
    loadRepoOptions, mergeIterationOptions, resetIterationOptions, loadBranchOptions, loadTagDefinitions,
    collectTagOptions, collectEnumOptions, loadApiMetadata, loadDescriptionTemplates,
} = useWorkItemMetadata({
    useApi: computed(() => props.useApi),
    getActiveProjectId,
});

const currentProjectName = computed(() => {
    if (!props.projectId) return "";
    return apiProjects.value.find(p => p.id === props.projectId)?.name || "";
});

// 本地演示模式不请求接口，保留与新建抽屉一致的静态迭代选项。
const localIterationOptions = [
    { id: "Sprint 1", name: "Sprint 1" },
    { id: "Sprint 2", name: "Sprint 2" },
    { id: "Sprint 3", name: "Sprint 3" },
];

// --- Column filter state ---

const columnFilters = reactive<Record<string, ColumnFilterValue | null>>({});
const columnSortField = ref<string>("");
const columnSortOrder = ref<"ascend" | "descend" | null>(null);
const tableRef = ref<any>(null);

const {
    statusFilterConfig, dateFilterConfig, tagsFilterConfig,
    ownerFilterConfig, collaboratorsFilterConfig,
    iterationFilterConfig, versionFilterConfig,
    priorityFilterConfig, creatorFilterConfig, typeFilterConfig,
    handleColumnSort, handleColumnFilter,
} = useWorkItemColumnFilters({
    currentStatusFilterOptions, dynamicTagOptions, baseTagOptions,
    dynamicIterationOptions, dynamicVersionOptions,
    memberOptions, getMemberAvatarUrl, getAvatarBg, getAvatarLabel, priorityOptions,
    columnFilters, columnSortField, columnSortOrder, tableRef,
});

// --- Column settings & View state ---

const columnTypeKey = props.type || "wall";
// 跨多项目（含全部项目）浏览时自动展示「关联项目」列；嵌入的单项目场景不展示
const showProjectColumn = computed(() => {
    const ids = (props.projectIds || []).filter(Boolean);
    if (ids.length) return ids.length > 1;
    return !props.projectId;
});
const {
    columnSettingsOpen, columnSettings, columns, columnSettingsForDialog,
    loadColumnSettingsFromStore, handleColumnSettingsSave, handleColumnWidthChange, applyOrderedColumnSettings,
} = useWorkItemColumns({ workItemType: columnTypeKey, showProjectColumn });

const {
    viewDirty, isSystemView, saveViewDialogOpen, saveViewDropdownOpen, saveViewWrapperRef,
    currentViewStateForCreate, resetViewBaseline, collectCurrentViewState,
    handleUpdateCurrentView, handleSaveAsNew, handleSaveAsNewView, applyViewState,
} = useWorkItemViewState({
    workItemType: columnTypeKey, currentViewId, keyword, owner, status,
    columnFilters, columnSortField, columnSortOrder, columnSettings, applyOrderedColumnSettings,
});

// ProTable 内置 sorter 触发的 sortChange 同步到 columnSortField/Order，
// 让 useWorkItemDataSource 拿到正确的 effectiveSortField，避免被默认 priority 排序覆盖。
// 白名单守卫：只对 SORT_FIELD_MAP 里有后端映射的字段才同步。
// 像 workNo / estimateHours 这类列虽然 ProTable 标了 sorter:true 但后端不支持，
// 不能让点击它们意外清掉用户已有的有效排序（如默认的 priority）。
const handleProTableSortChange = (sorter: { field: string; order: "ascend" | "descend" | null }) => {
    if (sorter.order && !(sorter.field in SORT_FIELD_MAP)) return;
    columnSortField.value = sorter.order ? sorter.field : "";
    columnSortOrder.value = sorter.order;
};

const handleCreateViewFromDialog = async (data: { name: string; scope: "personal" | "shared" }) => {
    const { filters, cols } = collectCurrentViewState();
    const maxOrder = vortFlowStore.customViews.reduce((max, v) => Math.max(max, v.order), -1);
    await vortFlowStore.addCustomView({
        name: data.name, work_item_type: props.type || "缺陷", scope: data.scope,
        visible: true, filters, columns: cols, order: maxOrder + 1,
    });
    viewCreateOpen.value = false;
};

// --- Shared reactive state ---

const itemRowsById = reactive<Record<string, RowItem>>({});
const itemChildrenMap = reactive<Record<string, RowItem[]>>({});
const expandedItemIds = reactive<Record<string, boolean>>({});
const expandingItemIds = reactive<Record<string, boolean>>({});
const pinnedRowsByType = reactive<Record<WorkItemType, RowItem[]>>({ 需求: [], 任务: [], 缺陷: [] });
const priorityModel = reactive<Record<string, Priority>>({});
const priorityScoreModel = reactive<Record<string, number>>({});
const tagsModel = reactive<Record<string, string[]>>({});
const planTimeModel = reactive<Record<string, any>>({});
const collaboratorsModel = reactive<Record<string, string[]>>({});

// --- Data source ---

const {
    mapBackendItemToRow, findItemRowById, findItemRowByIdentifier,
    loadItemById, loadChildItems, request, postProcessTableRows, prependPinnedRow,
    isMultiProjectView,
} = useWorkItemDataSource({
    useApi: computed(() => props.useApi), propType: props.type || "",
    propProjectId: computed(() => props.projectId || ""),
    propProjectIds: computed(() => props.projectIds || []),
    propIterationId: computed(() => props.iterationId || ""),
    propViewFilters: computed(() => ({
        ...builtInViewFilters.value,
        ...(props.viewFilters || {}),
        // 「已归档」视图下屏蔽 include_archived，避免覆盖 archived=true 把未归档也拉进来
        include_archived: !isArchivedView.value && includeArchived.value,
    })),
    type, owner, status, columnFilters, columnSortField, columnSortOrder, totalCount,
    apiProjects, pinnedRowsByType, expandedItemIds, expandingItemIds, itemRowsById, itemChildrenMap,
    getMemberIdByName, getMemberNameById, loadMemberOptions,
    mapBackendStateToStatus, mapBackendPriority, mapBackendPriorityScore,
    getBackendStatesByDisplayStatus, formatCnTime, formatDate,
    collectTagOptions, collectEnumOptions,
});

// --- CRUD ---

const createWorkItemRef = ref<{
    submit: () => NewBugForm | null;
    reset: () => void;
    cancel: () => void;
    getFormData: () => NewBugForm;
    getDescriptionTemplateForCurrentType: () => string;
} | null>(null);

const {
    selectedRowKeys, selectedRows, createParentItemId, createProjectId,
    createDraftData, isCreating, createBugAttachments, createBugForm, createParentRecord,
    createInitialBugForm, resetCreateBugForm, rowSelection, clearSelection,
    syncRecordUpdateToApi, syncRecordStatusToApi, deleteOne, handleBatchDelete,
    handleBatchArchive, handleBatchUnarchive,
    handleCreateSuccess: crudCreateSuccess, handleCopyWorkItem: crudCopyWorkItem,
    handleDetailUpdate: crudDetailUpdate, handleUnlinkChild: crudUnlinkChild,
} = useWorkItemCrud({
    useApi: computed(() => props.useApi), propType: props.type || "",
    getDescriptionTemplate, getMemberIdByName, getBackendStatesByDisplayStatus, formatCnTime,
    mapBackendItemToRow, prependPinnedRow, pinnedRowsByType, findItemRowById,
    apiProjects, apiIterations, dynamicVersionOptions,
    itemRowsById, itemChildrenMap, expandedItemIds, tableRef, createWorkItemRef,
    saveDraft, loadDraft, clearDraft,
});

// --- Inline edit ---

const {
    priorityPickerOpenMap, tagPickerOpenMap, statusPickerOpenMap,
    ownerPickerOpenMap, collaboratorsPickerOpenMap,
    getInteractiveCellKey, isCellBackgroundClick, openCellPickerOnBackgroundClick,
    getRowPriority, getRowPriorityScore, selectPriority, selectPriorityScore,
    getRowStatus, selectRowStatus,
    getRowOwner, selectRowOwner, getRowCollaborators, setRowCollaborators,
    getRowTags, setRowTags, rowTagOptions,
    getRowPlanTimeText, getRowOverdueInfo, getRowStaleInfo, onPlanTimeChange, onPlanTimeOpenChange,
    getRowPlanTime, togglePlanTimeMenu,
    getTagColor, openCreateTagDialog, openEditTagDialog, handleTagDialogSaved,
    tagDialogOpen, tagDialogMode, tagDialogData,
    openPlanTimeFor, planTimePickerOpen,
} = useWorkItemInlineEdit({
    useApi: computed(() => props.useApi), syncRecordUpdateToApi, syncRecordStatusToApi,
    getMemberIdByName, mapBackendPriority, toBackendPriorityLevel, toTaskEstimateHours,
    getBackendStatesByDisplayStatus: (t, s) => getBackendStatesByDisplayStatus(t as WorkItemType, s) || [],
    dynamicTagOptions, baseTagOptions, tagDefinitions: apiTagDefinitions,
    priorityModel, priorityScoreModel, tagsModel, collaboratorsModel, planTimeModel, normalizeDateValue,
    onTagsChanged: loadTagDefinitions,
    onTagRenamed: () => { tableRef.value?.refresh?.(); },
});

// --- Field editors ---

const {
    estimateEditingFor, estimateDraftMap, estimateInputRef, openEstimateEditor, selectRowEstimateHours,
    progressEditingFor, progressDraftMap, progressInputRef, isProgressReadonly, openProgressEditor, selectRowProgress,
    projectPickerOpenMap, selectRowProject, selectRowIteration,
    repoPickerOpenMap, openRepoPicker, selectRowRepo,
    branchPickerOpenMap, openBranchPicker, selectRowBranch,
    openDateFieldFor, dateFieldPickerOpen, toggleDateFieldPicker, onDateFieldPickerOpenChange, selectRowDateField,
} = useWorkItemFieldEditors({
    syncRecordUpdateToApi, getInteractiveCellKey, isCellBackgroundClick, openCellPickerOnBackgroundClick,
    normalizeDateValue, apiProjects, apiIterations, dynamicIterationOptions, planTimeModel,
    getRepoNameById, loadRepoOptions, loadBranchOptions,
});

// --- Detail panel ---

const {
    detailSelectedWorkNo, detailDescEditing, detailDescDraft,
    detailRecordSnapshot, detailComponentRef, detailParentRecord, detailChildRecords,
    detailCurrentRecord, cacheDescDraftBeforeClose, prepareDetailView,
    handleOpenRelated: detailOpenRelated, syncDetailRelations,
} = useWorkItemDetailPanel({
    useApi: computed(() => props.useApi), syncRecordUpdateToApi,
    loadItemById, loadChildItems, getRowPriority, getRowPriorityScore, getRowTags, planTimeModel,
});

// --- Work item drag (需求 / 任务 / 缺陷 / 工作墙) ---
// 启用条件：开启 useApi 后，所有 type 都启用拖拽排序；工作墙（type="")也启用，
// 跨类型嵌入由 composable 按规则校验（需求不能成为任务/缺陷的子等）。
const storyDragEnabled = computed(() => Boolean(props.useApi));
const storyDragProjectId = computed(() => props.projectId || vortFlowStore.selectedProjectId || "");

const {
    bindDragSource: bindStoryDragSource,
    bindRowDropTarget: bindStoryRowDropTarget,
    dropTargetClass: storyDropTargetClass,
} = useWorkItemStoryDrag({
    enabled: storyDragEnabled,
    projectId: storyDragProjectId,
    itemRowsById,
    itemChildrenMap,
    expandedItemIds,
    expandingItemIds,
    loadChildItems,
    refreshTable: () => tableRef.value?.refresh?.(),
    getVisibleRows: () => (tableRef.value?.dataSource as RowItem[]) || [],
});

// --- Export ---

const { handleExportCsv, handleExportExcel, handleExportJson } = useWorkItemExport({
    selectedRows,
    getCurrentPageRows: () => (tableRef.value?.dataSource as RowItem[]) || [],
});

// --- Gantt state (D6: 抽到 useWorkItemGantt composable) ---

const viewMode = computed<ViewMode>({
    get: () => vortFlowStore.viewMode as ViewMode,
    set: (v) => { vortFlowStore.viewMode = v; },
});
const ganttZoomLevel = computed<GanttZoomLevel>({
    get: () => vortFlowStore.ganttZoomLevel as GanttZoomLevel,
    set: (v) => { vortFlowStore.ganttZoomLevel = v; },
});
const tablePageSizeRef = computed<number>({
    get: () => vortFlowStore.tablePageSize,
    set: (v) => { vortFlowStore.tablePageSize = v; },
});
const ganttDividerRatioRef = computed<number>({
    get: () => vortFlowStore.ganttDividerRatio,
    set: (v) => { vortFlowStore.ganttDividerRatio = v; },
});

const {
    GANTT_ROW_HEIGHT,
    isGanttMode,
    ganttLeftWidth,
    ganttContainerRef,
    ganttTablePaneRef,
    ganttTimelineRef,
    ganttRowTops,
    ganttRowHeights,
    ganttBodyHeight,
    ganttTableHeaderHeight,
    ganttRows,
    tableFirstLoaded,
    measureGanttPositions,
    setupGanttObserver,
    initGanttWidth,
    onGanttDividerDrag,
    onGanttDividerDragEnd,
    ganttCanUndo,
    ganttCanRedo,
    ganttResetUndo,
    handleGanttUndoAction,
    handleGanttRedoAction,
    handleGanttTimeChange,
    handleGanttIconTimeChange,
    handleGanttClearIconTime,
    handleGanttProgressChange,
    handleGanttCreateTime,
    handleGanttClearDate,
    ganttPaginationTotal,
    ganttPaginationCurrent,
    ganttPaginationPageSize,
    handleGanttPageChange,
    handleGanttPageSizeChange,
    markTableFirstLoaded,
} = useWorkItemGantt({
    viewMode,
    ganttZoomLevel,
    tablePageSize: tablePageSizeRef,
    ganttDividerRatio: ganttDividerRatioRef,
    tableRef,
    findItemRowByIdentifier,
    syncRecordUpdateToApi,
    postProcessTableRows,
});

const ganttRequest = async (params: any) => {
    const result = await request(params);
    markTableFirstLoaded();
    return result;
};

// --- Page state ---

const importDialogOpen = ref(false);
const importRecordDialogOpen = ref(false);
const batchPropertyEditorOpen = ref(false);
const refreshKey = ref(0);
const mountedReady = ref(false);
const initialLoading = ref(true);

const queryParams = computed(() => ({
    keyword: keyword.value, owner: owner.value,
    type: props.type ? [props.type] : type.value, status: status.value, _rk: refreshKey.value,
    // 把 viewFilters/builtInViewFilters 引用纳入 ProTable 的 params 监听，
    // 这样切换关注成员（owner）+ 切换状态（status）能合并为一次 fetchData，
    // 避免双重请求带来的 race condition。
    _vf: props.viewFilters,
    _bvf: builtInViewFilters.value,
}));
const refreshTable = () => { refreshKey.value++; };
// 批量编辑完成后直接调用并等待表格实例刷新。仅递增 refreshKey 只能异步触发
// 外部 params watcher，批量回调无法确认刷新请求已完成；先等待选中项状态落盘，
// 再复用 ProTable 的刷新入口可确保当前页重新请求并替换旧快照。
const handleBatchDone = async () => {
    clearSelection();
    await nextTick();
    await tableRef.value?.refresh?.();
};
const onReset = () => { keyword.value = ""; owner.value = []; type.value = []; status.value = []; ganttResetUndo(); };

watch(() => [props.projectId, (props.projectIds || []).join(",")], () => {
    // 迭代下拉在项目范围变化后清空旧缓存，等用户再次打开时再请求新范围。
    resetIterationOptions();
    loadRepoOptions();
    refreshTableEnrichedGroups();
    tableRef.value?.refresh?.();
});
// 工作墙顶部切换迭代时，propIterationId 变化但 projectId 不变，需要单独触发表格重新拉取
watch(() => props.iterationId, () => { tableRef.value?.refresh?.(); });
// 「包含已归档」开关切换后重新拉取；切到「已归档」视图时重置开关避免残留勾选态误导
watch(includeArchived, () => { tableRef.value?.refresh?.(); });
watch(isArchivedView, (v) => { if (v) includeArchived.value = false; });

const rowKeyGetter = (record: RowItem) => record.backendId || record.workNo;

// --- Drawer state ---

const createBugDrawerMode = ref<"create" | "detail">(
    route.query.action === "detail" ? "detail" : "create",
);

const isDetailEditing = () => {
    if (createBugDrawerMode.value !== "detail") return false;
    const comp = detailComponentRef.value;
    if (!comp) return false;
    return !!(comp.detailDescEditing || comp.editingCommentId || comp.detailCommentDraft?.trim());
};

const doCloseDrawer = () => {
    cacheDescDraftBeforeClose();
    if (createBugDrawerMode.value === "create") {
        const formData = createWorkItemRef.value?.getFormData?.();
        const descTemplate = createWorkItemRef.value?.getDescriptionTemplateForCurrentType?.() ?? "";
        if (formData) {
            const workItemType = (props.type || formData.type || "缺陷") as WorkItemType;
            saveDraft(workItemType, formData, createParentItemId.value, descTemplate);
        }
    }
    router.replace({ query: { ...route.query, action: undefined, id: undefined, parentId: undefined, tab: undefined } });
};

const createBugDrawerOpen = computed({
    get: () => {
        const action = route.query.action as string;
        return action === "create" || action === "detail";
    },
    set: (val: boolean) => {
        if (!val) {
            if (isDetailEditing()) {
                dialog.confirm({
                    title: "未保存的更改",
                    content: "当前有未保存的编辑内容，关闭将丢失这些更改。确定要关闭吗？",
                    okText: "确定关闭",
                    okType: "danger",
                    cancelText: "继续编辑",
                    onOk: () => doCloseDrawer(),
                });
                return;
            }
            doCloseDrawer();
        }
    }
});

const handleCancelCreateBug = () => {
    createBugDrawerOpen.value = false;
    createParentItemId.value = "";
    createProjectId.value = "";
};

// --- Page-level CRUD wrappers (bridge composable + drawer state) ---

// 工作墙模式下，drawer 的 title 跟随当前选中的创建类型
const createDrawerTitleText = computed(() => {
    if (props.type) return props.createDrawerTitle;
    const t = createBugForm.type || "缺陷";
    return `新建${t}`;
});

const handleCreateBug = async (selectedType?: WorkItemType) => {
    const effectiveType = (props.type || selectedType || "缺陷") as WorkItemType;
    await loadApiMetadata(effectiveType === "任务");
    createBugDrawerMode.value = "create";
    createParentItemId.value = "";
    // 仅在明确单选时回填项目；多选/全部项目没有唯一归属，保持关联项目为空。
    createProjectId.value = resolveProjectIdFromScope(props.projectIds, props.projectId);
    resetCreateBugForm();
    createDraftData.value = loadDraft(effectiveType, "");
    createBugForm.type = effectiveType;
    router.replace({ query: { ...route.query, action: "create", parentId: undefined, type: props.type ? undefined : effectiveType } });
};

const handleCreateChild = async (record: RowItem) => {
    if ((record.type !== "需求" && record.type !== "任务") || !record.backendId) return;
    await loadApiMetadata(record.type === "任务");
    createBugDrawerMode.value = "create";
    createParentItemId.value = String(record.backendId);
    createProjectId.value = record.projectId || "";
    createDraftData.value = null;
    resetCreateBugForm();
    router.replace({ query: { ...route.query, action: "create", parentId: String(record.backendId), id: undefined } });
};

const handleCancelCreateWorkItem = () => {
    if (createWorkItemRef.value) { createWorkItemRef.value.cancel(); return; }
    handleCancelCreateBug();
};

const handleCreateSuccess = async (formData: NewBugForm, keepCreating = false) => {
    const success = await crudCreateSuccess(formData, keepCreating);
    if (success && !keepCreating) handleCancelCreateBug();
};

const handleSubmitCreateBug = async (keepCreating = false) => {
    const formData = createWorkItemRef.value?.submit();
    if (!formData) return;
    await handleCreateSuccess(formData, keepCreating);
};

const handleOpenBugDetail = async (record: RowItem) => {
    // 打开工作项详情时，把顶部项目选择器同步到该工作项真实所属项目。
    // 深链 / 分享链接 / 关联工作项跳转可能打开与当前所选项目不同项目的工作项，
    // 若不同步会出现顶部项目与详情面板「对应项目不一致」。仅在已选中具体项目且不一致时同步，
    // 「全部项目」模式（selectedProjectId 为空）保持不变，避免破坏跨项目浏览。
    // 仅在「恰好选中单个项目」时同步，避免多选/全部项目模式下打开详情把筛选范围收敛成单项目。
    if (
        record.projectId &&
        vortFlowStore.selectedProjectIds.length === 1 &&
        record.projectId !== vortFlowStore.selectedProjectIds[0]
    ) {
        vortFlowStore.setProjectId(record.projectId);
    }
    const info = await prepareDetailView(record);
    const base = createInitialBugForm();
    createBugDrawerMode.value = "detail";
    Object.assign(createBugForm, {
        ...base, title: record.title, owner: record.owner === "未指派" ? "" : record.owner,
        type: record.type, planTime: [...info.planTime], priority: info.priority,
        priorityScore: info.priorityScore,
        tags: [...info.tags], description: record.description || base.description,
    });
    const typeToTab: Record<string, string> = { "需求": "story", "任务": "task", "缺陷": "bug" };
    const fallbackTab = props.type ? typeToTab[props.type] : "";
    router.replace({ query: { ...route.query, action: "detail", id: record.backendId || record.workNo, tab: typeToTab[record.type] || fallbackTab } });
};

const handleDetailUpdate = async (data: Partial<RowItem>) => {
    if (!detailCurrentRecord.value) return;
    const result = await crudDetailUpdate(detailCurrentRecord.value, data);
    if (result === "close") handleCancelCreateBug();
};

const handleDetailDelete = async () => {
    const rec = detailCurrentRecord.value;
    if (!rec) return;
    try { await deleteOne(rec); message.success("删除成功"); handleCancelCreateBug(); tableRef.value?.refresh?.(); }
    catch { message.error("删除失败"); }
};

const handleCopyWorkItem = async () => {
    const success = await crudCopyWorkItem(detailCurrentRecord.value);
    if (success) createBugDrawerOpen.value = false;
};

const handleUnlinkChild = async (child: RowItem) => {
    await crudUnlinkChild(child, detailCurrentRecord.value, syncDetailRelations);
};

const handleOpenRelated = async (partial: any) => {
    await detailOpenRelated(partial, handleOpenBugDetail);
};

// --- Tree expand ---

const toggleItemExpand = async (record: RowItem) => {
    if ((record.type !== "需求" && record.type !== "任务") || !record.childrenCount || !record.backendId) return;
    const itemId = String(record.backendId);
    if (expandingItemIds[itemId]) return;
    if (expandedItemIds[itemId]) { expandedItemIds[itemId] = false; return; }
    if (!itemChildrenMap[itemId]) {
        expandingItemIds[itemId] = true;
        try { await loadChildItems(itemId, record.type, record.projectId); }
        finally { expandingItemIds[itemId] = false; }
    }
    expandedItemIds[itemId] = true;
};

// --- Tag rendering ---
const tagTextMeasureCache = new Map<string, number>();
let tagMeasureCtx: CanvasRenderingContext2D | null | undefined;
const measureTagTextWidth = (text: string): number => {
    if (!text) return 0;
    const cached = tagTextMeasureCache.get(text);
    if (cached !== undefined) return cached;
    if (typeof document === "undefined") {
        const fallback = text.length * 12;
        tagTextMeasureCache.set(text, fallback);
        return fallback;
    }
    if (tagMeasureCtx === undefined) {
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d");
        if (ctx) ctx.font = "12px sans-serif";
        tagMeasureCtx = ctx;
    }
    const w = tagMeasureCtx ? tagMeasureCtx.measureText(text).width : text.length * 12;
    tagTextMeasureCache.set(text, w);
    return w;
};

const getCollapsedTags = (tags: string[], resolvedWidth?: string | number): { visible: string[]; hidden: number } => {
    const width = typeof resolvedWidth === "number" ? resolvedWidth
        : (typeof resolvedWidth === "string" ? Number.parseFloat(resolvedWidth) : 180);
    const cellWidth = Number.isFinite(width) ? width : 180;
    const available = Math.max(48, cellWidth - 14);
    const moreReserve = 34;
    const gap = 4;
    let used = 0;
    const visible: string[] = [];
    // chip = px-1.5 (12px) + text + 2px safety margin
    const chipWidth = (text: string) => Math.max(36, Math.ceil(measureTagTextWidth(text)) + 14);
    for (let i = 0; i < tags.length; i++) {
        const w = chipWidth(tags[i]!);
        const remaining = tags.length - i - 1;
        const nextUsed = used + (visible.length > 0 ? gap : 0) + w;
        const limit = remaining > 0 ? available - moreReserve : available;
        if (nextUsed > limit) break;
        visible.push(tags[i]!);
        used = nextUsed;
    }
    // 当列宽极窄连第一个 chip 都装不下时，至少展示首个标签，避免出现仅有 "+N"
    // 而完全看不到任何标签内容的退化效果。
    if (visible.length === 0 && tags.length > 0) {
        visible.push(tags[0]!);
    }
    return { visible, hidden: Math.max(0, tags.length - visible.length) };
};

const getTagRenderInfo = (record: RowItem, text: string[] | undefined, resolvedWidth?: string | number) =>
    getCollapsedTags(getRowTags(record, text), resolvedWidth);

// --- Lifecycle ---

async function openDetailFromRoute(id: string) {
    const urlTab = route.query.tab as string;
    const tabTypeMap: Record<string, WorkItemType> = { story: "需求", task: "任务", bug: "缺陷" };
    const tabRouteMap: Record<string, string> = { story: "/vortflow/stories", task: "/vortflow/tasks", bug: "/vortflow/bugs" };
    const urlType = tabTypeMap[urlTab];
    // 单类型页面下，URL 指向其他类型时跳到对应列表；工作墙跨类型不跳
    if (props.type && urlType && urlType !== props.type) {
        const targetPath = tabRouteMap[urlTab];
        if (targetPath) {
            const urlProjectId = (route.query.project_id || route.query.project) as string;
            router.replace({ path: targetPath, query: { project_id: urlProjectId || undefined, action: "detail", id, tab: urlTab } });
        }
        return;
    }
    // 工作墙模式（props.type 为空）下，优先按 URL tab 推导出的 type 作为 fallback，
    // 避免误用默认的 "缺陷" 类型去拉取其它类型的 ID 导致 404 → drawer 弹出又收起。
    const fallbackType: WorkItemType = (props.type as WorkItemType) || urlType || "缺陷";
    // 强制拉最新数据，避免命中旧缓存导致"列表已展示负责人、详情却空白"
    // （其他人无缓存打开正常）。拉取失败时 loadItemById 内部回退缓存。
    let record = await loadItemById(id, fallbackType, true);
    if (!record) {
        const otherTypes = (["需求", "任务", "缺陷"] as WorkItemType[]).filter(t => t !== fallbackType);
        for (const t of otherTypes) { record = await loadItemById(id, t, true); if (record) break; }
    }
    if (record) { handleOpenBugDetail(record); }
    else { router.replace({ query: { ...route.query, action: undefined, id: undefined, parentId: undefined, tab: undefined } }); }
}

onMounted(async () => {
    const urlProjectId = (route.query.project_id || route.query.project) as string;
    if (urlProjectId && urlProjectId !== vortFlowStore.selectedProjectId) {
        vortFlowStore.setProjectId(urlProjectId);
    }
    const hasCachedColumns = !!vortFlowStore.getColumnSettings(columnTypeKey);
    if (hasCachedColumns) { columnSettings.value = loadColumnSettingsFromStore(); resetViewBaseline(); }

    // 工作墙：默认按优先级升序展示，让用户首次访问就能看到优先排序结果
    if (!props.type && !columnSortField.value) {
        columnSortField.value = "priority";
        columnSortOrder.value = "ascend";
    }

    await loadMemberOptions();
    refreshTableEnrichedGroups();
    await Promise.all([
        loadApiMetadata(false), loadRepoOptions(), loadTagDefinitions(),
        loadStatusOptions(), vortFlowStore.loadColumnSettings(columnTypeKey),
        vortFlowStore.loadViews(), loadDescriptionTemplates(),
    ]);
    columnSettings.value = loadColumnSettingsFromStore();
    applyViewState();

    const urlAssignee = route.query.assignee_id as string;
    const urlStatus = route.query.status as string;
    if (urlStatus === "incomplete" && currentWorkItemType.value) {
        onViewChange("incomplete");
        await nextTick();
    }
    if (urlAssignee) {
        const assigneeName = getMemberNameById(urlAssignee);
        if (assigneeName) {
            owner.value = [assigneeName];
        }
    }

    mountedReady.value = true;
    initialLoading.value = false;
    refreshTable();
    nextTick(() => { initGanttWidth(); setupGanttObserver(); measureGanttPositions(); });

    const action = route.query.action as string;
    const id = route.query.id as string;
    const parentId = route.query.parentId as string;
    if (action === "create") {
        await handleCreateBug();
        if (parentId) {
            createParentItemId.value = parentId;
            createProjectId.value = findItemRowById(parentId)?.projectId || "";
        }
    } else if (action === "detail" && id) {
        await openDetailFromRoute(id);
    }

    if (urlProjectId || urlAssignee || urlStatus) {
        const cleaned = { ...route.query };
        delete cleaned.project_id;
        delete cleaned.project;
        delete cleaned.assignee_id;
        delete cleaned.status;
        router.replace({ query: cleaned });
    }
});

watch(
    () => ({ action: route.query.action as string, id: route.query.id as string, project: (route.query.project_id || route.query.project) as string }),
    async (cur, prev) => {
        if (!mountedReady.value) return;
        if (cur.action === "detail" && cur.id && (cur.id !== prev?.id || prev?.action !== "detail")) {
            if (cur.project && cur.project !== vortFlowStore.selectedProjectId) {
                vortFlowStore.setProjectId(cur.project);
            }
            await openDetailFromRoute(cur.id);
        }
    },
);

// Sync document.title with the currently opened work item detail so that
// shared links (e.g. ?action=detail&id=...) show a meaningful tab title.
// When the detail drawer closes, router beforeEach restores the route title.
watchEffect(() => {
    const isDetailOpen = createBugDrawerOpen.value && createBugDrawerMode.value === "detail";
    const title = detailCurrentRecord.value?.title?.trim();
    if (isDetailOpen && title) {
        document.title = `${title} - OpenVort`;
    }
});

// 暴露给父组件用于联动筛选（如工作墙的成员关注切换）
const setStatusFilter = (values: string[]) => {
    status.value = Array.isArray(values) ? normalizeVirtualStatusValues(values) : [];
};
const setTypeFilter = (values: WorkItemType[]) => {
    type.value = Array.isArray(values) ? [...values] : [];
};

defineExpose({ setStatusFilter, setTypeFilter });
</script>

<template>
    <div class="space-y-4">
        <WorkItemFilters
            v-model:keyword="keyword"
            v-model:owner="owner"
            v-model:type="type"
            v-model:status="status"
            :page-title="props.pageTitle"
            :create-button-text="props.createButtonText"
            :total-count="totalCount"
            :member-options="memberOptions"
            :owner-groups="tableActiveGroups"
            :status-options="currentStatusFilterOptions"
            :status-groups="statusFilterGroups"
            :show-status-pending-shortcut="!props.type"
            :show-type-filter="false"
            :show-type-tabs="!props.type"
            :create-type-options="!props.type ? (['需求', '任务', '缺陷'] as WorkItemType[]) : []"
            :get-avatar-bg="getAvatarBg"
            :get-avatar-label="getAvatarLabel"
            :get-avatar-url="getMemberAvatarUrl"
            @search="tableRef?.refresh?.()"
            @reset="onReset"
            @create="(t: WorkItemType | undefined) => handleCreateBug(t)"
        >
            <template v-if="currentWorkItemType" #before-count>
                <ViewSelector
                    :views="mergedViews"
                    :selected-id="currentViewId"
                    @update:selected-id="onViewChange"
                    @create-view="viewCreateOpen = true"
                    @manage-views="viewManageOpen = true"
                />
            </template>
            <template v-if="currentWorkItemType && viewDirty" #after-filters>
                <div class="save-view-wrapper" ref="saveViewWrapperRef">
                    <button
                        type="button"
                        class="save-view-btn"
                        @click="saveViewDropdownOpen = !saveViewDropdownOpen"
                    >
                        保存视图
                        <svg
                            class="save-view-arrow"
                            :class="{ open: saveViewDropdownOpen }"
                            width="12" height="12" viewBox="0 0 12 12" fill="none"
                        >
                            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                    <Transition name="dropdown">
                        <div v-if="saveViewDropdownOpen" class="save-view-dropdown">
                            <button
                                type="button"
                                class="save-view-option"
                                :disabled="isSystemView"
                                @click="handleUpdateCurrentView"
                            >
                                更新当前视图
                            </button>
                            <button
                                type="button"
                                class="save-view-option"
                                @click="handleSaveAsNew"
                            >
                                存为新视图
                            </button>
                        </div>
                    </Transition>
                </div>
            </template>
            <template #extra-actions>
                <label v-if="!isArchivedView" class="include-archived-toggle">
                    <vort-checkbox v-model:checked="includeArchived" />
                    <span>包含已归档</span>
                </label>
                <ViewModeToggle v-model="viewMode" />
                <AiAssistButton
                    :prompt="`我想在项目「${currentProjectName}」中创建一个${resolveActiveType()}，请引导我完成。`"
                />
                <MoreActionsDropdown
                    @import="importDialogOpen = true"
                    @import-records="importRecordDialogOpen = true"
                    @export-csv="handleExportCsv"
                    @export-excel="handleExportExcel"
                    @export-json="handleExportJson"
                    @batch-ops="batchPropertyEditorOpen = true"
                />
                <vort-tooltip title="表头显示设置">
                    <button type="button" class="column-settings-btn" @click="columnSettingsOpen = true">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
                    </button>
                </vort-tooltip>
            </template>
        </WorkItemFilters>

        <div
            ref="ganttContainerRef"
            class="bg-white rounded-xl relative"
            :class="isGanttMode ? 'gantt-layout-container' : 'p-4'"
        >
            <div v-if="selectedRows.length > 0" class="flex items-center gap-3 text-sm" :class="isGanttMode ? 'px-4 pt-3 pb-1' : 'mb-3'">
                <span class="text-blue-500 font-medium">已选择 {{ selectedRows.length }} 个工作项</span>
                <VortButton variant="text" @click="batchPropertyEditorOpen = true">修改属性</VortButton>
                <vort-popconfirm v-if="isArchivedView" title="确认取消归档选中记录？" @confirm="handleBatchUnarchive">
                    <VortButton variant="text">取消归档</VortButton>
                </vort-popconfirm>
                <vort-popconfirm v-else title="确认归档选中记录？归档后将不可编辑，且不再出现在常规视图中。" @confirm="handleBatchArchive">
                    <VortButton variant="text">归档</VortButton>
                </vort-popconfirm>
                <vort-popconfirm title="确认批量删除选中记录？" @confirm="handleBatchDelete">
                    <VortButton variant="text" danger>删除</VortButton>
                </vort-popconfirm>
                <VortButton variant="link" @click="clearSelection">取消选择</VortButton>
            </div>

            <div :class="isGanttMode && tableFirstLoaded ? 'gantt-split-layout' : ''">
                <div
                    ref="ganttTablePaneRef"
                    :class="isGanttMode && tableFirstLoaded ? 'gantt-table-pane' : ''"
                    :style="isGanttMode && tableFirstLoaded ? { width: `${ganttLeftWidth}px` } : {}"
                >
            <ProTable
                ref="tableRef"
                :columns="columns"
                :request="ganttRequest"
                :immediate="false"
                :loading="initialLoading"
                :post-process-data="postProcessTableRows"
                :params="queryParams"
                :row-key="rowKeyGetter"
                :row-selection="rowSelection"
                :pagination="{ pageSize: vortFlowStore.tablePageSize, showSizeChanger: true, showQuickJumper: true, pageSizeOptions: [10, 20, 50] }"
                @pagination-change="({ pageSize: ps }) => { vortFlowStore.tablePageSize = ps; }"
                :toolbar="false"
                :bordered="!isGanttMode"
                @column-width-change="handleColumnWidthChange"
                @sort-change="handleProTableSortChange"
            >
                <template #header-status="{ column }">
                    <ColumnFilterPopover field="status" :title="column.title || ''" :config="statusFilterConfig" :sort-order="columnSortField === 'status' ? columnSortOrder : null" :filter-value="columnFilters['status']" @sort="(o) => handleColumnSort('status', o)" @filter="(v) => handleColumnFilter('status', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-priority="{ column }">
                    <ColumnFilterPopover field="priority" :title="column.title || ''" :config="priorityFilterConfig" :sort-order="columnSortField === 'priority' ? columnSortOrder : null" :filter-value="columnFilters['priority']" @sort="(o) => handleColumnSort('priority', o)" @filter="(v) => handleColumnFilter('priority', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-createdAt="{ column }">
                    <ColumnFilterPopover field="createdAt" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'createdAt' ? columnSortOrder : null" :filter-value="columnFilters['createdAt']" @sort="(o) => handleColumnSort('createdAt', o)" @filter="(v) => handleColumnFilter('createdAt', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-tags="{ column }">
                    <ColumnFilterPopover field="tags" :title="column.title || ''" :config="tagsFilterConfig" :sort-order="columnSortField === 'tags' ? columnSortOrder : null" :filter-value="columnFilters['tags']" @sort="(o) => handleColumnSort('tags', o)" @filter="(v) => handleColumnFilter('tags', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-planTime="{ column }">
                    <ColumnFilterPopover field="planTime" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'planTime' ? columnSortOrder : null" :filter-value="columnFilters['planTime']" @sort="(o) => handleColumnSort('planTime', o)" @filter="(v) => handleColumnFilter('planTime', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-owner="{ column }">
                    <ColumnFilterPopover field="owner" :title="column.title || ''" :config="ownerFilterConfig" :sort-order="columnSortField === 'owner' ? columnSortOrder : null" :filter-value="columnFilters['owner']" @sort="(o) => handleColumnSort('owner', o)" @filter="(v) => handleColumnFilter('owner', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-collaborators="{ column }">
                    <ColumnFilterPopover field="collaborators" :title="column.title || ''" :config="collaboratorsFilterConfig" :sort-order="columnSortField === 'collaborators' ? columnSortOrder : null" :filter-value="columnFilters['collaborators']" @sort="(o) => handleColumnSort('collaborators', o)" @filter="(v) => handleColumnFilter('collaborators', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-updatedAt="{ column }">
                    <ColumnFilterPopover field="updatedAt" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'updatedAt' ? columnSortOrder : null" :filter-value="columnFilters['updatedAt']" @sort="(o) => handleColumnSort('updatedAt', o)" @filter="(v) => handleColumnFilter('updatedAt', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-iteration="{ column }">
                    <ColumnFilterPopover field="iteration" :title="column.title || ''" :config="iterationFilterConfig" :sort-order="columnSortField === 'iteration' ? columnSortOrder : null" :filter-value="columnFilters['iteration']" @sort="(o) => handleColumnSort('iteration', o)" @filter="(v) => handleColumnFilter('iteration', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-version="{ column }">
                    <ColumnFilterPopover field="version" :title="column.title || ''" :config="versionFilterConfig" :sort-order="columnSortField === 'version' ? columnSortOrder : null" :filter-value="columnFilters['version']" @sort="(o) => handleColumnSort('version', o)" @filter="(v) => handleColumnFilter('version', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-startAt="{ column }">
                    <ColumnFilterPopover field="startAt" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'startAt' ? columnSortOrder : null" :filter-value="columnFilters['startAt']" @sort="(o) => handleColumnSort('startAt', o)" @filter="(v) => handleColumnFilter('startAt', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-endAt="{ column }">
                    <ColumnFilterPopover field="endAt" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'endAt' ? columnSortOrder : null" :filter-value="columnFilters['endAt']" @sort="(o) => handleColumnSort('endAt', o)" @filter="(v) => handleColumnFilter('endAt', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-testTime="{ column }">
                    <ColumnFilterPopover field="testTime" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'testTime' ? columnSortOrder : null" :filter-value="columnFilters['testTime']" @sort="(o) => handleColumnSort('testTime', o)" @filter="(v) => handleColumnFilter('testTime', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-draftTime="{ column }">
                    <ColumnFilterPopover field="draftTime" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'draftTime' ? columnSortOrder : null" :filter-value="columnFilters['draftTime']" @sort="(o) => handleColumnSort('draftTime', o)" @filter="(v) => handleColumnFilter('draftTime', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-releaseTime="{ column }">
                    <ColumnFilterPopover field="releaseTime" :title="column.title || ''" :config="dateFilterConfig" :sort-order="columnSortField === 'releaseTime' ? columnSortOrder : null" :filter-value="columnFilters['releaseTime']" @sort="(o) => handleColumnSort('releaseTime', o)" @filter="(v) => handleColumnFilter('releaseTime', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-creator="{ column }">
                    <ColumnFilterPopover field="creator" :title="column.title || ''" :config="creatorFilterConfig" :sort-order="columnSortField === 'creator' ? columnSortOrder : null" :filter-value="columnFilters['creator']" @sort="(o) => handleColumnSort('creator', o)" @filter="(v) => handleColumnFilter('creator', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #header-type="{ column }">
                    <ColumnFilterPopover field="type" :title="column.title || ''" :config="typeFilterConfig" :sort-order="columnSortField === 'type' ? columnSortOrder : null" :filter-value="columnFilters['type']" @sort="(o) => handleColumnSort('type', o)" @filter="(v) => handleColumnFilter('type', v)">{{ column.title }}</ColumnFilterPopover>
                </template>

                <template #workNo="{ text, record }">
                    <TableCell
                        :class="storyDragEnabled ? ['story-drop-cell', storyDropTargetClass(record)] : ''"
                        v-bind="storyDragEnabled ? { ...bindStoryRowDropTarget(record), ...bindStoryDragSource(record) } : {}"
                    >
                        <span
                            v-if="storyDragEnabled && !record.isArchived"
                            class="story-drag-handle"
                            :title="record.type === '缺陷' ? '拖动挂到需求或任务下' : '拖动调整顺序或父子关系'"
                            aria-hidden="true"
                        >
                            <svg width="10" height="14" viewBox="0 0 10 14" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="2" cy="3" r="1.2" fill="currentColor"/><circle cx="2" cy="7" r="1.2" fill="currentColor"/><circle cx="2" cy="11" r="1.2" fill="currentColor"/><circle cx="8" cy="3" r="1.2" fill="currentColor"/><circle cx="8" cy="7" r="1.2" fill="currentColor"/><circle cx="8" cy="11" r="1.2" fill="currentColor"/></svg>
                        </span>
                        <span class="text-sm text-gray-700">{{ text }}</span>
                    </TableCell>
                </template>

                <template #title="{ text, record }">
                    <TableCell
                        :class="storyDragEnabled ? ['story-drop-cell', storyDropTargetClass(record)] : ''"
                        v-bind="storyDragEnabled ? { ...bindStoryRowDropTarget(record), ...bindStoryDragSource(record) } : {}"
                        @click="handleOpenBugDetail(record)"
                    >
                        <VortButton class="title-link-cell" :title="text" variant="link" @click.stop="handleOpenBugDetail(record)">
                            <span v-if="record.isChild" class="story-child-indent"></span>
                            <span
                                v-if="record.childrenCount"
                                class="story-expand-toggle"
                                :class="{
                                    expanded: expandedItemIds[String(record.backendId || '')],
                                    loading: expandingItemIds[String(record.backendId || '')]
                                }"
                                @click.stop="toggleItemExpand(record)"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" role="img" class="flex-shrink-0 iconify iconify--gitee icon-caret-down" width="1em" height="1em" preserveAspectRatio="xMidYMid meet" viewBox="0 0 16 16"><g fill="none" fill-rule="evenodd"><path d="M0 0h16v16H0z"></path><path fill="currentColor" fill-rule="nonzero" d="m10.835 7.638-2.388 2.666a.628.628 0 01-.441.196.57.57 0 01-.426-.195L5.192 7.638c-.188-.19-.24-.478-.147-.725s.313-.413.556-.413h4.793c.243 0 .462.162.556.411.093.25.058.537-.115.727z"></path></g></svg>
                            </span>
                            <span v-else class="story-expand-placeholder"></span>
                            
                            <span class="work-type-icon" :class="getWorkItemTypeIconClass(record.type)">
                                <component :is="getWorkItemTypeIcon(record.type)" :size="12" />
                            </span>

                            <span class="title-link-text" :class="{ 'story-child-text': record.isChild, 'is-archived-text': record.isArchived }">{{ text }}</span>
                            <span v-if="record.isArchived" class="title-archived-tag">已归档</span>
                            <span
                                v-if="getRowOverdueInfo(record)"
                                class="title-overdue-tag"
                                :class="{ 'is-done': getRowOverdueInfo(record)!.completed }"
                            >
                                <svg class="title-overdue-icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 208c198.824 0 360 161.176 360 360s-161.176 360-360 360-360-161.176-360-360 161.176-360 360-360z m0 80c-154.64 0-280 125.36-280 280s125.36 280 280 280 280-125.36 280-280-125.36-280-280-280z m46.136 113.488v133.472l90.412 76.648-51.732 61.02L492.268 584a40 40 0 0 1-14.116-29.256l-0.016-1.256v-152h80zM259.528 126.972l56.128 57.008-160.964 158.48L98.56 285.452l160.96-158.48z m507.16 0l160.968 158.48-56.128 57.008-160.964-158.48 56.128-57.008z"></path></svg>
                                逾期{{ getRowOverdueInfo(record)!.days }}天
                            </span>
                            <span
                                v-else-if="getRowStaleInfo(record)"
                                class="title-stale-tag"
                                :title="`已超过 ${getRowStaleInfo(record)!.days} 天没有任何动作（事件 / 评论）`"
                            >
                                <svg class="title-stale-icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64z m0 820c-205.4 0-372-166.6-372-372s166.6-372 372-372 372 166.6 372 372-166.6 372-372 372z"></path><path fill="currentColor" d="M464 336v200a32 32 0 0 0 16 27.712l160 92.4a32 32 0 1 0 32-55.424l-144-83.136V336a32 32 0 0 0-64 0z"></path></svg>
                                停滞{{ getRowStaleInfo(record)!.days }}天
                            </span>
                        </VortButton>
                    </TableCell>
                </template>

                <template #priority="{ text, record }">
                    <TableCell @click="openCellPickerOnBackgroundClick(record, $event, priorityPickerOpenMap)">
                        <WorkItemPriority
                            v-model:open="priorityPickerOpenMap[getInteractiveCellKey(record)]"
                            :model-value="getRowPriority(record, text)"
                            :score="getRowPriorityScore(record)"
                            :enable-score-slider="true"
                            @change-score="(value) => selectPriorityScore(record, value)"
                        />
                    </TableCell>
                </template>

                <template #tags="{ text, record, resolvedWidth }">
                    <TableCell @click="openCellPickerOnBackgroundClick(record, $event, tagPickerOpenMap)">
                        <WorkItemTagPicker
                            v-model:open="tagPickerOpenMap[getInteractiveCellKey(record)]"
                            :model-value="getRowTags(record, text)"
                            :options="rowTagOptions"
                            :get-tag-color="getTagColor"
                            :bordered="false"
                            enable-edit
                            @update:model-value="(value) => setRowTags(record, value)"
                            @edit-tag="openEditTagDialog($event)"
                        >
                            <template #trigger>
                                <div class="flex items-center gap-1 flex-nowrap whitespace-nowrap overflow-hidden">
                                    <template v-for="tag in getTagRenderInfo(record, text, resolvedWidth).visible" :key="record.workNo + '-' + tag">
                                        <span
                                            class="px-1.5 py-0.5 rounded text-xs text-white inline-block"
                                            :style="{ backgroundColor: getTagColor(tag) }"
                                        >
                                            {{ tag }}
                                        </span>
                                    </template>
                                    <span v-if="getTagRenderInfo(record, text, resolvedWidth).hidden > 0" class="text-gray-400 font-medium text-sm">
                                        +{{ getTagRenderInfo(record, text, resolvedWidth).hidden }}
                                    </span>
                                </div>
                            </template>
                            <template #footer>
                                <div class="mt-1 px-3 py-2 text-left">
                                    <button
                                        type="button"
                                        class="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700"
                                        @click.stop="openCreateTagDialog(record, text)"
                                    >
                                        <span class="text-base leading-none">+</span>
                                        <span>新建标签</span>
                                    </button>
                                </div>
                            </template>
                        </WorkItemTagPicker>
                    </TableCell>
                </template>

                <template #status="{ text, record }">
                    <TableCell @click="openCellPickerOnBackgroundClick(record, $event, statusPickerOpenMap)">
                        <WorkItemStatus
                            v-model:open="statusPickerOpenMap[getInteractiveCellKey(record)]"
                            :model-value="getRowStatus(record, text)"
                            :options="getStatusOptionsByType(record.type || resolveActiveType())"
                            @change="(value) => selectRowStatus(record, value)"
                        />
                    </TableCell>
                </template>

                <template #owner="{ text, record }">
                    <TableCell @click="openCellPickerOnBackgroundClick(record, $event, ownerPickerOpenMap)">
                        <WorkItemMemberPicker
                            v-model:open="ownerPickerOpenMap[getInteractiveCellKey(record)]"
                            mode="owner"
                            :owner="getRowOwner(record, text)"
                            :groups="tableActiveGroups"
                            :default-collapsed="tableEnrichedCollapsed"
                            :dropdown-max-height="420"
                            :bordered="false"
                            :get-avatar-bg="getAvatarBg"
                            :get-avatar-label="getAvatarLabel"
                            :get-avatar-url="getMemberAvatarUrl"
                            @update:owner="(value) => { selectRowOwner(record, value); if (value) recordRecentMember(value); }"
                        >
                            <template #trigger>
                                <div
                                    class="h-8 max-w-[150px] px-2 rounded-md bg-transparent flex items-center gap-2 cursor-pointer"
                                >
                                    <span
                                        class="w-6 h-6 rounded-full text-white text-[12px] flex items-center justify-center shrink-0 overflow-hidden relative"
                                        :style="{ backgroundColor: getAvatarBg(getRowOwner(record, text)) }"
                                    >
                                        {{ getAvatarLabel(getRowOwner(record, text)) }}
                                        <img v-if="getMemberAvatarUrl(getRowOwner(record, text))" :src="getMemberAvatarUrl(getRowOwner(record, text))" class="absolute inset-0 w-full h-full object-cover" @error="onAvatarError" />
                                    </span>
                                    <span class="text-sm text-gray-700 truncate">{{ getRowOwner(record, text) }}</span>
                                </div>
                            </template>
                        </WorkItemMemberPicker>
                    </TableCell>
                </template>

                <template #creator="{ text }">
                    <TableCell>
                        <div class="h-8 max-w-[150px] px-2 rounded-md bg-transparent flex items-center gap-2">
                            <span
                                class="w-6 h-6 rounded-full text-white text-[12px] flex items-center justify-center shrink-0"
                                :style="{ backgroundColor: getAvatarBg(text) }"
                            >
                                {{ getAvatarLabel(text) }}
                            </span>
                            <span class="text-sm text-gray-700 truncate">{{ text }}</span>
                        </div>
                    </TableCell>
                </template>

                <template #collaborators="{ text, record }">
                    <TableCell @click="openCellPickerOnBackgroundClick(record, $event, collaboratorsPickerOpenMap)">
                        <WorkItemMemberPicker
                            v-model:open="collaboratorsPickerOpenMap[getInteractiveCellKey(record)]"
                            mode="collaborators"
                            :collaborators="getRowCollaborators(record, text)"
                            :groups="tableActiveGroups"
                            :default-collapsed="tableEnrichedCollapsed"
                            :dropdown-max-height="260"
                            :bordered="false"
                            :get-avatar-bg="getAvatarBg"
                            :get-avatar-label="getAvatarLabel"
                            :get-avatar-url="getMemberAvatarUrl"
                            @update:collaborators="(value) => { setRowCollaborators(record, value); value.forEach(recordRecentMember); }"
                        >
                            <template #trigger>
                                <div
                                    class="h-8 px-1 rounded-md bg-transparent flex items-center cursor-pointer"
                                >
                                    <div class="flex items-center">
                                        <div
                                            v-for="(name, idx) in getRowCollaborators(record, text)"
                                            :key="record.workNo + '-c-' + name + idx"
                                            class="-ml-1 first:ml-0 w-6 h-6 rounded-full border border-white text-white text-[11px] flex items-center justify-center overflow-hidden relative"
                                            :style="{ backgroundColor: getAvatarBg(name) }"
                                            :title="name"
                                        >
                                            {{ getAvatarLabel(name) }}
                                            <img v-if="getMemberAvatarUrl(name)" :src="getMemberAvatarUrl(name)" class="absolute inset-0 w-full h-full object-cover" @error="onAvatarError" />
                                        </div>
                                    </div>
                                </div>
                            </template>
                        </WorkItemMemberPicker>
                    </TableCell>
                </template>

                <template #planTime="{ text, record }">
                    <TableCell @click.stop="togglePlanTimeMenu(record.workNo, record, text)">
                        <div class="relative inline-block" @click.stop>
                            <span
                                v-if="openPlanTimeFor !== record.workNo"
                                class="plan-time-display text-sm text-gray-700 cursor-pointer"
                                @click.stop="togglePlanTimeMenu(record.workNo, record, text)"
                            >
                                {{ getRowPlanTimeText(record, text) }}
                                <span v-if="getRowOverdueInfo(record, text)" class="plan-time-overdue" :class="getRowOverdueInfo(record, text)!.completed ? 'is-done' : ''">
                                    {{ getRowOverdueInfo(record, text)!.completed ? `逾期${getRowOverdueInfo(record, text)!.days}天完成` : `逾期${getRowOverdueInfo(record, text)!.days}天` }}
                                </span>
                            </span>
                            <vort-range-picker
                                v-else
                                v-model="planTimeModel[record.workNo]"
                                format="YYYY-MM-DD"
                                separator="~"
                                :open="planTimePickerOpen"
                                :allow-clear="true"
                                :placeholder="['开始', '结束']"
                                class="plan-time-picker"
                                @change="(value: any) => onPlanTimeChange(record, value)"
                                @open-change="(open: boolean) => onPlanTimeOpenChange(record, open)"
                                @click.stop
                            />
                        </div>
                    </TableCell>
                </template>

                <template #createdAt="{ text }">
                    <TableCell>
                        <span class="text-sm text-gray-700">{{ text }}</span>
                    </TableCell>
                </template>

                <template #type="{ text }">
                    <TableCell>
                        <span class="text-sm text-gray-700">{{ text }}</span>
                    </TableCell>
                </template>

                <template #updatedAt="{ text }">
                    <TableCell>
                        <span class="text-sm text-gray-500">{{ text }}</span>
                    </TableCell>
                </template>

                <template #iteration="{ record }">
                    <TableCell @click.stop>
                        <div class="cell-select-plain text-sm text-gray-700">
                            <IterationSelect
                                :model-value="record.iterationId || undefined"
                                :use-api="props.useApi"
                                :project-id="record.projectId || props.projectId"
                                :project-ids="record.projectId ? [] : props.projectIds"
                                :static-options="localIterationOptions"
                                :selected-label="record.iteration || record.iterationId || ''"
                                placeholder="-"
                                allow-clear
                                size="small"
                                :bordered="false"
                                @options-change="mergeIterationOptions"
                                @change="(val: any, option: any) => selectRowIteration(record, String(val || ''), option)"
                            />
                        </div>
                    </TableCell>
                </template>

                <template #version="{ text }">
                    <TableCell>
                        <span v-if="text" class="text-sm text-gray-700">{{ text }}</span>
                        <span v-else class="text-sm text-gray-300">-</span>
                    </TableCell>
                </template>

                <template #progress="{ record }">
                    <TableCell @click.stop="openProgressEditor(record)">
                        <template v-if="record.type === '需求' || record.type === '任务'">
                            <div class="progress-cell">
                                <div class="progress-bar">
                                    <div
                                        class="progress-fill"
                                        :style="{ width: (record.progress || 0) + '%' }"
                                    />
                                </div>
                                <template v-if="!isProgressReadonly(record) && progressEditingFor === getInteractiveCellKey(record)">
                                    <vort-input-number
                                        ref="progressInputRef"
                                        v-model="progressDraftMap[getInteractiveCellKey(record)]"
                                        :min="0"
                                        :max="100"
                                        :step="5"
                                        size="small"
                                        style="width:64px"
                                        @click.stop
                                        @blur="selectRowProgress(record, progressDraftMap[getInteractiveCellKey(record)])"
                                        @keyup.enter="selectRowProgress(record, progressDraftMap[getInteractiveCellKey(record)])"
                                    />
                                </template>
                                <span v-else class="progress-text" :class="{ 'cursor-pointer': !isProgressReadonly(record) }">{{ record.progress || 0 }}%</span>
                            </div>
                        </template>
                        <span v-else class="text-sm text-gray-300">-</span>
                    </TableCell>
                </template>

                <template #estimateHours="{ text, record }">
                    <TableCell @click.stop="openEstimateEditor(record)">
                        <div class="min-h-8 flex items-center">
                            <vort-input-number
                                v-if="estimateEditingFor === getInteractiveCellKey(record)"
                                ref="estimateInputRef"
                                v-model="estimateDraftMap[getInteractiveCellKey(record)]"
                                :min="0"
                                :step="0.5"
                                size="small"
                                style="width:88px"
                                @click.stop
                                @blur="selectRowEstimateHours(record, estimateDraftMap[getInteractiveCellKey(record)])"
                                @keyup.enter="selectRowEstimateHours(record, estimateDraftMap[getInteractiveCellKey(record)])"
                            />
                            <span
                                v-else-if="text != null && text !== ''"
                                class="text-sm cursor-pointer"
                            >
                                {{ text }}h
                            </span>
                            <span v-else class="text-sm text-blue-400 cursor-pointer">-</span>
                        </div>
                    </TableCell>
                </template>


                <template #project="{ record }">
                    <TableCell @click.stop="projectPickerOpenMap[getInteractiveCellKey(record)] = true">
                        <div class="cell-select-plain text-sm text-gray-700">
                            <vort-select
                                :model-value="record.projectId || undefined"
                                :open="projectPickerOpenMap[getInteractiveCellKey(record)]"
                                placeholder="-"
                                allow-clear
                                size="small"
                                :bordered="false"
                                @update:open="projectPickerOpenMap[getInteractiveCellKey(record)] = $event"
                                @change="(val: any) => selectRowProject(record, val)"
                            >
                                <vort-select-option v-for="p in apiProjects" :key="p.id" :value="p.id">{{ p.name }}</vort-select-option>
                            </vort-select>
                        </div>
                    </TableCell>
                </template>

                <template #startAt="{ text, record }">
                    <TableCell @click.stop="toggleDateFieldPicker(record, 'startAt')">
                        <div class="relative inline-block" @click.stop>
                            <span
                                v-if="openDateFieldFor !== `${getInteractiveCellKey(record)}:startAt`"
                                class="text-sm cursor-pointer"
                                @click.stop="toggleDateFieldPicker(record, 'startAt')"
                            >
                                {{ text || "-" }}
                            </span>
                            <vort-date-picker
                                v-else
                                v-model="record.startAt"
                                :open="dateFieldPickerOpen"
                                value-format="YYYY-MM-DD"
                                format="YYYY-MM-DD"
                                allow-clear
                                class="date-field-picker"
                                @change="(value: any) => selectRowDateField(record, 'startAt', value || '')"
                                @open-change="(open: boolean) => onDateFieldPickerOpenChange(record, 'startAt', open)"
                                @click.stop
                            />
                        </div>
                    </TableCell>
                </template>

                <template #endAt="{ text, record }">
                    <TableCell @click.stop="toggleDateFieldPicker(record, 'endAt')">
                        <div class="relative inline-block" @click.stop>
                            <span
                                v-if="openDateFieldFor !== `${getInteractiveCellKey(record)}:endAt`"
                                class="text-sm cursor-pointer"
                                @click.stop="toggleDateFieldPicker(record, 'endAt')"
                            >
                                {{ text || "-" }}
                            </span>
                            <vort-date-picker
                                v-else
                                v-model="record.endAt"
                                :open="dateFieldPickerOpen"
                                value-format="YYYY-MM-DD"
                                format="YYYY-MM-DD"
                                allow-clear
                                class="date-field-picker"
                                @change="(value: any) => selectRowDateField(record, 'endAt', value || '')"
                                @open-change="(open: boolean) => onDateFieldPickerOpenChange(record, 'endAt', open)"
                                @click.stop
                            />
                        </div>
                    </TableCell>
                </template>

                <template #testTime="{ text, record }">
                    <TableCell @click.stop="toggleDateFieldPicker(record, 'testTime')">
                        <div class="relative inline-block" @click.stop>
                            <span
                                v-if="openDateFieldFor !== `${getInteractiveCellKey(record)}:testTime`"
                                class="text-sm cursor-pointer"
                                @click.stop="toggleDateFieldPicker(record, 'testTime')"
                            >
                                {{ text || "-" }}
                            </span>
                            <vort-date-picker
                                v-else
                                v-model="record.testTime"
                                :open="dateFieldPickerOpen"
                                value-format="YYYY-MM-DD"
                                format="YYYY-MM-DD"
                                allow-clear
                                class="date-field-picker"
                                @change="(value: any) => selectRowDateField(record, 'testTime', value || '')"
                                @open-change="(open: boolean) => onDateFieldPickerOpenChange(record, 'testTime', open)"
                                @click.stop
                            />
                        </div>
                    </TableCell>
                </template>

                <template #draftTime="{ text, record }">
                    <TableCell @click.stop="toggleDateFieldPicker(record, 'draftTime')">
                        <div class="relative inline-block" @click.stop>
                            <span
                                v-if="openDateFieldFor !== `${getInteractiveCellKey(record)}:draftTime`"
                                class="text-sm cursor-pointer"
                                @click.stop="toggleDateFieldPicker(record, 'draftTime')"
                            >
                                {{ text || "-" }}
                            </span>
                            <vort-date-picker
                                v-else
                                v-model="record.draftTime"
                                :open="dateFieldPickerOpen"
                                value-format="YYYY-MM-DD"
                                format="YYYY-MM-DD"
                                allow-clear
                                class="date-field-picker"
                                @change="(value: any) => selectRowDateField(record, 'draftTime', value || '')"
                                @open-change="(open: boolean) => onDateFieldPickerOpenChange(record, 'draftTime', open)"
                                @click.stop
                            />
                        </div>
                    </TableCell>
                </template>

                <template #releaseTime="{ text, record }">
                    <TableCell @click.stop="toggleDateFieldPicker(record, 'releaseTime')">
                        <div class="relative inline-block" @click.stop>
                            <span
                                v-if="openDateFieldFor !== `${getInteractiveCellKey(record)}:releaseTime`"
                                class="text-sm cursor-pointer"
                                @click.stop="toggleDateFieldPicker(record, 'releaseTime')"
                            >
                                {{ text || "-" }}
                            </span>
                            <vort-date-picker
                                v-else
                                v-model="record.releaseTime"
                                :open="dateFieldPickerOpen"
                                value-format="YYYY-MM-DD"
                                format="YYYY-MM-DD"
                                allow-clear
                                class="date-field-picker"
                                @change="(value: any) => selectRowDateField(record, 'releaseTime', value || '')"
                                @open-change="(open: boolean) => onDateFieldPickerOpenChange(record, 'releaseTime', open)"
                                @click.stop
                            />
                        </div>
                    </TableCell>
                </template>

                <template #repo="{ text, record }">
                    <TableCell @click="openRepoPicker(record, $event)">
                        <vort-select
                            :model-value="record.repoId || ''"
                            :open="repoPickerOpenMap[getInteractiveCellKey(record)]"
                            placeholder="未设置"
                            allow-clear
                            :bordered="false"
                            size="small"
                            class="w-full min-w-0"
                            @update:open="(open: boolean) => { repoPickerOpenMap[getInteractiveCellKey(record)] = open; if (open) loadRepoOptions(); }"
                            @change="(value: string | number | (string | number)[] | undefined) => selectRowRepo(record, String(value || ''))"
                        >
                            <vort-select-option v-for="item in apiRepos" :key="item.id" :value="item.id">{{ item.name }}</vort-select-option>
                        </vort-select>
                    </TableCell>
                </template>

                <template #branch="{ text, record }">
                    <TableCell @click="openBranchPicker(record, $event)">
                        <vort-select
                            :model-value="record.branch || ''"
                            :open="branchPickerOpenMap[getInteractiveCellKey(record)]"
                            :placeholder="record.repoId ? (branchLoadingMap[record.repoId] ? '分支加载中' : '未设置') : '请先选择仓库'"
                            allow-clear
                            :disabled="!record.repoId"
                            :bordered="false"
                            size="small"
                            class="w-full min-w-0"
                            @update:open="(open: boolean) => { branchPickerOpenMap[getInteractiveCellKey(record)] = open; if (open) loadBranchOptions(record.repoId); }"
                            @change="(value: string | number | (string | number)[] | undefined) => selectRowBranch(record, String(value || ''))"
                        >
                            <vort-select-option v-for="item in getBranchOptions(record.repoId)" :key="item.name" :value="item.name">{{ item.name }}</vort-select-option>
                        </vort-select>
                    </TableCell>
                </template>
            </ProTable>
                </div>
                <template v-if="isGanttMode && tableFirstLoaded">
                    <GanttDivider
                        @drag="onGanttDividerDrag"
                        @drag-end="onGanttDividerDragEnd"
                    />
                    <GanttTimeline
                        ref="ganttTimelineRef"
                        :rows="ganttRows"
                        :row-tops="ganttRowTops"
                        :row-heights="ganttRowHeights"
                        :body-height="ganttBodyHeight"
                        :table-header-height="ganttTableHeaderHeight"
                        :row-height="GANTT_ROW_HEIGHT"
                        :zoom-level="ganttZoomLevel"
                        :can-undo="ganttCanUndo"
                        :can-redo="ganttCanRedo"
                        @update:zoom-level="(v: GanttZoomLevel) => ganttZoomLevel = v"
                        @time-change="handleGanttTimeChange"
                        @progress-change="handleGanttProgressChange"
                        @create-time="handleGanttCreateTime"
                        @clear-date="handleGanttClearDate"
                        @icon-time-change="handleGanttIconTimeChange"
                        @clear-icon-time="handleGanttClearIconTime"
                        @undo="handleGanttUndoAction"
                        @redo="handleGanttRedoAction"
                    />
                </template>
            </div>

            <div v-if="isGanttMode && ganttPaginationTotal > 0" class="gantt-pagination-footer">
                <Pagination
                    :current="ganttPaginationCurrent"
                    :page-size="ganttPaginationPageSize"
                    :total="ganttPaginationTotal"
                    :show-size-changer="true"
                    :show-quick-jumper="true"
                    :page-size-options="[10, 20, 50]"
                    @update:current="handleGanttPageChange"
                    @update:page-size="handleGanttPageSizeChange"
                />
            </div>
        </div>

        <vort-drawer
            v-model:open="createBugDrawerOpen"
            :title="createBugDrawerMode === 'create' ? createDrawerTitleText : props.detailDrawerTitle"
            :width="1180"
            :body-style="{ padding: '16px 20px 20px' }"
        >
            <template v-if="createBugDrawerMode === 'detail'">
                <WorkItemDetail
                    v-if="detailCurrentRecord"
                    ref="detailComponentRef"
                    :work-no="detailCurrentRecord.workNo"
                    :initial-data="detailCurrentRecord"
                    :parent-record="detailParentRecord"
                    :child-records="detailChildRecords"
                    :initial-desc-editing="detailDescEditing"
                    :initial-desc-draft="detailDescDraft"
                    @close="handleCancelCreateBug"
                    @update="handleDetailUpdate"
                    @delete="handleDetailDelete"
                    @copy="handleCopyWorkItem"
                    @open-related="handleOpenRelated"
                    @create-child="handleCreateChild"
                    @unlink-child="handleUnlinkChild"
                />
            </template>
            <template v-else>
                <WorkItemCreate
                    ref="createWorkItemRef"
                    :type="(props.type || createBugForm.type || '缺陷') as WorkItemType"
                    :title="createDrawerTitleText"
                    :use-api="props.useApi"
                    :project-id="createProjectId"
                    :project-ids="props.projectIds"
                    :parent-id="createParentItemId"
                    :parent-record="createParentRecord"
                    :iteration-id="props.iterationId"
                    :initial-draft="createDraftData"
                    @close="handleCancelCreateBug"
                    @success="handleCreateSuccess"
                    @iteration-options="mergeIterationOptions"
                />
            </template>
            <template #footer>
                <div v-if="createBugDrawerMode === 'create'" class="create-bug-footer">
                    <VortButton
                        variant="primary"
                        :loading="isCreating"
                        :disabled="isCreating"
                        @click="handleSubmitCreateBug()"
                    >
                        新建
                    </VortButton>
                    <VortButton :disabled="isCreating" @click="handleSubmitCreateBug(true)">新建并继续</VortButton>
                    <VortButton :disabled="isCreating" @click="handleCancelCreateWorkItem">取消</VortButton>
                </div>
            </template>
        </vort-drawer>

        <TagEditDialog
            v-model:open="tagDialogOpen"
            :mode="tagDialogMode"
            :data="tagDialogData"
            @saved="handleTagDialogSaved"
        />

        <ImportDialog v-model:open="importDialogOpen" :project-id="props.projectId" @done="tableRef?.refresh?.()" />
        <ImportRecordDialog v-model:open="importRecordDialogOpen" />
        <BatchPropertyEditor
            v-model:open="batchPropertyEditorOpen"
            :selected-rows="selectedRows"
            :work-item-type="(props.type || '缺陷') as WorkItemType"
            :status-options="currentStatusFilterOptions"
            @done="handleBatchDone"
        />
        <ViewManageDialog
            v-model:open="viewManageOpen"
            :work-item-type="props.type || ''"
            :current-filters="currentViewStateForCreate.filters"
            :current-columns="currentViewStateForCreate.cols"
        />
        <ViewCreateDialog v-model:open="viewCreateOpen" @create="handleCreateViewFromDialog" />
        <ViewCreateDialog v-model:open="saveViewDialogOpen" @create="handleSaveAsNewView" />
        <ColumnSettingsDialog
            v-model:open="columnSettingsOpen"
            :all-columns="columnSettingsForDialog"
            @save="handleColumnSettingsSave"
        />
    </div>
</template>

<style scoped>
@reference "../../assets/styles/index.css";

.progress-cell {
    @apply flex items-center gap-2;
}
.progress-bar {
    @apply flex-1 h-2 rounded-full overflow-hidden;
    background-color: var(--vort-bg-secondary, #f0f0f0);
    min-width: 60px;
}
.progress-fill {
    @apply h-full rounded-full transition-all duration-200;
    background-color: #22c55e;
}
.progress-text {
    @apply text-sm text-gray-600 whitespace-nowrap;
    min-width: 36px;
}

.title-link-cell {
    @apply flex items-center justify-start gap-2 cursor-pointer max-w-full !p-0 !h-auto !bg-transparent;
}

.title-link-text {
    @apply truncate text-blue-600 hover:underline;
}

.title-overdue-tag {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    font-size: 11px;
    font-weight: 500;
    line-height: 18px;
    padding: 0 6px;
    border-radius: 9px;
    color: #dc2626;
    background: #fef2f2;
    white-space: nowrap;
}

.include-archived-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: #4b5563;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}

/* 归档行视觉弱化：标题置灰，配合「已归档」徽标提示不可编辑 */
.title-link-text.is-archived-text {
    color: #9ca3af !important;
}
.title-link-text.is-archived-text:hover {
    text-decoration: none;
}

.title-archived-tag {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    font-weight: 500;
    line-height: 18px;
    padding: 0 6px;
    border-radius: 9px;
    color: #6b7280;
    background: rgba(107, 114, 128, 0.12);
    white-space: nowrap;
}

.title-overdue-icon {
    width: 12px;
    height: 12px;
    flex-shrink: 0;
}
.title-overdue-tag.is-done {
    color: #d97706;
    background: #fffbeb;
}

.title-stale-tag {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    font-size: 11px;
    font-weight: 500;
    line-height: 18px;
    padding: 0 6px;
    border-radius: 9px;
    color: #4b5563;
    background: rgba(107, 114, 128, 0.12);
    white-space: nowrap;
}

.title-stale-icon {
    width: 12px;
    height: 12px;
    flex-shrink: 0;
}

.story-expand-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    color: var(--vort-text-tertiary, rgba(0, 0, 0, 0.45));
    transition: transform 0.2s ease, color 0.2s ease;
    flex-shrink: 0;
}

.story-expand-toggle svg {
    width: 18px;
    height: 18px;
    transform: rotate(-90deg);
    transition: transform 0.2s ease;
}

.story-expand-toggle.expanded svg {
    transform: rotate(0deg);
}

.story-expand-toggle.expanded {
    transform: none;
}

.story-expand-toggle.loading {
    pointer-events: none;
}

.story-expand-toggle.loading svg {
    animation: story-expand-spin 0.8s linear infinite;
}

.story-expand-placeholder {
    display: inline-block;
    width: 20px;
    flex-shrink: 0;
}

.story-child-indent {
    display: inline-block;
    width: 20px;
    flex-shrink: 0;
}

@keyframes story-expand-spin {
    from {
        transform: rotate(-90deg);
    }
    to {
        transform: rotate(270deg);
    }
}

.work-type-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 3px;
    font-size: 12px;
    color: #fff;
    flex-shrink: 0;
}

.work-type-icon-demand {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
}

.work-type-icon-task {
    background: linear-gradient(135deg, #0ea5e9 0%, #06b6d4 100%);
}

.work-type-icon-bug {
    background: linear-gradient(135deg, #ef4444 0%, #f97316 100%);
}

.story-child-text {
    padding-left: 0;
}

.story-children-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 20px;
    height: 20px;
    padding: 0 6px;
    margin-left: 6px;
    border-radius: 999px;
    background: rgba(99, 102, 241, 0.12);
    color: #4f46e5;
    font-size: 12px;
    line-height: 20px;
}

.plan-time-overdue {
    margin-left: 6px;
    font-size: 12px;
    font-weight: 500;
    color: #dc2626;
    white-space: nowrap;
}
.plan-time-overdue.is-done {
    color: #d97706;
}

:deep(.plan-time-picker) {
    max-width: 260px;
    border-color: transparent !important;
    .vort-rangepicker-prefix{
        display: none;
    }
    .vort-rangepicker-separator{
    padding: 0 4px;
    }
    .vort-rangepicker-input{
    font-size: 13px;

    }
}

:deep(.date-field-picker) {
    max-width: 160px;
    border-color: transparent !important;
    box-shadow: none !important;
    padding-left: 0;
    margin-left: -1px;
    background-color: transparent !important;
    .vort-datepicker-selector {
        border-color: transparent !important;
        box-shadow: none !important;
    }
    .vort-datepicker-value{
        font-size: 14px !important;
    }
    .vort-datepicker-prefix {
        display: none;
    }
    .vort-datepicker-value {
        font-size: 13px;
    }
}

.create-bug-footer {
    display: flex;
    gap: 12px;
}

.column-settings-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fff;
    cursor: pointer;
    color: #666;
    transition: all 0.2s;
}
.column-settings-btn:hover {
    border-color: var(--vort-primary, #1456f0);
    color: var(--vort-primary, #1456f0);
    background: var(--vort-primary-bg, rgba(20, 86, 240, 0.04));
}

.save-view-wrapper {
    position: relative;
}

.save-view-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 32px;
    padding: 0 10px;
    border: 1px solid var(--vort-primary, #1456f0);
    border-radius: 6px;
    background: #fff;
    color: var(--vort-primary, #1456f0);
    font-size: 13px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.2s;
}
.save-view-btn:hover {
    background: var(--vort-primary-bg, rgba(20, 86, 240, 0.04));
}

.save-view-arrow {
    transition: transform 0.2s;
}
.save-view-arrow.open {
    transform: rotate(180deg);
}

.save-view-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    min-width: 150px;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12);
    padding: 4px;
    z-index: 50;
}

.save-view-option {
    display: block;
    width: 100%;
    padding: 8px 12px;
    border: none;
    background: transparent;
    text-align: left;
    font-size: 14px;
    color: #1e293b;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
}
.save-view-option:hover:not(:disabled) {
    background: rgba(0, 0, 0, 0.04);
}
.save-view-option:disabled {
    color: #c0c4cc;
    cursor: not-allowed;
}

.dropdown-enter-active,
.dropdown-leave-active {
    transition: opacity 0.15s, transform 0.15s;
}
.dropdown-enter-from,
.dropdown-leave-to {
    opacity: 0;
    transform: translateY(-4px);
}

.cell-select-plain {
    width: 100%;
}

/* ===== Gantt layout ===== */

.gantt-layout-container {
    overflow: hidden;
}

.gantt-split-layout {
    display: flex;
    /* height: calc(100vh - 240px); */
    min-height: 400px;
    overflow-y: auto;
    overflow-x: hidden;
}

.gantt-table-pane {
    flex-shrink: 0;
    overflow: hidden;
    position: relative;
}

.gantt-table-pane::after {
    content: '';
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: 8px;
    background: linear-gradient(to left, rgba(0, 0, 0, 0.06), transparent);
    pointer-events: none;
    z-index: 20;
}

/* Force table header sticky inside the shared scroll container */
.gantt-table-pane :deep(.vort-pro-table-thead th) {
    position: sticky;
    top: 0;
    z-index: 10;
    background: var(--vort-table-header-bg, #fafafa);
}

/* Force fixed row height in gantt mode */
.gantt-table-pane :deep(.vort-pro-table-tbody tr) {
    height: 50px;
}

.gantt-table-pane :deep(.vort-pro-table-tbody td) {
    height: 50px;
    max-height: 50px;
    overflow: hidden;
    box-sizing: border-box;
}

/* Hide pagination inside the table pane; it shows in the normal flow below */
.gantt-table-pane :deep(.vort-pro-table-pagination) {
    display: none;
}

.gantt-pagination-footer {
    display: flex;
    justify-content: flex-end;
    padding: 12px 16px;
    border-top: 1px solid #e5e7eb;
}

/* Keep horizontal scroll for the table, only disable vertical */
.gantt-table-pane :deep(.vort-pro-table-scroll) {
    overflow-x: auto !important;
    overflow-y: hidden !important;
}

/* ===== Story drag & drop ===== */

/*
 * Drag handle 始终预占位（width:12px），避免 hover 时挤动工作编号文字。
 * 默认低对比度（淡灰），行 hover 颜色加深，手柄本身 hover 变主题蓝。
 */
.story-drag-handle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 12px;
    height: 18px;
    margin-right: 6px;
    border-radius: 3px;
    color: #d8dde5;
    cursor: grab;
    flex-shrink: 0;
    user-select: none;
    transition: color 0.15s ease, background 0.15s ease;
}
:deep(.vort-pro-table-row:hover) .story-drag-handle {
    color: #94a3b8;
}
.story-drag-handle:hover {
    color: var(--vort-primary, #1456f0);
    background: rgba(20, 86, 240, 0.08);
}
.story-drag-handle:active {
    cursor: grabbing;
}

/*
 * Drop cell 占位线
 * 用 ::before（绕开 TableCell 自带的 ::after hover 边框），absolute 横向溢出 cell 形成贯穿整行的横线。
 * - before:   行上沿一条蓝色细线
 * - after:    行下沿一条蓝色细线
 * - inside:   cell 浅蓝高亮（嵌入为子需求）
 * - forbidden: 红色细线 + 浅红背景
 */
.story-drop-cell {
    position: relative;
}
.story-drop-cell::before {
    content: "";
    position: absolute;
    left: 0;
    width: 9999px;
    height: 1px;
    pointer-events: none;
    z-index: 5;
    background: transparent;
    transition: background 0.1s ease;
}
.story-drop-cell.story-drop-before::before {
    top: -1px;
    background: var(--vort-primary, #1456f0);
}
.story-drop-cell.story-drop-after::before {
    top: auto;
    bottom: -1px;
    background: var(--vort-primary, #1456f0);
}
.story-drop-cell.story-drop-inside {
    background: rgba(20, 86, 240, 0.08);
    box-shadow: inset 0 0 0 1px rgba(20, 86, 240, 0.35);
}
.story-drop-cell.story-drop-forbidden {
    cursor: not-allowed;
    background: rgba(239, 68, 68, 0.04);
}
.story-drop-cell.story-drop-forbidden::before {
    top: auto;
    bottom: -1px;
    background: #ef4444;
}

</style>

<style>
.cell-select-plain .vort-select-suffix {
    display: none !important;
}
.cell-select-plain .vort-select-value {
    color: inherit !important;
    font-size: inherit !important;
}
.cell-select-plain .vort-select-placeholder {
    color: #d1d5db !important;
    font-size: inherit !important;
}
</style>
