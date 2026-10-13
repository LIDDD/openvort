import { computed, nextTick, onScopeDispose, ref, watch, type ComputedRef, type Ref } from "vue";
import dayjs from "dayjs";
import type { GanttTimeline } from "../gantt";
import type { GanttZoomLevel } from "../gantt";
import { useGanttUndo, type GanttUndoSnapshot } from "../gantt/useGanttUndo";
import type { RowItem } from "@/components/vort-biz/work-item/WorkItemTable.types";

type GanttTimelineInstance = InstanceType<typeof GanttTimeline>;

type ViewMode = "list" | "gantt";

export interface UseWorkItemGanttOptions {
    /** 双向绑定的 store 视图模式（视图模式 / 缩放级别 / 分页 / 分隔条比例） */
    viewMode: Ref<ViewMode>;
    ganttZoomLevel: Ref<GanttZoomLevel>;
    tablePageSize: Ref<number>;
    ganttDividerRatio: Ref<number>;

    /** ProTable 实例引用（提供 dataSource / current / pageSize / refresh 等） */
    tableRef: Ref<any>;
    /** 行数据查找（按 rowId 查 RowItem） */
    findItemRowByIdentifier: (rowId: string) => RowItem | null | undefined;
    /** 单字段保存（透传给 useWorkItemCrud.syncRecordUpdateToApi） */
    syncRecordUpdateToApi: (record: RowItem, patch: any) => Promise<void> | void;
    /** 在 ganttRows 计算时把 ProTable 原始 dataSource 经过项目级后处理 */
    postProcessTableRows?: (rows: RowItem[]) => RowItem[];
}

const GANTT_ROW_HEIGHT = 50;

/**
 * 工作项工作墙的「甘特视图」状态与交互。
 *
 * 抽离自 WorkItemTable.vue 阶段 D6：
 * - 视图模式 + 缩放级别 + 分页 + 分隔条比例（来自 store）
 * - 甘特容器/表格栏/时间轴的 DOM 引用，行高度测量（ResizeObserver）
 * - 甘特拖拽分隔条 + 滚动到今天
 * - 甘特行编辑联动（calendar/progress/iconTime/clearDate）+ Undo/Redo
 * - 甘特独立分页
 *
 * 依赖关系完全通过 options 注入：
 * - tableRef / findItemRowByIdentifier / syncRecordUpdateToApi 来自主组件
 * - undoStack 由 composable 内部维护
 */
export function useWorkItemGantt(opts: UseWorkItemGanttOptions) {
    const isGanttMode = computed(() => opts.viewMode.value === "gantt");

    const ganttLeftWidth = ref(0);
    const ganttContainerRef = ref<HTMLElement | null>(null);
    const ganttTablePaneRef = ref<HTMLElement | null>(null);
    const ganttTimelineRef = ref<GanttTimelineInstance | null>(null);
    const ganttNeedScrollToToday = ref(false);

    const ganttRowTops = ref<number[]>([]);
    const ganttRowHeights = ref<number[]>([]);
    const ganttBodyHeight = ref(0);
    const ganttTableHeaderHeight = ref(0);

    const tableFirstLoaded = ref(false);

    const {
        canUndo: ganttCanUndo,
        canRedo: ganttCanRedo,
        pushRecord: ganttPushUndo,
        undo: ganttUndo,
        redo: ganttRedo,
        reset: ganttResetUndo,
    } = useGanttUndo();

    let ganttResizeObs: ResizeObserver | null = null;

    const ganttRows = computed<RowItem[]>(() => {
        const t = opts.tableRef.value;
        if (!t) return [];
        const raw = t.dataSource as RowItem[] | undefined;
        return raw && opts.postProcessTableRows ? opts.postProcessTableRows(raw) : (raw || []);
    });

    function measureGanttPositions() {
        const pane = ganttTablePaneRef.value;
        if (!pane || !isGanttMode.value) return;

        const thead = pane.querySelector(".vort-pro-table-thead");
        if (thead) ganttTableHeaderHeight.value = thead.getBoundingClientRect().height;

        const tbody = pane.querySelector(".vort-pro-table-tbody");
        if (!tbody) return;
        const rows = Array.from(tbody.children).filter((el) => el.tagName === "TR");
        const tops: number[] = [];
        const heights: number[] = [];
        let cumTop = 0;
        for (const row of rows) {
            const h = (row as HTMLElement).offsetHeight;
            tops.push(cumTop);
            heights.push(h);
            cumTop += h;
        }
        ganttRowTops.value = tops;
        ganttRowHeights.value = heights;
        ganttBodyHeight.value = cumTop;
    }

    function setupGanttObserver() {
        ganttResizeObs?.disconnect();
        const pane = ganttTablePaneRef.value;
        if (!pane) return;
        const tbody = pane.querySelector(".vort-pro-table-tbody");
        if (!tbody) return;
        ganttResizeObs = new ResizeObserver(() => { measureGanttPositions(); });
        ganttResizeObs.observe(tbody);
    }

    onScopeDispose(() => {
        ganttResizeObs?.disconnect();
        ganttResizeObs = null;
    });

    watch(isGanttMode, (v) => {
        if (v) nextTick(() => { setupGanttObserver(); measureGanttPositions(); });
        else { ganttResizeObs?.disconnect(); ganttResetUndo(); }
    });

    watch(ganttRows, () => {
        if (isGanttMode.value) nextTick(measureGanttPositions);
        if (ganttNeedScrollToToday.value) {
            ganttNeedScrollToToday.value = false;
            nextTick(() => ganttTimelineRef.value?.scrollToToday());
        }
    }, { deep: false });

    watch(tableFirstLoaded, (loaded) => {
        if (loaded && isGanttMode.value) {
            nextTick(() => { initGanttWidth(); setupGanttObserver(); measureGanttPositions(); });
        }
    });

    function initGanttWidth() {
        if (!ganttContainerRef.value) return;
        const totalW = ganttContainerRef.value.clientWidth;
        ganttLeftWidth.value = Math.round(totalW * opts.ganttDividerRatio.value);
    }

    function onGanttDividerDrag(delta: number) {
        if (!ganttContainerRef.value) return;
        const totalW = ganttContainerRef.value.clientWidth;
        const minW = 300;
        const maxW = totalW - 300;
        ganttLeftWidth.value = Math.max(minW, Math.min(maxW, ganttLeftWidth.value + delta));
    }

    function onGanttDividerDragEnd() {
        if (!ganttContainerRef.value) return;
        const totalW = ganttContainerRef.value.clientWidth;
        if (totalW > 0) opts.ganttDividerRatio.value = ganttLeftWidth.value / totalW;
    }

    function snapshotRow(rowId: string, record: RowItem): GanttUndoSnapshot {
        return {
            rowId,
            planStartDate: record.planStartDate || "",
            planEndDate: record.planEndDate || "",
            progress: record.progress ?? 0,
            testTime: record.testTime || "",
            draftTime: record.draftTime || "",
            releaseTime: record.releaseTime || "",
        };
    }

    function applyGanttSnapshot(s: GanttUndoSnapshot) {
        const record = opts.findItemRowByIdentifier(s.rowId);
        if (!record) return;
        record.planStartDate = s.planStartDate;
        record.planEndDate = s.planEndDate;
        record.planTime = [s.planStartDate, s.planEndDate];
        record.progress = s.progress;
        const patch: any = {
            plan_start: s.planStartDate || "",
            deadline: s.planEndDate || "",
            progress: s.progress,
        };
        if (record.type === "需求") {
            record.testTime = s.testTime || "";
            record.draftTime = s.draftTime || "";
            record.releaseTime = s.releaseTime || "";
            patch.test_time = s.testTime || "";
            patch.draft_time = s.draftTime || "";
            patch.release_time = s.releaseTime || "";
        }
        opts.syncRecordUpdateToApi(record, patch);
    }

    function handleGanttUndoAction() {
        const snapshot = ganttUndo();
        if (snapshot) applyGanttSnapshot(snapshot);
    }

    function handleGanttRedoAction() {
        const snapshot = ganttRedo();
        if (snapshot) applyGanttSnapshot(snapshot);
    }

    function handleGanttTimeChange(rowId: string, startDate: string, endDate: string) {
        const record = opts.findItemRowByIdentifier(rowId);
        if (!record) return;
        const prev = snapshotRow(rowId, record);
        const patch: any = {};
        const oldEnd = record.planTime?.[1] || "";
        if (record.planTime?.[0] !== startDate || oldEnd !== endDate) {
            record.planTime = [startDate, endDate];
            record.planStartDate = startDate;
            record.planEndDate = endDate;
            patch.plan_start = startDate;
            patch.deadline = endDate;
        }
        if (oldEnd && endDate && record.type === "需求") {
            const deltaDays = dayjs(endDate).diff(dayjs(oldEnd), "day");
            if (deltaDays !== 0) {
                const minDate = dayjs(startDate);
                if (record.testTime) {
                    let newTestTime = dayjs(record.testTime).add(deltaDays, "day");
                    if (newTestTime.isBefore(minDate)) newTestTime = minDate;
                    record.testTime = newTestTime.format("YYYY-MM-DD");
                    patch.test_time = record.testTime;
                }
                if (record.draftTime) {
                    let newDraftTime = dayjs(record.draftTime).add(deltaDays, "day");
                    if (newDraftTime.isBefore(minDate)) newDraftTime = minDate;
                    record.draftTime = newDraftTime.format("YYYY-MM-DD");
                    patch.draft_time = record.draftTime;
                }
                if (record.releaseTime) {
                    let newReleaseTime = dayjs(record.releaseTime).add(deltaDays, "day");
                    if (newReleaseTime.isBefore(minDate)) newReleaseTime = minDate;
                    record.releaseTime = newReleaseTime.format("YYYY-MM-DD");
                    patch.release_time = record.releaseTime;
                }
            }
        }
        if (Object.keys(patch).length) {
            opts.syncRecordUpdateToApi(record, patch);
            ganttPushUndo({ prev, next: snapshotRow(rowId, record) });
        }
    }

    const ICON_TIME_API_FIELD = {
        testTime: "test_time",
        draftTime: "draft_time",
        releaseTime: "release_time",
    } as const;

    function handleGanttIconTimeChange(rowId: string, field: "testTime" | "draftTime" | "releaseTime", date: string) {
        const record = opts.findItemRowByIdentifier(rowId);
        if (!record || record.type !== "需求") return;
        const prev = snapshotRow(rowId, record);
        record[field] = date;
        opts.syncRecordUpdateToApi(record, { [ICON_TIME_API_FIELD[field]]: date });
        ganttPushUndo({ prev, next: snapshotRow(rowId, record) });
    }

    function handleGanttClearIconTime(rowId: string, field: "testTime" | "draftTime" | "releaseTime") {
        const record = opts.findItemRowByIdentifier(rowId);
        if (!record || record.type !== "需求") return;
        const prev = snapshotRow(rowId, record);
        record[field] = "";
        opts.syncRecordUpdateToApi(record, { [ICON_TIME_API_FIELD[field]]: "" });
        ganttPushUndo({ prev, next: snapshotRow(rowId, record) });
    }

    function handleGanttProgressChange(rowId: string, progress: number) {
        const record = opts.findItemRowByIdentifier(rowId);
        if (!record) return;
        const prev = snapshotRow(rowId, record);
        record.progress = progress;
        opts.syncRecordUpdateToApi(record, { progress });
        ganttPushUndo({ prev, next: snapshotRow(rowId, record) });
    }

    function handleGanttCreateTime(rowId: string, startDate: string, endDate: string) {
        const record = opts.findItemRowByIdentifier(rowId);
        if (!record) return;
        const prev = snapshotRow(rowId, record);
        record.planTime = [startDate, endDate];
        record.planStartDate = startDate;
        record.planEndDate = endDate;
        opts.syncRecordUpdateToApi(record, { plan_start: startDate, deadline: endDate });
        ganttPushUndo({ prev, next: snapshotRow(rowId, record) });
    }

    function handleGanttClearDate(rowId: string, type: "start" | "end" | "both") {
        const record = opts.findItemRowByIdentifier(rowId);
        if (!record) return;
        const prev = snapshotRow(rowId, record);
        const patch: Record<string, any> = {};
        if (type === "start" || type === "both") {
            record.planStartDate = "";
            patch.plan_start = "";
        }
        if (type === "end" || type === "both") {
            record.planEndDate = "";
            patch.deadline = "";
        }
        record.planTime = [record.planStartDate || "", record.planEndDate || ""];
        opts.syncRecordUpdateToApi(record, patch);
        ganttPushUndo({ prev, next: snapshotRow(rowId, record) });
    }

    /** ProTable 数据源加载完成（首次或刷新）后，由主组件 ganttRequest 通知 */
    const markTableFirstLoaded = () => {
        if (!tableFirstLoaded.value) tableFirstLoaded.value = true;
    };

    const ganttPaginationTotal: ComputedRef<number> = computed(() => opts.tableRef.value?.total ?? 0);
    const ganttPaginationCurrent: ComputedRef<number> = computed(() => opts.tableRef.value?.current ?? 1);
    const ganttPaginationPageSize: ComputedRef<number> = computed(() => opts.tableRef.value?.pageSize ?? opts.tablePageSize.value);

    function handleGanttPageChange(page: number) {
        const t = opts.tableRef.value;
        if (!t) return;
        t.current = page;
        ganttNeedScrollToToday.value = true;
        ganttResetUndo();
        t.refresh();
    }

    function handleGanttPageSizeChange(size: number) {
        const t = opts.tableRef.value;
        if (!t) return;
        t.pageSize = size;
        t.current = 1;
        opts.tablePageSize.value = size;
        ganttNeedScrollToToday.value = true;
        ganttResetUndo();
        t.refresh();
    }

    return {
        // 常量
        GANTT_ROW_HEIGHT,
        // 模式 / 状态
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
        // 测量 / 监听
        measureGanttPositions,
        setupGanttObserver,
        markTableFirstLoaded,
        // 分隔条
        initGanttWidth,
        onGanttDividerDrag,
        onGanttDividerDragEnd,
        // Undo
        ganttCanUndo,
        ganttCanRedo,
        ganttResetUndo,
        handleGanttUndoAction,
        handleGanttRedoAction,
        // 行编辑联动
        handleGanttTimeChange,
        handleGanttIconTimeChange,
        handleGanttClearIconTime,
        handleGanttProgressChange,
        handleGanttCreateTime,
        handleGanttClearDate,
        // 分页
        ganttPaginationTotal,
        ganttPaginationCurrent,
        ganttPaginationPageSize,
        handleGanttPageChange,
        handleGanttPageSizeChange,
    };
}
