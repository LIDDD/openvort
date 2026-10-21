import { ref, type Component } from "vue";
import { getMembersSimple, getVortflowStatuses, getVortflowProjectMembers } from "@/api";
import { fetchAllPages } from "@/api/iterationOptions";
import { resolveIconKey } from "@/components/vort-biz/work-item/statusIcons";
import { Bookmark, SquareCheck, Bug } from "lucide-vue-next";
import type {
    WorkItemType,
    Priority,
    Status,
    MemberOption,
    StatusOption
} from "@/components/vort-biz/work-item/WorkItemTable.types";

// ============================================================================
// 优先级 score (0-100) 与等级 (Priority) 的映射规则
// ============================================================================
// 80-100 = urgent (紧急)，默认段起始值 80
//  60-79 = high   (高)，默认 60
//  40-59 = medium (中)，默认 40
//  20-39 = low    (低)，默认 20
//   0-19 = none   (无优先级)，默认 0
//
// 显示规则：score === 段起始值 时只显示等级标签（如 [紧急]）；否则显示等级 + 数字（如 [紧急 95]）。
// ============================================================================

export const PRIORITY_SCORE_DEFAULTS: Record<Priority, number> = {
    urgent: 80,
    high: 60,
    medium: 40,
    low: 20,
    none: 0
};

export const PRIORITY_SCORE_RANGES: Record<Priority, [number, number]> = {
    urgent: [80, 100],
    high: [60, 79],
    medium: [40, 59],
    low: [20, 39],
    none: [0, 19]
};

export const scoreToPriority = (score: number | null | undefined): Priority => {
    if (score == null || Number.isNaN(score)) return "none";
    const s = Number(score);
    if (s >= 80) return "urgent";
    if (s >= 60) return "high";
    if (s >= 40) return "medium";
    if (s >= 20) return "low";
    return "none";
};

export const priorityToDefaultScore = (priority: Priority): number =>
    PRIORITY_SCORE_DEFAULTS[priority] ?? 0;

export const clampPriorityScore = (score: number | null | undefined): number => {
    if (score == null || Number.isNaN(score)) return 0;
    return Math.max(0, Math.min(100, Math.round(Number(score))));
};

/** 派生展示信息：是否需要显示具体分数（非段起始值才显示）。 */
export const formatPriorityDisplay = (
    score: number | null | undefined
): { level: Priority; showScore: boolean; score: number } => {
    const normalized = clampPriorityScore(score);
    const level = scoreToPriority(normalized);
    const defaultScore = PRIORITY_SCORE_DEFAULTS[level];
    return {
        level,
        showScore: normalized !== defaultScore,
        score: normalized
    };
};

/** 后端 priority 等级 (1-4) → score 默认值。AI 工具/老接口兼容时使用。 */
export const backendPriorityLevelToScore = (level: number | null | undefined): number => {
    if (level == null) return 0;
    const map: Record<number, number> = { 1: 80, 2: 60, 3: 40, 4: 20 };
    return map[Number(level)] ?? 0;
};

export type OwnerGroup = { label: string; members: string[] };

interface ApiMemberRecord {
    id?: string;
    name?: string;
    avatar_url?: string;
    avatar?: string;
    status?: string;
}

const normalizeMemberName = (value: unknown): string => String(value || "").trim();

const dedupeNames = (members: string[]): string[] => {
    const result: string[] = [];
    const seen = new Set<string>();
    for (const member of members) {
        const normalized = normalizeMemberName(member);
        if (!normalized || seen.has(normalized)) continue;
        seen.add(normalized);
        result.push(normalized);
    }
    return result;
};

const buildOwnerGroupsFromMembers = (members: ApiMemberRecord[]): OwnerGroup[] => {
    const activeNames: string[] = [];
    const inactiveNames: string[] = [];

    for (const item of members) {
        const name = normalizeMemberName(item?.name);
        if (!name) continue;

        if (String(item?.status || "").toLowerCase() === "inactive") {
            inactiveNames.push(name);
        } else {
            activeNames.push(name);
        }
    }

    const groups: OwnerGroup[] = [];
    if (activeNames.length > 0) {
        groups.push({ label: "企业成员", members: dedupeNames(activeNames) });
    }
    if (inactiveNames.length > 0) {
        groups.push({ label: "离职人员", members: dedupeNames(inactiveNames) });
    }
    return groups;
};

const RECENT_MEMBERS_KEY = "openvort:recent-assignees";
const RECENT_MEMBERS_MAX = 8;

const getRecentMemberNames = (): string[] => {
    try {
        const raw = localStorage.getItem(RECENT_MEMBERS_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : [];
    } catch {
        return [];
    }
};

const recordRecentMember = (name: string) => {
    const normalized = normalizeMemberName(name);
    if (!normalized) return;
    const list = getRecentMemberNames().filter((n) => n !== normalized);
    list.unshift(normalized);
    try {
        localStorage.setItem(RECENT_MEMBERS_KEY, JSON.stringify(list.slice(0, RECENT_MEMBERS_MAX)));
    } catch { /* quota exceeded */ }
};

const projectMembersCache = new Map<string, string[]>();
let lastProjectMembersFetchId = "";

const loadProjectMemberNames = async (projectId: string): Promise<string[]> => {
    if (!projectId) return [];
    if (projectMembersCache.has(projectId)) return projectMembersCache.get(projectId)!;
    try {
        const res: any = await getVortflowProjectMembers(projectId);
        const items = Array.isArray(res?.items) ? res.items : [];
        const names = items
            .filter((item: any) => item?.name && String(item?.member_status || "active") !== "inactive")
            .map((item: any) => normalizeMemberName(item.name))
            .filter(Boolean);
        const deduped = dedupeNames(names);
        projectMembersCache.set(projectId, deduped);
        return deduped;
    } catch {
        return [];
    }
};

const buildEnrichedOwnerGroups = (
    baseGroups: OwnerGroup[],
    projectMemberNames: string[],
    recentNames: string[],
): OwnerGroup[] => {
    const allBaseNames = new Set(baseGroups.flatMap((g) => g.members));
    const groups: OwnerGroup[] = [];
    const usedNames = new Set<string>();

    if (recentNames.length > 0) {
        const valid = recentNames.filter((n) => allBaseNames.has(n));
        if (valid.length > 0) {
            groups.push({ label: "最近选择", members: valid });
            valid.forEach((n) => usedNames.add(n));
        }
    }

    if (projectMemberNames.length > 0) {
        const valid = projectMemberNames.filter((n) => allBaseNames.has(n) && !usedNames.has(n));
        if (valid.length > 0) {
            groups.push({ label: "项目参与人", members: valid });
            valid.forEach((n) => usedNames.add(n));
        }
    }

    for (const group of baseGroups) {
        const remaining = group.members.filter((n) => !usedNames.has(n));
        if (remaining.length > 0) {
            groups.push({ label: group.label, members: remaining });
        }
    }

    return groups;
};

const sharedMemberOptions = ref<MemberOption[]>([]);
const sharedOwnerGroups = ref<OwnerGroup[]>([]);
let memberOptionsLoadTask: Promise<void> | null = null;

interface ApiStatusItem {
    name: string;
    icon: string;
    icon_color: string;
    command: string;
    work_item_types: string[];
}

const sharedApiStatuses = ref<ApiStatusItem[]>([]);
let statusLoadTask: Promise<void> | null = null;

const HEX_TO_TW: Record<string, string> = {
    "#64748b": "text-gray-500", "#ef4444": "text-red-500", "#6366f1": "text-indigo-500",
    "#3b82f6": "text-blue-500", "#22c55e": "text-emerald-500", "#7c3aed": "text-violet-600",
    "#f59e0b": "text-amber-500", "#0284c7": "text-sky-600", "#a855f7": "text-purple-500",
};

const toIconClass = (hex: string): string => HEX_TO_TW[hex] || "text-gray-500";
const toLucideIcon = (raw: string): string => resolveIconKey(raw) || "circle";

const buildOptionsForType = (type: string): StatusOption[] =>
    sharedApiStatuses.value
        .filter((s) => s.work_item_types.includes(type))
        .map((s) => ({
            label: s.name,
            value: s.name,
            icon: toLucideIcon(s.icon),
            iconClass: toIconClass(s.icon_color),
            iconColor: s.icon_color,
            syncable: Boolean(s.command && s.command.split(",").some((x) => x.trim())),
        }));

const buildStateToNameMap = (type: string): Record<string, string> => {
    const map: Record<string, string> = {};
    for (const s of sharedApiStatuses.value) {
        if (!s.work_item_types.includes(type)) continue;
        if (s.command) {
            for (const state of s.command.split(",")) {
                const key = state.trim();
                if (key && !map[key]) map[key] = s.name;
            }
        } else {
            // command 为空表示该 status 仅作展示用，没有对应的后端 state。
            // 历史脏数据可能直接把 status 名当 state 写进了 DB，这里仍允许反向映射
            // 让前端能正确识别这些值，但同步路径会在 buildNameToStatesMap 里拦掉。
            if (!map[s.name]) map[s.name] = s.name;
        }
    }
    return map;
};

// 后端状态机不识别的 status 名称（command 为空），这些状态目前仅用于展示，
// 不能作为可同步的目标状态，否则会写入非法 state 导致下次切换全部失败。
const buildNameToStatesMap = (type: string): Record<string, string[]> => {
    const map: Record<string, string[]> = {};
    for (const s of sharedApiStatuses.value) {
        if (!s.work_item_types.includes(type)) continue;
        if (s.command) {
            map[s.name] = s.command.split(",").map((x) => x.trim()).filter(Boolean);
        }
    }
    return map;
};

const isStatusNameSyncable = (type: string, name: string): boolean => {
    return Boolean(buildNameToStatesMap(type)[name]?.length);
};

const FALLBACK_BUG: StatusOption[] = [
    { label: "待确认", value: "待确认", icon: "circle", iconClass: "text-gray-500" },
    { label: "修复中", value: "修复中", icon: "circle-dot", iconClass: "text-blue-500" },
    { label: "已修复", value: "已修复", icon: "check", iconClass: "text-blue-500" },
    { label: "已关闭", value: "已关闭", icon: "check", iconClass: "text-gray-500" },
];

// 「在手工作项」虚拟状态值：与具体显示状态互斥；语义为后端 dashboard pending（未完成）
export const PENDING_STATUS_VALUE = "__pending";
export const PENDING_STATUS_LABEL = "在手工作项";

// 「当日已完成」虚拟状态值：与具体显示状态互斥；可与「在手工作项」组合
export const COMPLETED_TODAY_STATUS_VALUE = "__completed_today";
export const COMPLETED_TODAY_STATUS_LABEL = "当日已完成";

// 「已逾期」虚拟状态值：筛出计划截止日已过的非完成态工作项（与成员卡片「逾」徽章同口径）
export const OVERDUE_STATUS_VALUE = "__overdue";
export const OVERDUE_STATUS_LABEL = "已逾期";

// 「停滞」虚拟状态值：筛出超过 7 天无活动且未逾期的非完成态工作项（与成员卡片「滞」徽章同口径）
export const STALE_STATUS_VALUE = "__stale";
export const STALE_STATUS_LABEL = "停滞";

// legacy：旧版合并的「逾期/停滞」虚拟状态值。UI 已拆分为上面两个值，
// 该值仅用于兼容历史保存的自定义视图，读取时应 normalize 成两个新值。
export const OVERDUE_STALE_STATUS_VALUE = "__overdue_stale";
export const OVERDUE_STALE_STATUS_LABEL = "逾期/停滞";

/** 把 legacy 的「逾期/停滞」合并值展开为「已逾期」+「停滞」两个新值 */
export function normalizeVirtualStatusValues(values: string[]): string[] {
    if (!values.includes(OVERDUE_STALE_STATUS_VALUE)) return values;
    const next = values.filter((v) => v !== OVERDUE_STALE_STATUS_VALUE);
    for (const v of [OVERDUE_STATUS_VALUE, STALE_STATUS_VALUE]) {
        if (!next.includes(v)) next.push(v);
    }
    return next;
}

// 与后端 STORY_DONE_STATES / TASK_DONE_STATES / BUG_CLOSED_STATES 保持一致
const STORY_DONE_BACKEND_STATES = new Set<string>(["done", "released"]);
// 需求计划时间是开发排期：只有待测试之前的状态参与 deadline 逾期判断。
const STORY_DEVELOPMENT_PENDING_BACKEND_STATES = new Set<string>([
    "submitted", "intake", "review", "pm_refine", "design",
    "design_done", "pending_dev", "breakdown", "dev_assign", "in_progress",
]);
const TASK_DONE_BACKEND_STATES = new Set<string>(["done", "closed"]);
const BUG_CLOSED_BACKEND_STATES = new Set<string>([
    "resolved", "verified", "closed", "not_reproducible", "by_design",
]);

const DONE_BACKEND_STATES: Record<WorkItemType, string[]> = {
    需求: Array.from(STORY_DONE_BACKEND_STATES),
    任务: Array.from(TASK_DONE_BACKEND_STATES),
    缺陷: Array.from(BUG_CLOSED_BACKEND_STATES),
};

export function getDoneBackendStates(typeValue: WorkItemType): string[] {
    return DONE_BACKEND_STATES[typeValue] ? [...DONE_BACKEND_STATES[typeValue]] : [];
}

export function isCompletedDisplayStatus(typeValue: WorkItemType, displayStatus: string): boolean {
    if (!displayStatus) return false;
    if (typeValue === "需求") return displayStatus === "已完成";
    if (typeValue === "任务") return displayStatus === "已完成" || displayStatus === "已取消";
    return displayStatus === "已修复" || displayStatus === "已关闭";
}

// 各类型已知的全部 backend states（与 engine.py 中的枚举对齐）
const ALL_STORY_BACKEND_STATES: string[] = [
    "submitted", "intake", "review", "rejected", "pm_refine", "design",
    "design_done", "pending_dev", "breakdown", "dev_assign", "in_progress",
    "dev_done", "pending_test", "testing", "bugfix",
    "test_done", "regression", "pending_release", "released", "done",
    "suspended",
];
const ALL_TASK_BACKEND_STATES: string[] = ["todo", "in_progress", "done", "closed"];
const ALL_BUG_BACKEND_STATES: string[] = [
    "open", "confirmed", "fixing", "resolved", "verified", "closed",
    "not_reproducible", "reopened", "by_design", "deferred", "suspended",
];

const PENDING_BACKEND_STATES: Record<WorkItemType, string[]> = {
    需求: ALL_STORY_BACKEND_STATES.filter((s) => !STORY_DONE_BACKEND_STATES.has(s)),
    任务: ALL_TASK_BACKEND_STATES.filter((s) => !TASK_DONE_BACKEND_STATES.has(s)),
    缺陷: ALL_BUG_BACKEND_STATES.filter((s) => !BUG_CLOSED_BACKEND_STATES.has(s)),
};

export function getPendingBackendStates(typeValue: WorkItemType): string[] {
    return PENDING_BACKEND_STATES[typeValue] ? [...PENDING_BACKEND_STATES[typeValue]] : [];
}

export function isPendingDisplayStatus(typeValue: WorkItemType, displayStatus: string): boolean {
    if (!displayStatus) return false;
    if (typeValue === "需求") return displayStatus !== "已完成";
    if (typeValue === "任务") return displayStatus !== "已完成" && displayStatus !== "已取消";
    return displayStatus !== "已修复" && displayStatus !== "已关闭";
}
const FALLBACK_DEMAND: StatusOption[] = [
    { label: "已取消", value: "已取消", icon: "x", iconClass: "text-red-500", syncable: true },
    { label: "收集中", value: "收集中", icon: "diamond", iconClass: "text-gray-400", syncable: true },
    { label: "意向", value: "意向", icon: "circle", iconClass: "text-gray-500", syncable: true },
    { label: "设计中", value: "设计中", icon: "pencil", iconClass: "text-indigo-500", syncable: true },
    { label: "设计完成", value: "设计完成", icon: "check", iconClass: "text-sky-600", syncable: true },
    { label: "待开发", value: "待开发", icon: "circle", iconClass: "text-purple-500", syncable: true },
    { label: "开发中", value: "开发中", icon: "circle-dot", iconClass: "text-blue-500", syncable: true },
    { label: "开发完成", value: "开发完成", icon: "check", iconClass: "text-emerald-500", syncable: true },
    { label: "待测试", value: "待测试", icon: "circle-minus", iconClass: "text-cyan-500", syncable: true },
    { label: "测试中", value: "测试中", icon: "circle-dashed", iconClass: "text-red-500", syncable: true },
    { label: "测试完成", value: "测试完成", icon: "check", iconClass: "text-violet-600", syncable: true },
    { label: "已测完回归中", value: "已测完回归中", icon: "circle-dot", iconClass: "text-blue-500", syncable: true },
    { label: "待发布", value: "待发布", icon: "circle-dot", iconClass: "text-amber-500", syncable: true },
    { label: "发布完成", value: "发布完成", icon: "check", iconClass: "text-emerald-500", syncable: true },
    { label: "已完成", value: "已完成", icon: "circle-check", iconClass: "text-emerald-500", syncable: true },
];
const FALLBACK_TASK: StatusOption[] = [
    { label: "待办的", value: "待办的", icon: "circle", iconClass: "text-gray-500" },
    { label: "进行中", value: "进行中", icon: "circle-dot", iconClass: "text-blue-500" },
    { label: "已完成", value: "已完成", icon: "circle-check", iconClass: "text-emerald-500" },
    { label: "已取消", value: "已取消", icon: "x", iconClass: "text-red-500" },
];
const FALLBACK_MAP: Record<WorkItemType, StatusOption[]> = {
    缺陷: FALLBACK_BUG, 需求: FALLBACK_DEMAND, 任务: FALLBACK_TASK,
};

// 兜底名单：仅在行数据没有原始 backend state 时使用（如本地 mock 行）。
// 注意它比后端完成态口径更宽（含开发完成/测试完成），优先走 _stateRaw 判断。
const OVERDUE_STALE_DONE_STATUSES = new Set([
    "已关闭", "已完成", "已修复", "发布完成", "测试完成", "开发完成", "已取消",
]);
const STORY_DEVELOPMENT_PENDING_DISPLAY_STATUSES = new Set([
    "收集中", "意向", "设计中", "设计完成", "待开发", "开发中",
]);
const OVERDUE_STALE_DAYS = 7;

type OverdueStaleRow = {
    status: string;
    type?: WorkItemType;
    planEndDate?: string;
    _stateRaw?: string;
    _lastActivityAtRaw?: string;
    _updatedAtRaw?: string;
};

/**
 * 完成态判断：与后端 /members/workload 卡片计数口径对齐。
 * 优先用行上的原始 backend state 对照 DONE 集合（需求仅 done/released 算完成，
 * 「开发完成」「测试完成」等中间态仍算在手）；无原始 state 时回退到显示状态名单。
 */
function isRowDoneForRisk(row: OverdueStaleRow): boolean {
    if (row._stateRaw && row.type) {
        return getDoneBackendStates(row.type).includes(row._stateRaw);
    }
    return OVERDUE_STALE_DONE_STATUSES.has(row.status);
}

/** 是否仍需按计划结束时间考核；需求进入待测试或后续状态后即退出。 */
export function isRowPendingForDeadline(row: OverdueStaleRow): boolean {
    if (row.type === "需求") {
        if (row._stateRaw) {
            return STORY_DEVELOPMENT_PENDING_BACKEND_STATES.has(row._stateRaw);
        }
        return STORY_DEVELOPMENT_PENDING_DISPLAY_STATUSES.has(row.status);
    }
    return !isRowDoneForRisk(row);
}

function getRowOverdueDays(row: OverdueStaleRow): number {
    const end = row.planEndDate;
    if (!end) return 0;
    const endDate = new Date(end + "T00:00:00");
    if (Number.isNaN(endDate.getTime())) return 0;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.max(0, Math.floor((today.getTime() - endDate.getTime()) / 86400000));
}

function getRowStaleDays(row: OverdueStaleRow): number {
    const lastRaw = row._lastActivityAtRaw || row._updatedAtRaw;
    if (!lastRaw) return 0;
    const lastTs = new Date(lastRaw).getTime();
    if (Number.isNaN(lastTs)) return 0;
    return Math.floor((Date.now() - lastTs) / 86400000);
}

/** 已逾期：仍需考核计划时间且截止日期已过（与成员卡片「逾」数字同口径） */
export function isRowOverdue(row: OverdueStaleRow): boolean {
    if (!isRowPendingForDeadline(row)) return false;
    return getRowOverdueDays(row) > 0;
}

/** 停滞：非完成态、未逾期、超过 7 天无活动（与成员卡片「滞」数字同口径，与逾期互斥） */
export function isRowStale(row: OverdueStaleRow): boolean {
    if (isRowDoneForRisk(row)) return false;
    if (isRowOverdue(row)) return false;
    return getRowStaleDays(row) >= OVERDUE_STALE_DAYS;
}

export function isRowOverdueOrStale(row: OverdueStaleRow): boolean {
    return isRowOverdue(row) || isRowStale(row);
}

/**
 * Sort key for overdue/stale rows: overdue first (by days desc), then stale (by days desc).
 * Returns negative value; more negative = higher priority.
 */
export function getOverdueStaleSortKey(row: OverdueStaleRow): number {
    if (isRowDoneForRisk(row)) return 0;
    const overdueDays = isRowPendingForDeadline(row) ? getRowOverdueDays(row) : 0;
    if (overdueDays > 0) return -(1_000_000 + overdueDays);
    const staleDays = getRowStaleDays(row);
    if (staleDays >= OVERDUE_STALE_DAYS) return -staleDays;
    return 0;
}

export function useWorkItemCommon() {
    const memberOptions = sharedMemberOptions;
    const ownerGroups = sharedOwnerGroups;

    const bugStatusFilterOptions = FALLBACK_BUG;
    const demandStatusFilterOptions = FALLBACK_DEMAND;
    const taskStatusFilterOptions = FALLBACK_TASK;

    const getStatusOptionsByType = (typeValue: WorkItemType): StatusOption[] => {
        const dynamic = buildOptionsForType(typeValue);
        return dynamic.length ? dynamic : (FALLBACK_MAP[typeValue] || FALLBACK_BUG);
    };

    const getStatusOption = (value: Status, typeValue?: WorkItemType) => {
        const options = typeValue ? getStatusOptionsByType(typeValue) : getStatusOptionsByType("缺陷");
        return options.find((x) => x.value === value) || options[0] || FALLBACK_BUG[0]!;
    };

    const loadStatusOptions = async () => {
        if (sharedApiStatuses.value.length > 0) return;
        if (statusLoadTask) return statusLoadTask;
        statusLoadTask = (async () => {
            try {
                const res: any = await getVortflowStatuses();
                const items = ((res?.items || []) as any[]).map((s: any): ApiStatusItem => ({
                    name: String(s.name || ""),
                    icon: String(s.icon || "○"),
                    icon_color: String(s.icon_color || "#64748b"),
                    command: String(s.command || ""),
                    work_item_types: Array.isArray(s.work_item_types) ? s.work_item_types : [],
                }));
                if (items.length) sharedApiStatuses.value = items;
            } catch { /* keep fallback */ } finally { statusLoadTask = null; }
        })();
        return statusLoadTask;
    };

    const priorityOptions: Array<{ label: string; value: Priority }> = [
        { label: "紧急", value: "urgent" },
        { label: "高", value: "high" },
        { label: "中", value: "medium" },
        { label: "低", value: "low" },
        { label: "无优先级", value: "none" }
    ];

    const priorityLabelMap: Record<Priority, string> = {
        urgent: "紧急",
        high: "高",
        medium: "中",
        low: "低",
        none: "无优先级"
    };

    const priorityClassMap: Record<Priority, string> = {
        urgent: "text-red-500 border-red-500 bg-red-50",
        high: "text-amber-500 border-amber-500 bg-amber-50",
        medium: "text-blue-500 border-blue-500 bg-blue-50",
        low: "text-emerald-500 border-emerald-500 bg-emerald-50",
        none: "text-gray-400 border-gray-300 bg-gray-50"
    };

    const avatarBgPalette = ["#2f80ed", "#5b8ff9", "#9b59b6", "#27ae60", "#f39c12", "#e67e22", "#16a085", "#8b44ad"];
    const getAvatarBg = (name: string): string => {
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
        return avatarBgPalette[hash % avatarBgPalette.length]!;
    };
    const getAvatarLabel = (name: string): string => name.slice(0, 1).toUpperCase();
    const getMemberAvatarUrl = (name: string): string => memberOptions.value.find((m) => m.name === name)?.avatarUrl || "";

    const getMemberIdByName = (name: string): string => {
        const normalized = String(name || "").trim();
        if (!normalized) return "";
        return memberOptions.value.find((m) => m.id === normalized)?.id
            || memberOptions.value.find((m) => m.name === normalized)?.id || "";
    };

    const getMemberNameById = (memberId: string): string => {
        const normalized = String(memberId || "").trim();
        if (!normalized) return "";
        return memberOptions.value.find((m) => m.id === normalized)?.name || "";
    };

    const loadMemberOptions = async () => {
        if (memberOptions.value.length > 0 && ownerGroups.value.length > 0) return;
        if (memberOptionsLoadTask) return memberOptionsLoadTask;

        memberOptionsLoadTask = (async () => {
            try {
                const { items: members } = await fetchAllPages<ApiMemberRecord>(async (page, size) => {
                    const res: any = await getMembersSimple({ search: "", page, size });
                    return { items: res?.members, total: res?.total };
                }, { pageSize: 100 });
                const next: MemberOption[] = [];
                const seenIds = new Set<string>();

                for (const item of members) {
                    const id = String(item?.id || "").trim();
                    const name = String(item?.name || "").trim();
                    if (!id || !name || seenIds.has(id)) continue;
                    seenIds.add(id);
                    next.push({
                        id,
                        name,
                        avatarUrl: String(item?.avatar_url || item?.avatar || "")
                    });
                }

                if (next.length > 0) {
                    memberOptions.value = next;
                    ownerGroups.value = buildOwnerGroupsFromMembers(members);
                    return;
                }
            } catch {
                // Keep fallback groups when the organization member API is unavailable.
            } finally {
                memberOptionsLoadTask = null;
            }

            ownerGroups.value = [];
        })();

        return memberOptionsLoadTask;
    };

    const getWorkItemTypeIconClass = (type: WorkItemType): string => {
        if (type === "需求") return "work-type-icon-demand";
        if (type === "任务") return "work-type-icon-task";
        return "work-type-icon-bug";
    };

    const getWorkItemTypeIcon = (type: WorkItemType): Component => {
        if (type === "需求") return Bookmark;
        if (type === "任务") return SquareCheck;
        return Bug;
    };

    const FALLBACK_STATE_MAP: Record<WorkItemType, Record<string, Status>> = {
        需求: {
            submitted: "收集中", intake: "意向", review: "意向", rejected: "已取消",
            pm_refine: "设计中", design: "设计中", design_done: "设计完成",
            pending_dev: "待开发",
            breakdown: "开发中", dev_assign: "开发中", in_progress: "开发中",
            dev_done: "开发完成",
            pending_test: "待测试",
            testing: "测试中",
            bugfix: "开发中",
            test_done: "测试完成",
            regression: "已测完回归中",
            pending_release: "待发布",
            released: "发布完成",
            done: "已完成",
        },
        任务: {
            todo: "待办的", in_progress: "进行中", done: "已完成",
            closed: "已取消", fixing: "进行中", resolved: "已完成", verified: "已完成",
        },
        缺陷: {
            open: "待确认", confirmed: "待确认", fixing: "修复中",
            resolved: "已修复", verified: "已关闭", closed: "已关闭",
        },
    };
    const FALLBACK_DEFAULT: Record<WorkItemType, Status> = {
        需求: "收集中", 任务: "待办的", 缺陷: "待确认",
    };

    const mapBackendStateToStatus = (typeValue: WorkItemType, stateValue: string): Status => {
        const normalized = String(stateValue || "").toLowerCase();
        const dynamicMap = buildStateToNameMap(typeValue);
        if (dynamicMap[normalized]) return dynamicMap[normalized] as Status;
        return (FALLBACK_STATE_MAP[typeValue]?.[normalized] || FALLBACK_DEFAULT[typeValue] || "待确认") as Status;
    };

    const mapBackendPriorityScore = (item: any, typeValue: WorkItemType): number => {
        const rawScore = item?.priority_score;
        if (rawScore != null && !Number.isNaN(Number(rawScore))) {
            return clampPriorityScore(Number(rawScore));
        }
        if (typeValue === "需求") {
            return backendPriorityLevelToScore(Number(item?.priority));
        }
        if (typeValue === "缺陷") {
            return backendPriorityLevelToScore(Number(item?.severity));
        }
        const estimate = Number(item?.estimate_hours || 0);
        if (estimate >= 16) return PRIORITY_SCORE_DEFAULTS.urgent;
        if (estimate >= 8) return PRIORITY_SCORE_DEFAULTS.high;
        if (estimate >= 4) return PRIORITY_SCORE_DEFAULTS.medium;
        return PRIORITY_SCORE_DEFAULTS.low;
    };

    const mapBackendPriority = (item: any, typeValue: WorkItemType): Priority => {
        return scoreToPriority(mapBackendPriorityScore(item, typeValue));
    };

    const formatCnTime = (d: Date): string => {
        const month = d.getMonth() + 1;
        const day = d.getDate();
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        return `${month}月${day}日 ${hh}:${mm}`;
    };

    const formatDate = (d: Date): string => {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    };

    const toBackendPriorityLevel = (value: Priority): number => {
        const map: Record<Priority, number> = { urgent: 1, high: 2, medium: 3, low: 4, none: 4 };
        return map[value] || 4;
    };

    const toTaskEstimateHours = (value: Priority): number => {
        const map: Record<Priority, number> = { urgent: 16, high: 8, medium: 4, low: 2, none: 2 };
        return map[value] || 2;
    };

    const FALLBACK_STATUS_TO_STATES: Record<WorkItemType, Partial<Record<Status, string[]>>> = {
        需求: {
            收集中: ["submitted"],
            意向: ["intake", "review"],
            已取消: ["rejected"],
            设计中: ["pm_refine", "design"],
            设计完成: ["design_done"],
            待开发: ["pending_dev"],
            开发中: ["breakdown", "dev_assign", "in_progress", "bugfix"],
            开发完成: ["dev_done"],
            待测试: ["pending_test"],
            测试中: ["testing"],
            测试完成: ["test_done"],
            已测完回归中: ["regression"],
            待发布: ["pending_release"],
            发布完成: ["released"],
            已完成: ["done"],
            暂搁置: ["suspended"],
        },
        任务: { 待办的: ["todo"], 进行中: ["in_progress"], 已完成: ["done"], 已取消: ["closed"] },
        缺陷: { 待确认: ["open", "confirmed"], 修复中: ["fixing"], 已修复: ["resolved"], 已关闭: ["verified", "closed"] },
    };

    const getBackendStatesByDisplayStatus = (typeValue: WorkItemType, statusValue: string): string[] | undefined => {
        const dynamicMap = buildNameToStatesMap(typeValue);
        if (dynamicMap[statusValue]) return dynamicMap[statusValue];
        return FALLBACK_STATUS_TO_STATES[typeValue]?.[statusValue as Status];
    };

    const getEnrichedOwnerGroups = async (projectId?: string): Promise<OwnerGroup[]> => {
        const projectNames = projectId ? await loadProjectMemberNames(projectId) : [];
        const recentNames = getRecentMemberNames();
        return buildEnrichedOwnerGroups(ownerGroups.value, projectNames, recentNames);
    };

    const defaultCollapsedGroups = (groups: OwnerGroup[]): string[] => {
        const hasProjectOrRecent = groups.some((g) => g.label === "项目参与人" || g.label === "最近选择");
        if (!hasProjectOrRecent) return [];
        return groups
            .filter((g) => g.label === "企业成员" || g.label === "离职人员")
            .map((g) => g.label);
    };

    return {
        memberOptions,
        ownerGroups,
        bugStatusFilterOptions,
        demandStatusFilterOptions,
        taskStatusFilterOptions,
        getStatusOptionsByType,
        getStatusOption,
        loadStatusOptions,
        priorityOptions,
        priorityLabelMap,
        priorityClassMap,
        getAvatarBg,
        getAvatarLabel,
        getMemberAvatarUrl,
        loadMemberOptions,
        getMemberIdByName,
        getMemberNameById,
        getWorkItemTypeIconClass,
        getWorkItemTypeIcon,
        mapBackendStateToStatus,
        mapBackendPriority,
        mapBackendPriorityScore,
        formatCnTime,
        formatDate,
        toBackendPriorityLevel,
        toTaskEstimateHours,
        getBackendStatesByDisplayStatus,
        getEnrichedOwnerGroups,
        defaultCollapsedGroups,
        recordRecentMember,
    };
}
