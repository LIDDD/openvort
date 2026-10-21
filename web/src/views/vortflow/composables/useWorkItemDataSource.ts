import { reactive, ref } from "vue";
import type { Ref, ComputedRef } from "vue";
import type { ProTableRequestParams, ProTableResponse } from "@/components/vort-biz";
import type { ColumnFilterValue } from "@/components/vort-biz/pro-table/ColumnFilterPopover.vue";
import type {
    WorkItemType,
    RowItem,
    Status,
} from "@/components/vort-biz/work-item/WorkItemTable.types";
import {
    getVortflowStory, getVortflowStories,
    getVortflowTask, getVortflowTasks,
    getVortflowBug, getVortflowBugs,
    getVortflowWorkItems,
} from "@/api";
import {
    COMPLETED_TODAY_STATUS_VALUE,
    OVERDUE_STALE_STATUS_VALUE,
    OVERDUE_STATUS_VALUE,
    PENDING_STATUS_VALUE,
    STALE_STATUS_VALUE,
    getDoneBackendStates,
    getOverdueStaleSortKey,
    getPendingBackendStates,
    isCompletedDisplayStatus,
    isRowOverdue,
    isRowStale,
    isPendingDisplayStatus,
} from "@/views/vortflow/work-item/useWorkItemCommon";
import { compareWorkItemDate } from "@/views/vortflow/work-item/workItemSort";

// 虚拟状态值集合：不对应任何具体显示状态，行级匹配走专用谓词
const VIRTUAL_STATUS_VALUES = new Set<string>([
    PENDING_STATUS_VALUE,
    COMPLETED_TODAY_STATUS_VALUE,
    OVERDUE_STATUS_VALUE,
    STALE_STATUS_VALUE,
    OVERDUE_STALE_STATUS_VALUE,
]);

/** 从状态筛选值中解析虚拟状态开关（legacy 合并值展开为 逾期+停滞） */
function parseVirtualStatusFlags(values: string[]) {
    const hasLegacyOverdueStale = values.includes(OVERDUE_STALE_STATUS_VALUE);
    return {
        hasPending: values.includes(PENDING_STATUS_VALUE),
        hasCompletedToday: values.includes(COMPLETED_TODAY_STATUS_VALUE),
        hasOverdue: values.includes(OVERDUE_STATUS_VALUE) || hasLegacyOverdueStale,
        hasStale: values.includes(STALE_STATUS_VALUE) || hasLegacyOverdueStale,
    };
}

/** 行级「当日已完成」判断：完成态且 end_at 为今天（本地时区） */
function isRowCompletedToday(row: RowItem): boolean {
    if (!row.endAt) return false;
    const done = row._stateRaw
        ? getDoneBackendStates(row.type).includes(row._stateRaw)
        : isCompletedDisplayStatus(row.type, row.status);
    if (!done) return false;
    const t = new Date();
    const todayKey = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
    return row.endAt === todayKey;
}

// 跨类型映射（工作墙）
const TYPE_BACKEND_TO_CN: Record<string, WorkItemType> = {
    story: "需求",
    task: "任务",
    bug: "缺陷",
};
const TYPE_CN_TO_BACKEND: Record<string, string> = {
    "需求": "story",
    "任务": "task",
    "缺陷": "bug",
};

export const SORT_FIELD_MAP: Record<string, string> = {
    createdAt: "created_at",
    updatedAt: "updated_at",
    priority: "priority",
    title: "title",
    status: "state",
    planTime: "deadline",
    owner: "assignee_id",
    creator: "creator_id",
    testTime: "test_time",
    draftTime: "draft_time",
    releaseTime: "release_time",
    // ProTable 内置 sorter 默认以 dataIndex 作为 field，project 列 dataIndex=projectName。
    // 前端把它映射到后端的 project_id 字段，让点击表头能真正按项目排序。
    project: "project_id",
    projectName: "project_id",
    // 工作编号 workNo 是前端从 backendId 派生（#XXXXXX = id 前 6 位 toUpperCase），
    // 因此按后端 id 排序结果与前端展示的工作编号顺序一致。
    workNo: "id",
    // 任务 / 缺陷 模型上有 estimate_hours 字段；需求模型没有，stories 接口会兜底为 priority_score。
    estimateHours: "estimate_hours",
};

export const SORT_FIELD_OVERRIDES: Record<string, Record<string, string>> = {
    // owner 全部按 assignee_id 排序，与 /members/workload 与列表 owner_id 口径对齐。
    "需求": { creator: "submitter_id" },
    "缺陷": { creator: "reporter_id" },
};

export interface UseWorkItemDataSourceOptions {
    useApi: ComputedRef<boolean> | Ref<boolean>;
    propType: string;
    propProjectId: ComputedRef<string> | Ref<string>;
    /** 多项目筛选范围；非空时优先于 propProjectId */
    propProjectIds?: ComputedRef<string[]> | Ref<string[]>;
    propIterationId: ComputedRef<string> | Ref<string>;
    propViewFilters: ComputedRef<Record<string, any>> | Ref<Record<string, any>>;
    type: Ref<WorkItemType[]>;
    owner: Ref<string[]>;
    status: Ref<string[]>;
    columnFilters: Record<string, ColumnFilterValue | null>;
    columnSortField: Ref<string>;
    columnSortOrder: Ref<"ascend" | "descend" | null>;
    totalCount: Ref<number>;
    apiProjects: Ref<Array<{ id: string; name: string }>>;
    pinnedRowsByType: Record<WorkItemType, RowItem[]>;
    expandedItemIds: Record<string, boolean>;
    expandingItemIds: Record<string, boolean>;
    itemRowsById: Record<string, RowItem>;
    itemChildrenMap: Record<string, RowItem[]>;
    getMemberIdByName: (name: string) => string;
    getMemberNameById: (id: string) => string;
    loadMemberOptions?: () => Promise<void>;
    mapBackendStateToStatus: (type: WorkItemType, state: string) => Status;
    mapBackendPriority: (item: any, type: WorkItemType) => any;
    mapBackendPriorityScore: (item: any, type: WorkItemType) => number;
    getBackendStatesByDisplayStatus: (type: WorkItemType, status: Status | string) => string[] | undefined;
    formatCnTime: (date: Date) => string;
    formatDate: (date: Date) => string;
    collectTagOptions: (rows: RowItem[]) => void;
    collectEnumOptions: (rows: RowItem[]) => void;
}

export function useWorkItemDataSource(options: UseWorkItemDataSourceOptions) {
    const {
        useApi,
        propType,
        propProjectId,
        propProjectIds,
        propIterationId,
        propViewFilters,
        type,
        owner,
        status,
        columnFilters,
        columnSortField,
        columnSortOrder,
        totalCount,
        apiProjects,
        pinnedRowsByType,
        expandedItemIds,
        itemRowsById,
        itemChildrenMap,
        getMemberIdByName,
        getMemberNameById,
        loadMemberOptions,
        mapBackendStateToStatus,
        mapBackendPriority,
        mapBackendPriorityScore,
        getBackendStatesByDisplayStatus,
        formatCnTime,
        formatDate,
        collectTagOptions,
        collectEnumOptions,
    } = options;

    // 归一化项目过滤参数：多选（project_ids）优先，其次单选（project_id）。
    // 两者皆空表示「全部项目」，不下发过滤参数。
    const buildProjectFilter = (): { project_id?: string; project_ids?: string } => {
        const ids = (propProjectIds?.value || []).filter(Boolean);
        if (ids.length) return { project_ids: ids.join(",") };
        const single = propProjectId.value || "";
        return single ? { project_id: single } : {};
    };

    // 当前是否处于跨多项目（含全部项目）视图：用于决定是否展示「所属项目」列
    const isMultiProjectView = (): boolean => {
        const ids = (propProjectIds?.value || []).filter(Boolean);
        if (ids.length) return ids.length > 1;
        return !propProjectId.value;
    };

    const getOwnerSourceId = (item: any, typeValue: WorkItemType): string => {
        // owner 口径与后端 /members/workload、/work-items 列表保持一致：
        // 需求 = assignee_id || pm_id；缺陷 = assignee_id || developer_id；任务 = assignee_id。
        // 历史上前端把 pm_id 当作主负责人，导致与后端工作量统计错位（如「副本」需求带着幽灵 assignee_id），
        // 现已统一以 assignee_id 为权威字段，pm_id 仅作为旧数据兜底。
        if (typeValue === "需求") {
            return String(item?.assignee_id || item?.pm_id || "").trim();
        }
        if (typeValue === "缺陷") {
            return String(item?.assignee_id || item?.developer_id || "").trim();
        }
        return String(item?.assignee_id || "").trim();
    };

    const mapBackendItemToRow = (item: any, typeValue: WorkItemType, index: number): RowItem => {
        const created = item?.created_at ? new Date(item.created_at) : new Date();
        const createdAt = formatCnTime(created);
        const planStart = item?.plan_start ? String(item.plan_start).split("T")[0] : "";
        const deadline = item?.deadline ? String(item.deadline).split("T")[0] : "";
        const backendId = String(item?.id || index + 1);
        const workNo = `#${backendId.replace(/-/g, "").slice(0, 6).toUpperCase().padEnd(6, "X")}`;
        const ownerSourceId = getOwnerSourceId(item, typeValue);
        const ownerSourceName = getMemberNameById(ownerSourceId);
        const ownerName = ownerSourceName || (ownerSourceId ? ownerSourceId : "未指派");

        const creatorSourceId = String(item?.submitter_id || item?.creator_id || item?.reporter_id || "").trim();
        const creatorName = getMemberNameById(creatorSourceId) || (creatorSourceId || "");

        const collaboratorIds = Array.isArray(item?.collaborators)
            ? (item.collaborators as any[]).map((x) => String(x || "").trim()).filter(Boolean)
            : [];
        const collaboratorsFromBackend = collaboratorIds.map((id) => getMemberNameById(id) || id);

        const tags: string[] = Array.isArray(item?.tags)
            ? (item.tags as any[]).map((x) => String(x || "").trim()).filter(Boolean)
            : [];

        const planStartDate = planStart || deadline || "";
        const planEndDate = deadline || "";
        const updated = item?.updated_at ? new Date(item.updated_at) : null;
        const updatedAt = updated ? formatCnTime(updated) : "";
        const estimateHours = item?.estimate_hours != null ? item.estimate_hours : undefined;
        const loggedHours = item?.actual_hours != null ? item.actual_hours : undefined;
        const remainHours = (estimateHours != null && loggedHours != null)
            ? Math.max(0, Number(estimateHours) - Number(loggedHours))
            : undefined;
        const iterationId = item?.iteration_id ? String(item.iteration_id) : "";
        const versionId = item?.version_id ? String(item.version_id) : "";
        const progress = item?.progress != null ? Number(item.progress) : 0;
        const startAt = item?.start_at ? String(item.start_at).split("T")[0] : "";
        const endAt = item?.end_at ? String(item.end_at).split("T")[0] : "";
        const testTime = item?.test_time ? String(item.test_time).split("T")[0] : "";
        const draftTime = item?.draft_time ? String(item.draft_time).split("T")[0] : "";
        const releaseTime = item?.release_time ? String(item.release_time).split("T")[0] : "";
        return {
            backendId,
            workNo,
            title: String(item?.title || ""),
            parentId: item?.parent_id ? String(item.parent_id) : "",
            parentTitle: "",
            childrenCount: Number(item?.children_count || 0),
            taskCount: Number(item?.task_count || 0),
            isChild: Boolean(item?.parent_id),
            sortOrder: item?.sort_order != null ? Number(item.sort_order) : null,
            priority: mapBackendPriority(item, typeValue),
            priorityScore: mapBackendPriorityScore(item, typeValue),
            tags,
            status: mapBackendStateToStatus(typeValue, String(item?.state || "")),
            createdAt,
            updatedAt,
            collaborators: collaboratorsFromBackend,
            collaboratorIds,
            type: typeValue,
            planTime: [planStartDate, planEndDate],
            planStartDate,
            planEndDate,
            description: item?.description || "",
            ownerId: ownerSourceId,
            owner: ownerName,
            creator: creatorName,
            projectId: item?.project_id ? String(item.project_id) : "",
            progress,
            projectName: item?.project_name
                ? String(item.project_name)
                : (item?.project_id ? (apiProjects.value.find(p => p.id === String(item.project_id))?.name || "") : ""),
            iterationId,
            iteration: item?.iteration_name ? String(item.iteration_name) : "",
            versionId,
            version: item?.version_name ? String(item.version_name) : "",
            estimateHours,
            loggedHours,
            remainHours,
            repoId: item?.repo_id ? String(item.repo_id) : "",
            repo: "",
            branch: item?.branch ? String(item.branch) : "",
            attachments: Array.isArray(item?.attachments) ? item.attachments : [],
            isArchived: Boolean(item?.is_archived),
            startAt,
            endAt,
            testTime,
            draftTime,
            releaseTime,
            _prevIteration: iterationId,
            _prevVersion: versionId,
            _stateRaw: item?.state ? String(item.state) : "",
            _createdAtRaw: item?.created_at ? String(item.created_at) : "",
            _updatedAtRaw: item?.updated_at ? String(item.updated_at) : "",
            _lastActivityAtRaw: item?.last_activity_at
                ? String(item.last_activity_at)
                : (item?.updated_at ? String(item.updated_at) : ""),
        };
    };

    const createOwnerMatcher = (ownerValues: string | string[]) => {
        const ownerArray = (Array.isArray(ownerValues) ? ownerValues : (ownerValues ? [ownerValues] : []))
            .map(v => String(v || "").trim())
            .filter(Boolean);
        const ownerMemberIds = ownerArray
            .filter(v => v !== "未指派")
            .map(v => getMemberIdByName(v))
            .filter(Boolean);
        const hasUnassigned = ownerArray.includes("未指派");
        const singleMemberId = ownerMemberIds.length === 1 && !hasUnassigned ? ownerMemberIds[0] : "";
        const matchOwner = (row: RowItem) => {
            if (!ownerArray.length) return true;
            const rowOwnerId = String(row.ownerId || "").trim();
            if (hasUnassigned && !rowOwnerId) return true;
            if (ownerMemberIds.length && ownerMemberIds.includes(rowOwnerId)) return true;
            if (ownerArray.includes(row.owner as string)) return true;
            return false;
        };
        return { ownerMemberId: singleMemberId, matchOwner };
    };

    const cacheItemRows = (rows: RowItem[]) => {
        for (const row of rows) {
            if (!row.backendId) continue;
            itemRowsById[row.backendId] = row;
        }
    };

    const findItemRowById = (itemId?: string): RowItem | null => {
        if (!itemId) return null;
        return itemRowsById[itemId] || null;
    };

    const findItemRowByIdentifier = (itemId?: string): RowItem | null => {
        if (!itemId) return null;
        const byBackendId = findItemRowById(itemId);
        if (byBackendId) return byBackendId;
        return Object.values(itemRowsById).find((row) => row.workNo === itemId) || null;
    };

    const loadItemById = async (
        itemId: string | undefined,
        itemType: WorkItemType,
        forceRefresh = false,
    ): Promise<RowItem | null> => {
        if (!itemId) return null;
        // 深链 / 分享链接打开详情时须强制拉最新数据：itemRowsById 可能是早先列表加载
        // 的旧快照（如负责人尚未指派），命中缓存会导致"列表已指派、详情空白"。
        // 请求失败时回退缓存，兼容 id 为 workNo（无法直接查询单条接口）的历史深链。
        if (!forceRefresh) {
            const cached = findItemRowByIdentifier(itemId);
            if (cached) return cached;
        }
        try {
            const res: any = itemType === "任务"
                ? await getVortflowTask(itemId)
                : itemType === "缺陷"
                    ? await getVortflowBug(itemId)
                    : await getVortflowStory(itemId);
            if (!res?.id) return forceRefresh ? findItemRowByIdentifier(itemId) : null;
            const row = mapBackendItemToRow(res, itemType, 0);
            itemRowsById[String(res.id)] = row;
            return row;
        } catch {
            return forceRefresh ? findItemRowByIdentifier(itemId) : null;
        }
    };

    const loadChildItems = async (parentId: string, itemType: WorkItemType, projectId?: string): Promise<RowItem[]> => {
        if (!parentId || itemType === "缺陷") return [];
        const res: any = itemType === "任务"
            ? await getVortflowTasks({
                parent_id: parentId,
                page: 1,
                page_size: 100,
            })
            : await getVortflowStories({
                parent_id: parentId,
                project_id: projectId,
                page: 1,
                page_size: 100,
            });
        const rows = ((res?.items || []) as any[]).map((item, index) => {
            const row = mapBackendItemToRow(item, itemType, index);
            row.isChild = true;
            return row;
        });
        cacheItemRows(rows);
        itemChildrenMap[parentId] = rows;
        return rows;
    };

    const getVisibleChildRows = (rows: RowItem[], ownerValue: string | string[] = owner.value, statusValues: string[] = status.value) => {
        const propTypeStr = String(propType ?? "").trim();
        const singleTopType = Array.isArray(type.value) && type.value.length === 1 ? String(type.value[0]) : "";
        const currentType = propTypeStr || singleTopType;
        if (!useApi.value || (currentType !== "需求" && currentType !== "任务")) return rows;
        const { matchOwner } = createOwnerMatcher(ownerValue);
        const childType = currentType as WorkItemType;
        const flags = parseVirtualStatusFlags(statusValues);
        const concreteStatusValues = statusValues.filter((s) => !VIRTUAL_STATUS_VALUES.has(s));
        const matchChildStatus = (child: RowItem): boolean => {
            if (!statusValues.length) return true;
            if (flags.hasOverdue && isRowOverdue(child)) return true;
            if (flags.hasStale && isRowStale(child)) return true;
            if (flags.hasPending && isPendingDisplayStatus(childType, child.status)) return true;
            if (concreteStatusValues.includes(child.status)) return true;
            return false;
        };
        const flattenedRows: RowItem[] = [];
        for (const row of rows) {
            flattenedRows.push(row);
            const itemId = String(row.backendId || "").trim();
            if (!itemId || !expandedItemIds[itemId]) continue;
            const children = (itemChildrenMap[itemId] || [])
                .filter(matchChildStatus)
                .filter(matchOwner)
                .map((child) => ({ ...child, isChild: true }));
            flattenedRows.push(...children);
        }
        return flattenedRows;
    };

    const applyColumnFilters = (rows: RowItem[]): RowItem[] => {
        const filters = columnFilters;
        if (!Object.keys(filters).length) return rows;

        return rows.filter(row => {
            for (const [field, fv] of Object.entries(filters)) {
                if (!fv) continue;
                if (field === "status") {
                    const vals = fv.value as string[];
                    if (vals?.length && !vals.includes(row.status)) return false;
                } else if (field === "owner") {
                    const vals = fv.value as string[];
                    if (vals?.length) {
                        const rowOwner = String(row.owner || "").trim();
                        const matched = vals.some((value) => {
                            if (value === "__unassigned__") {
                                return !String(row.ownerId || "").trim() || rowOwner === "未指派" || !rowOwner;
                            }
                            return rowOwner === value;
                        });
                        if (!matched) return false;
                    }
                } else if (field === "collaborators") {
                    const vals = fv.value as string[];
                    if (vals?.length) {
                        const rowCollaborators = (row.collaborators || []).map((name) => String(name || "").trim()).filter(Boolean);
                        if (!vals.some((value) => rowCollaborators.includes(value))) return false;
                    }
                } else if (field === "tags") {
                    const vals = fv.value as string[];
                    if (vals?.length) {
                        const rowTags: string[] = row.tags || [];
                        if (!vals.some(v => rowTags.includes(v))) return false;
                    }
                } else if (field === "priority") {
                    const vals = fv.value as string[];
                    if (vals?.length && !vals.includes(row.priority || "")) return false;
                } else if (field === "iteration") {
                    const vals = fv.value as string[];
                    if (vals?.length && !vals.includes(row.iteration || "")) return false;
                } else if (field === "version") {
                    const vals = fv.value as string[];
                    if (vals?.length && !vals.includes(row.version || "")) return false;
                } else if (field === "creator") {
                    const vals = fv.value as string[];
                    if (vals?.length && !vals.includes(String(row.creator || "").trim())) return false;
                } else if (field === "type") {
                    const vals = fv.value as string[];
                    if (vals?.length && !vals.includes(row.type || "")) return false;
                } else if (field === "createdAt" || field === "planTime" || field === "updatedAt" || field === "startAt" || field === "endAt" || field === "testTime" || field === "draftTime" || field === "releaseTime") {
                    const dateFieldMap: Record<string, string> = {
                        createdAt: row._createdAtRaw || row.createdAt,
                        planTime: row.planStartDate || row.planEndDate || "",
                        updatedAt: row._updatedAtRaw || row.updatedAt || "",
                        startAt: row.startAt || "",
                        endAt: row.endAt || "",
                        testTime: row.testTime || "",
                        draftTime: row.draftTime || "",
                        releaseTime: row.releaseTime || "",
                    };
                    const rowVal = dateFieldMap[field] || "";
                    if (!rowVal) return false;
                    const rowDate = new Date(rowVal).getTime();
                    if (isNaN(rowDate)) return false;
                    const { operator, value } = fv;
                    if (operator === "between") {
                        const [start, end] = value as [string, string];
                        if (start && rowDate < new Date(start).getTime()) return false;
                        if (end && rowDate > new Date(end + "T23:59:59").getTime()) return false;
                    } else {
                        const target = new Date(value).getTime();
                        if (isNaN(target)) continue;
                        if (operator === "gt" && rowDate <= target) return false;
                        if (operator === "lt" && rowDate >= target) return false;
                        if (operator === "gte" && rowDate < target) return false;
                        if (operator === "lte" && rowDate > target) return false;
                        if (operator === "eq" && new Date(rowVal).toDateString() !== new Date(value).toDateString()) return false;
                    }
                }
            }
            return true;
        });
    };

    const applyColumnSort = (rows: RowItem[]): RowItem[] => {
        const field = columnSortField.value;
        const order = columnSortOrder.value;
        if (!field || !order) return rows;

        const sorted = [...rows];
        const dir = order === "ascend" ? 1 : -1;

        sorted.sort((a, b) => {
            if (field === "createdAt") {
                return compareWorkItemDate(a, b, "_createdAtRaw", "createdAt", order);
            }
            if (field === "updatedAt") {
                return compareWorkItemDate(a, b, "_updatedAtRaw", "updatedAt", order);
            }

            let va: any;
            let vb: any;
            if (field === "status") {
                va = a.status || "";
                vb = b.status || "";
            } else if (field === "priority") {
                // 优先级列前端排序：score 大的优先（紧急 80~100 在前）。
                // dir=-1（降序）时 score 大的在前；dir=1（升序）时 score 小的在前。
                // 为兼容现有"priority asc=紧急在前"，把 score 取反作为比较值。
                va = -(a.priorityScore ?? 0);
                vb = -(b.priorityScore ?? 0);
            } else if (field === "tags") {
                va = (a.tags || []).join(",");
                vb = (b.tags || []).join(",");
            } else if (field === "planTime") {
                va = a.planStartDate || a.planEndDate || "";
                vb = b.planStartDate || b.planEndDate || "";
            } else if (field === "iteration") {
                va = a.iteration || "";
                vb = b.iteration || "";
            } else if (field === "version") {
                va = a.version || "";
                vb = b.version || "";
            } else if (field === "creator") {
                va = a.creator || "";
                vb = b.creator || "";
            } else if (field === "type") {
                va = a.type || "";
                vb = b.type || "";
            } else if (field === "project" || field === "projectName") {
                va = a.projectName || "";
                vb = b.projectName || "";
            } else if (field === "workNo") {
                va = a.workNo || "";
                vb = b.workNo || "";
            } else if (field === "estimateHours") {
                va = Number(a.estimateHours ?? 0);
                vb = Number(b.estimateHours ?? 0);
            } else if (field === "startAt") {
                va = a.startAt || "";
                vb = b.startAt || "";
            } else if (field === "endAt") {
                va = a.endAt || "";
                vb = b.endAt || "";
            } else if (field === "testTime") {
                va = a.testTime || "";
                vb = b.testTime || "";
            } else if (field === "draftTime") {
                va = a.draftTime || "";
                vb = b.draftTime || "";
            } else if (field === "releaseTime") {
                va = a.releaseTime || "";
                vb = b.releaseTime || "";
            } else {
                return 0;
            }
            if (va < vb) return -1 * dir;
            if (va > vb) return 1 * dir;
            return 0;
        });
        return sorted;
    };

    // ===== 工作墙聚合模式 =====
    // type 为空时跨类型聚合查询，调用 GET /vortflow/work-items
    const requestUnified = async (ctx: {
        kw: string;
        ownerValues: string[];
        ownerMemberId: string;
        matchOwner: (row: RowItem) => boolean;
        statusValues: string[];
        current: number;
        pageSize: number;
        effectiveSortField: string;
        effectiveSortOrder: "ascend" | "descend" | null | string;
    }): Promise<ProTableResponse<RowItem>> => {
        const { kw, ownerValues, ownerMemberId, matchOwner, statusValues, current, pageSize, effectiveSortField, effectiveSortOrder } = ctx;
        const projectFilter = buildProjectFilter();
        const iterationIdParam = propIterationId.value || undefined;
        const vf = propViewFilters.value || {};

        // 类型筛选：列筛选优先，其次顶部 type 多选
        const typeColumnFilter = (columnFilters["type"]?.value as string[] | undefined) || [];
        const topTypeArray: string[] = Array.isArray(type.value) ? [...type.value] : [];
        let types: string | undefined;
        if (typeColumnFilter.length > 0) {
            types = typeColumnFilter.map((t) => TYPE_CN_TO_BACKEND[t]).filter(Boolean).join(",");
        } else if (topTypeArray.length > 0) {
            const codes = topTypeArray.map((t) => TYPE_CN_TO_BACKEND[t]).filter(Boolean);
            if (codes.length) types = codes.join(",");
        }

        // 状态筛选：跨类型时把"显示状态"展开到三类型 backend states 联合传给后端
        const statusColumnFilter = (columnFilters["status"]?.value as string[] | undefined) || [];
        const allDisplayStates: string[] = [...(statusValues || []), ...statusColumnFilter];
        const flags = parseVirtualStatusFlags(allDisplayStates);
        const hasPendingStatus = flags.hasPending;
        const hasCompletedTodayStatus = flags.hasCompletedToday;
        // 逾期/停滞属于「在手」的子集，粗筛用 pendingUnion，细筛在行级完成
        const hasRisk = flags.hasOverdue || flags.hasStale;
        const concreteDisplayStates = allDisplayStates.filter((s) => !VIRTUAL_STATUS_VALUES.has(s));
        const allTypes: WorkItemType[] = ["需求", "任务", "缺陷"];
        const pendingUnion = allTypes.flatMap((t) => getPendingBackendStates(t));
        const doneUnion = allTypes.flatMap((t) => getDoneBackendStates(t));
        const concreteUnion = concreteDisplayStates.flatMap((s) =>
            allTypes.flatMap((t) => getBackendStatesByDisplayStatus(t, s as Status) || [])
        );
        let backendStates: string[];
        if (hasPendingStatus || hasCompletedTodayStatus || hasRisk) {
            backendStates = Array.from(new Set([
                ...((hasPendingStatus || hasRisk) ? pendingUnion : []),
                ...(hasCompletedTodayStatus ? doneUnion : []),
                ...concreteUnion,
            ]));
        } else if (concreteDisplayStates.length) {
            backendStates = Array.from(new Set(concreteUnion));
        } else {
            backendStates = [];
        }
        // 「未完成工作项」视图翻译成后端 pending states 过滤（同单类型分支：
        // 后端过滤+分页+计数；视图内再选具体状态时取交集）
        const isIncompleteView = vf.status === "incomplete";
        if (isIncompleteView) {
            const pendingSet = new Set(pendingUnion);
            if (backendStates.length) {
                backendStates = backendStates.filter((s) => pendingSet.has(s));
                if (!backendStates.length) {
                    totalCount.value = 0;
                    return { data: [], total: 0, current, pageSize };
                }
            } else {
                backendStates = [...pendingSet];
            }
        }

        // 「当日已完成」起点：今日零点 ISO（local time）。后端会限制完成态 end_at>=此时间。
        let completedAfterParam: string | undefined;
        if (hasCompletedTodayStatus) {
            const now = new Date();
            const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
            completedAfterParam = todayStart.toISOString();
        }

        // 排序映射（工作墙支持 priority/created_at/updated_at/deadline）
        const wallSortFieldMap: Record<string, string> = {
            priority: "priority",
            createdAt: "created_at",
            updatedAt: "updated_at",
            planTime: "deadline",
        };
        const backendSortBy = wallSortFieldMap[effectiveSortField] || "created_at";
        const backendSortOrder = effectiveSortOrder === "ascend"
            ? "asc"
            : effectiveSortOrder === "descend"
                ? "desc"
                : (backendSortBy === "priority" ? "asc" : "desc");

        const archivedParam = vf.archived === true ? true : false;
        // include_archived=true 时后端忽略 archived，返回归档+未归档（「包含已归档」开关）
        const includeArchivedParam = vf.include_archived === true ? true : false;
        const viewCreator = vf.creator || undefined;
        const viewParticipant = vf.participant || undefined;
        const effectiveAssignee = ownerMemberId || vf.owner || undefined;

        const fetchPage = async (page: number, size: number) => {
            return getVortflowWorkItems({
                types,
                ...projectFilter,
                iteration_id: iterationIdParam,
                keyword: kw,
                state: backendStates.length ? backendStates.join(",") : undefined,
                assignee_id: effectiveAssignee,
                creator_id: viewCreator,
                participant_id: viewParticipant,
                archived: archivedParam,
                include_archived: includeArchivedParam,
                sort_by: backendSortBy,
                sort_order: backendSortOrder,
                page,
                page_size: size,
                completed_after: completedAfterParam,
            });
        };

        const fetchAll = async (): Promise<any[]> => {
            const batchSize = 100;
            const firstRes: any = await fetchPage(1, batchSize);
            const all: any[] = [...((firstRes as any)?.items || [])];
            const total = Number(firstRes?.total || all.length);
            const totalPages = Math.max(1, Math.ceil(total / batchSize));
            for (let page = 2; page <= totalPages && page <= 50; page++) {
                const res: any = await fetchPage(page, batchSize);
                const items = res?.items || [];
                if (!items.length) break;
                all.push(...items);
            }
            return all;
        };

        const buildRows = (items: any[]): RowItem[] => {
            const rows = items.map((item: any, idx: number) => {
                const cnType = TYPE_BACKEND_TO_CN[item.type] || "缺陷";
                return mapBackendItemToRow(item, cnType, idx);
            });
            cacheItemRows(rows);
            return rows;
        };

        const hasOwnerFilter = ownerValues.length > 0;
        const hasOtherColumnFilters = Object.keys(columnFilters).some(
            (k) => columnFilters[k] != null && k !== "type" && k !== "status"
        );
        const needFetchAll = hasOtherColumnFilters
            || hasRisk
            || (hasOwnerFilter && (ownerValues.includes("未指派") || !ownerMemberId));

        let rows: RowItem[];
        let totalFromApi: number;

        if (needFetchAll) {
            const allItems = await fetchAll();
            let allRows = buildRows(allItems).filter(matchOwner);
            if (hasRisk) {
                // 虚拟状态之间是并集语义：逾期 / 停滞 / 在手 / 当日完成 / 具体状态任一命中即保留
                allRows = allRows.filter((x) =>
                    (flags.hasOverdue && isRowOverdue(x))
                    || (flags.hasStale && isRowStale(x))
                    || (hasPendingStatus && isPendingDisplayStatus(x.type, x.status))
                    || (hasCompletedTodayStatus && isRowCompletedToday(x))
                    || concreteDisplayStates.includes(x.status)
                );
            }
            collectTagOptions(allRows);
            collectEnumOptions(allRows);

            allRows = applyColumnFilters(allRows);
            if (hasRisk && !effectiveSortField) {
                allRows.sort((a, b) => getOverdueStaleSortKey(a) - getOverdueStaleSortKey(b));
            } else {
                allRows = applyColumnSort(allRows);
            }
            totalFromApi = allRows.length;

            const start = (current - 1) * pageSize;
            rows = allRows.slice(start, start + pageSize);
        } else {
            const res: any = await fetchPage(current, pageSize);
            rows = buildRows(res?.items || []);
            totalFromApi = Number(res?.total || rows.length);
            collectTagOptions(rows);
            collectEnumOptions(rows);
        }

        totalCount.value = totalFromApi;
        return { data: rows, total: totalFromApi, current, pageSize };
    };

    const request = async (params: ProTableRequestParams): Promise<ProTableResponse<RowItem>> => {
        await loadMemberOptions?.();
        const kw = String(params.keyword ?? "").trim().toLowerCase();
        const ownerValues: string[] = Array.isArray(params.owner) ? params.owner : (params.owner ? [String(params.owner)] : []);
        const hasOwnerFilter = ownerValues.length > 0;
        const { ownerMemberId, matchOwner } = createOwnerMatcher(ownerValues);
        // 单类型页面 propType 优先；工作墙下取 params.type 数组
        const propTypeValue = String(propType ?? "").trim();
        const typeValue = propTypeValue;
        const statusValues: string[] = Array.isArray(params.status)
            ? params.status
                .map(value => String(value || "").trim())
                .filter(value => value && value !== "全部")
            : [];
        const current = Number(params.current || 1);
        const pageSize = Number(params.pageSize || 20);

        const effectiveSortField = columnSortField.value || params.sortField || "";
        const effectiveSortOrder = columnSortOrder.value || params.sortOrder || null;
        const typeOverrides = SORT_FIELD_OVERRIDES[typeValue];
        let backendSortBy = (typeOverrides && typeOverrides[effectiveSortField]) || SORT_FIELD_MAP[effectiveSortField] || "";
        const backendSortOrder = effectiveSortOrder === "ascend" ? "asc" : effectiveSortOrder === "descend" ? "desc" : "";

        // ===== 工作墙聚合模式（无指定 propType，统一走 /work-items 接口）=====
        if (useApi.value && !propTypeValue) {
            return await requestUnified({
                kw, ownerValues, ownerMemberId, matchOwner,
                statusValues, current, pageSize,
                effectiveSortField, effectiveSortOrder,
            });
        }

        if (useApi.value && (typeValue === "需求" || typeValue === "任务" || typeValue === "缺陷")) {
            const workType = typeValue as WorkItemType;
            const vf = propViewFilters.value || {};
            // 「未完成工作项」视图必须翻译成后端 pending states 过滤，让后端做过滤+分页+计数。
            // 否则只能取回一页后行级剔除完成项，total 会被截成"当前页剩余行数"，分页也失效。
            const isIncompleteView = vf.status === "incomplete";
            const sFlags = parseVirtualStatusFlags(statusValues);
            const hasPendingStatus = sFlags.hasPending;
            // 逾期/停滞属于「在手」子集：粗筛用 pending states，细筛在行级完成
            const hasRisk = sFlags.hasOverdue || sFlags.hasStale;
            const concreteStatusValues = statusValues.filter((s) => !VIRTUAL_STATUS_VALUES.has(s));
            let backendStates: string[] | undefined;
            if (hasPendingStatus || hasRisk) {
                backendStates = Array.from(new Set([
                    ...getPendingBackendStates(workType),
                    ...concreteStatusValues.flatMap(
                        (s) => getBackendStatesByDisplayStatus(workType, s as any) || []
                    ),
                ]));
            } else if (concreteStatusValues.length) {
                backendStates = [...new Set(concreteStatusValues.flatMap(
                    (s) => getBackendStatesByDisplayStatus(workType, s as any) || []
                ))];
            } else {
                backendStates = undefined;
            }
            if (isIncompleteView) {
                // 视图限定"未完成"范围；视图内再选具体状态时取交集（选完成态则结果为空）
                const pendingSet = new Set(getPendingBackendStates(workType));
                backendStates = backendStates === undefined
                    ? [...pendingSet]
                    : backendStates.filter((s) => pendingSet.has(s));
                if (!backendStates.length) {
                    totalCount.value = 0;
                    return { data: [], total: 0, current, pageSize };
                }
            }
            if (statusValues.length && !hasPendingStatus && !hasRisk
                && (!backendStates || backendStates.length === 0)) {
                totalCount.value = 0;
                return { data: [], total: 0, current, pageSize };
            }

            // 行级 status 匹配：虚拟状态（在手/逾期/停滞/当日完成）与具体显示状态取并集
            const matchStatus = (row: RowItem): boolean => {
                if (!statusValues.length) return true;
                if (sFlags.hasOverdue && isRowOverdue(row)) return true;
                if (sFlags.hasStale && isRowStale(row)) return true;
                if (hasPendingStatus && isPendingDisplayStatus(workType, row.status)) return true;
                if (sFlags.hasCompletedToday && isRowCompletedToday(row)) return true;
                if (concreteStatusValues.includes(row.status)) return true;
                return false;
            };
            const hasStatusFilter = statusValues.length > 0;
            const projectFilter = buildProjectFilter();
            const iterationIdParam = propIterationId.value || undefined;
            const viewOwner = vf.owner || undefined;
            const viewCreator = vf.creator || undefined;
            const viewParticipant = vf.participant || undefined;
            const effectiveAssignee = ownerMemberId || viewOwner || undefined;
            const shouldFetchAllStoryOwner = workType === "需求" && Boolean(ownerMemberId || viewOwner);
            const archivedParam = vf.archived === true ? true : false;
            // include_archived=true 时后端忽略 archived，返回归档+未归档（「包含已归档」开关）
            const includeArchivedParam = vf.include_archived === true ? true : false;
            const sortParams = backendSortBy ? { sort_by: backendSortBy, sort_order: backendSortOrder } : {};
            const requestByState = async (state?: string, page = current, size = pageSize) => {
                if (workType === "需求") {
                    return getVortflowStories({
                        keyword: kw, state, parent_id: "root",
                        ...projectFilter,
                        iteration_id: iterationIdParam,
                        submitter_id: viewCreator,
                        participant_id: viewParticipant,
                        archived: archivedParam,
                        include_archived: includeArchivedParam,
                        ...sortParams,
                        page, page_size: size
                    });
                }
                if (workType === "任务") {
                    return getVortflowTasks({
                        keyword: kw,
                        parent_id: "root",
                        state,
                        assignee_id: effectiveAssignee,
                        ...projectFilter,
                        iteration_id: iterationIdParam,
                        creator_id: viewCreator,
                        participant_id: viewParticipant,
                        archived: archivedParam,
                        include_archived: includeArchivedParam,
                        ...sortParams,
                        page,
                        page_size: size
                    });
                }
                return getVortflowBugs({
                    keyword: kw,
                    state,
                    assignee_id: effectiveAssignee,
                    ...projectFilter,
                    iteration_id: iterationIdParam,
                    reporter_id: viewCreator,
                    participant_id: viewParticipant,
                    archived: archivedParam,
                    include_archived: includeArchivedParam,
                    ...sortParams,
                    page,
                    page_size: size
                });
            };
            const fetchAllItemsByState = async (state?: string): Promise<any[]> => {
                const batchSize = 100;
                const firstRes: any = await requestByState(state, 1, batchSize);
                const allItems: any[] = [...((firstRes as any)?.items || [])];
                const total = Number((firstRes as any)?.total || allItems.length);
                const totalPages = Math.max(1, Math.ceil(total / batchSize));
                for (let page = 2; page <= totalPages; page++) {
                    const pageRes: any = await requestByState(state, page, batchSize);
                    const pageItems = ((pageRes as any)?.items || []);
                    if (!pageItems.length) break;
                    allItems.push(...pageItems);
                }
                return allItems;
            };
            const buildRowsFromItems = (items: any[]): RowItem[] => {
                const rows = items.map((item: any, idx: number) => mapBackendItemToRow(item, workType, idx));
                cacheItemRows(rows);
                return rows;
            };

            let rows: RowItem[] = [];
            let totalFromApi = 0;

            const combinedState = backendStates?.join(",");
            const hasColumnFilters = Object.keys(columnFilters).some(k => columnFilters[k] != null);
            const needFetchAll = hasColumnFilters
                || hasRisk
                || shouldFetchAllStoryOwner
                || (hasOwnerFilter && (workType === "需求" || ownerValues.includes("未指派") || !ownerMemberId));

            if (needFetchAll) {
                const allItems = await fetchAllItemsByState(combinedState);
                let allRows = buildRowsFromItems(allItems)
                    .filter(matchStatus)
                    .filter(matchOwner);

                const optionRows = workType === "需求" || workType === "任务" ? getVisibleChildRows(allRows, ownerValues, concreteStatusValues) : allRows;
                collectTagOptions(optionRows);
                collectEnumOptions(optionRows);

                allRows = applyColumnFilters(allRows);
                if (hasRisk && !effectiveSortField) {
                    allRows.sort((a, b) => getOverdueStaleSortKey(a) - getOverdueStaleSortKey(b));
                } else {
                    allRows = applyColumnSort(allRows);
                }
                totalFromApi = allRows.length;

                if (current === 1) {
                    let pinnedRows = getScopedPinnedRows(workType);
                    if (hasStatusFilter) pinnedRows = pinnedRows.filter(matchStatus);
                    if (hasOwnerFilter) pinnedRows = pinnedRows.filter(matchOwner);
                    const pinnedIds = new Set(pinnedRows.map((x) => x.backendId || x.workNo));
                    allRows = [...pinnedRows, ...allRows.filter((x) => !pinnedIds.has(x.backendId || x.workNo))];
                    totalFromApi = allRows.length;
                }

                const start = (current - 1) * pageSize;
                rows = allRows.slice(start, start + pageSize);
            } else {
                const combinedState = backendStates?.join(",");
                if (hasOwnerFilter && (workType === "需求" || ownerValues.includes("未指派") || !ownerMemberId)) {
                    const allItems = await fetchAllItemsByState(combinedState);
                    const allRows = buildRowsFromItems(allItems)
                        .filter(matchStatus)
                        .filter(matchOwner);
                    totalFromApi = allRows.length;
                    const start = (current - 1) * pageSize;
                    rows = allRows.slice(start, start + pageSize);
                } else {
                    const res: any = await requestByState(combinedState, current, pageSize);
                    rows = buildRowsFromItems((res as any)?.items || []);
                    if (hasStatusFilter) rows = rows.filter(matchStatus);
                    if (hasOwnerFilter) rows = rows.filter(matchOwner);
                    totalFromApi = Number((res as any)?.total || rows.length);
                }
            }

            if (current === 1) {
                let pinnedRows = getScopedPinnedRows(workType);
                if (hasStatusFilter) pinnedRows = pinnedRows.filter(matchStatus);
                if (hasOwnerFilter) pinnedRows = pinnedRows.filter(matchOwner);
                const pinnedIds = new Set(pinnedRows.map((x) => x.backendId || x.workNo));
                rows = [...pinnedRows, ...rows.filter((x) => !pinnedIds.has(x.backendId || x.workNo))];
                rows = rows.slice(0, pageSize);
            }
            const beforeFilterCount = rows.length;
            rows = applyColumnFilters(rows);
            rows = applyColumnSort(rows);
            if (rows.length < beforeFilterCount) {
                totalFromApi = rows.length;
            }
            const optionRows = workType === "需求" || workType === "任务" ? getVisibleChildRows(rows, ownerValues, concreteStatusValues) : rows;
            collectTagOptions(optionRows);
            collectEnumOptions(optionRows);
            totalCount.value = totalFromApi;
            return { data: rows, total: totalFromApi, current, pageSize };
        }

        totalCount.value = 0;
        return { data: [], total: 0, current, pageSize };
    };

    const postProcessTableRows = (rows: RowItem[]) => getVisibleChildRows(rows);

    const prependPinnedRow = (typeValue: WorkItemType, row: RowItem) => {
        const list = pinnedRowsByType[typeValue] || [];
        const rowId = row.backendId || row.workNo;
        pinnedRowsByType[typeValue] = [row, ...list.filter((x) => (x.backendId || x.workNo) !== rowId)];
        if (row.backendId) {
            itemRowsById[row.backendId] = row;
        }
    };

    // pinnedRows 是页面级跨次查询保留的"刚创建置顶行"，但它跨项目/迭代不重置。
    // 拼接到第一页前必须按当前作用域的 projectId / iterationId 过滤，
    // 否则切到别的项目会把上一个项目刚建的工作项也带过去（强刷才正常）。
    const getScopedPinnedRows = (workType: WorkItemType): RowItem[] => {
        const list = pinnedRowsByType[workType] || [];
        const ids = (propProjectIds?.value || []).filter(Boolean);
        const projectId = propProjectId.value || "";
        const iterationId = propIterationId.value || "";
        const idSet = ids.length ? new Set(ids) : (projectId ? new Set([projectId]) : null);
        if (!idSet && !iterationId) return list;
        return list.filter((row) => {
            if (idSet && !idSet.has(row.projectId || "")) return false;
            if (iterationId && row.iterationId !== iterationId) return false;
            return true;
        });
    };

    return {
        SORT_FIELD_MAP,
        SORT_FIELD_OVERRIDES,
        mapBackendItemToRow,
        createOwnerMatcher,
        cacheItemRows,
        findItemRowById,
        findItemRowByIdentifier,
        loadItemById,
        loadChildItems,
        getVisibleChildRows,
        applyColumnFilters,
        applyColumnSort,
        request,
        postProcessTableRows,
        prependPinnedRow,
        isMultiProjectView,
    };
}
