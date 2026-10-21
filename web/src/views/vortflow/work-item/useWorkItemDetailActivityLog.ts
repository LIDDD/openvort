import { computed, reactive, type ComputedRef, type Ref } from "vue";
import { getVortflowActivity } from "@/api";
import type {
    DetailLog,
    DetailLogExpandable,
    RowItem,
} from "@/components/vort-biz/work-item/WorkItemTable.types";

export interface UseWorkItemDetailActivityLogOptions {
    /** 当前打开的工作项；用于读取类型展示与字段值格式化 */
    record: Ref<RowItem | null>;
    /** 当前抽屉对应的 workNo（作为 logsMap 的 key） */
    workNo: ComputedRef<string>;
    /** 当前操作人显示名（用于本地新增日志时的 actor） */
    currentUser: ComputedRef<string>;
    /** 把成员 ID 转成显示名 */
    getMemberNameById: (id: string) => string;
}

export interface ActivityLogResult {
    action: string;
    expandableChanges?: DetailLogExpandable[];
}

/**
 * 工作项详情面板「操作日志」相关状态与工具。
 *
 * 抽离自 WorkItemDetail.vue 阶段 D1：
 * - 日志状态（detailLogsMap / logExpandedMap）
 * - 字段标签 / 状态标签 / 优先级标签三套常量
 * - 字段值渲染（formatFieldValue / stringifyLongValue / truncateText）
 * - 日志条目格式化（formatActivityLog）
 * - 远程加载 + 本地追加（loadActivityLogs / appendDetailLog）
 *
 * 故意暴露 formatTimeAgo，因为评论侧 composable 需要复用它格式化 created_at。
 */
export function useWorkItemDetailActivityLog(opts: UseWorkItemDetailActivityLogOptions) {
    const detailLogsMap = reactive<Record<string, DetailLog[]>>({});
    const logExpandedMap = reactive<Record<string, boolean>>({});

    const detailLogs = computed<DetailLog[]>(() => {
        const id = opts.workNo.value;
        return id ? detailLogsMap[id] || [] : [];
    });

    const toggleLogExpand = (logId: string) => {
        logExpandedMap[logId] = !logExpandedMap[logId];
    };

    const formatTimeAgo = (isoStr: string): string => {
        if (!isoStr) return "";
        const d = new Date(isoStr);
        const now = Date.now();
        const diff = now - d.getTime();
        if (diff < 60_000) return "刚刚";
        if (diff < 3600_000) return `${Math.floor(diff / 60_000)}分钟前`;
        if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}小时前`;
        const month = d.getMonth() + 1;
        const day = d.getDate();
        const h = String(d.getHours()).padStart(2, "0");
        const m = String(d.getMinutes()).padStart(2, "0");
        return `${month}月${day}日 ${h}:${m}`;
    };

    const FIELD_LABEL_MAP: Record<string, string> = {
        title: "名称", description: "描述", state: "状态", priority: "优先级",
        priority_score: "优先级精排分数",
        assignee_id: "负责人", pm_id: "负责人", estimate_hours: "预估工时",
        actual_hours: "实际工时", tags: "标签", collaborators: "协作者",
        deadline: "截止日期", project_id: "项目", project_name: "项目",
        plan_start: "计划开始时间",
        start_at: "开始时间", end_at: "结束时间",
        repo_id: "关联仓库", repo_name: "关联仓库", branch: "关联分支",
        severity: "严重程度", task_type: "任务类型", parent_id: "父级",
        iteration_id: "迭代", iteration: "迭代",
        version_id: "版本", version: "版本",
        progress: "进度", attachments: "附件",
        test_time: "提测时间", draft_time: "出稿时间", release_time: "发布时间",
    };

    const LONG_TEXT_FIELDS = new Set(["description"]);

    const STATE_LABEL_MAP: Record<string, string> = {
        submitted: "收集中", intake: "意向", review: "评审", rejected: "已取消",
        pm_refine: "需求细化", design: "设计中", design_done: "设计完成",
        pending_dev: "待开发", breakdown: "任务拆解",
        dev_assign: "待分配", in_progress: "进行中", testing: "测试中",
        bugfix: "修复缺陷", done: "已完成",
        todo: "待办的", closed: "已关闭",
        open: "待确认", confirmed: "已确认",
        fixing: "修复中", resolved: "已修复", verified: "已验证",
        reopened: "重新打开", not_reproducible: "无法复现",
        by_design: "设计如此", deferred: "延期处理", suspended: "已挂起",
    };

    const PRIORITY_LEVEL_LABEL: Record<string, string> = {
        urgent: "紧急", high: "高", medium: "中", low: "低", none: "无",
    };

    const formatFieldValue = (key: string, value: any): string => {
        if (value == null || value === "") return "空";
        if (LONG_TEXT_FIELDS.has(key)) return "（已更新）";
        if (key === "assignee_id" || key === "pm_id") {
            return opts.getMemberNameById(String(value)) || String(value);
        }
        if (key === "collaborators" && Array.isArray(value)) {
            return value.map(v => opts.getMemberNameById(String(v)) || String(v)).join("、") || "空";
        }
        if (key === "tags" && Array.isArray(value)) return value.join("、") || "空";
        if (key === "attachments") {
            if (Array.isArray(value)) {
                const names = value.map(v => (v && typeof v === "object" ? v.name : String(v))).filter(Boolean);
                return names.length ? names.join("、") : "空";
            }
            return String(value);
        }
        if (key === "state") return STATE_LABEL_MAP[String(value)] || String(value);
        if (key === "priority") {
            if (typeof value === "string") return PRIORITY_LEVEL_LABEL[value] || String(value);
            const m: Record<number, string> = { 1: "紧急", 2: "高", 3: "中", 4: "低" };
            return m[value] || String(value);
        }
        if (key === "severity") {
            const m: Record<number, string> = { 1: "致命", 2: "严重", 3: "一般", 4: "轻微" };
            return m[value] || String(value);
        }
        if (key === "estimate_hours" || key === "actual_hours") {
            const n = Number(value);
            return Number.isFinite(n) ? `${n}h` : String(value);
        }
        if (key === "progress") {
            const n = Number(value);
            return Number.isFinite(n) ? `${n}%` : String(value);
        }
        return String(value);
    };

    const truncateText = (text: string, max: number): string => {
        if (!text) return "";
        return text.length > max ? text.slice(0, max) + "..." : text;
    };

    const stringifyLongValue = (value: any): string => {
        if (value == null) return "";
        if (typeof value === "string") return value;
        try {
            return JSON.stringify(value, null, 2);
        } catch {
            return String(value);
        }
    };

    const formatActivityLog = (action: string, detailRaw: any): ActivityLogResult => {
        let detail: Record<string, any> = {};
        if (typeof detailRaw === "string") {
            try { detail = JSON.parse(detailRaw); } catch { /* ignore */ }
        } else if (detailRaw && typeof detailRaw === "object") {
            detail = detailRaw;
        }
        if (action === "created") {
            const title = detail.title ? `「${detail.title}」` : "";
            return { action: `创建了工作项${title}` };
        }
        if (action === "state_changed") {
            const fromLabel = STATE_LABEL_MAP[detail.from] || detail.from || "?";
            const toLabel = STATE_LABEL_MAP[detail.to] || detail.to || "?";
            return { action: `将状态由"${fromLabel}"改为"${toLabel}"` };
        }
        if (action === "updated") {
            const keys = Object.keys(detail);
            if (!keys.length) return { action: "更新了工作项" };
            const expandable: DetailLogExpandable[] = [];
            const parts = keys.map(k => {
                const label = FIELD_LABEL_MAP[k] || k;
                const entry = detail[k];
                if (entry && typeof entry === "object" && "to" in entry) {
                    const fromVal = formatFieldValue(k, entry.from);
                    const toVal = formatFieldValue(k, entry.to);
                    if (LONG_TEXT_FIELDS.has(k)) {
                        expandable.push({
                            label,
                            before: stringifyLongValue(entry.from),
                            after: stringifyLongValue(entry.to),
                        });
                    }
                    return `${label}由"${fromVal}"改为"${toVal}"`;
                }
                const val = formatFieldValue(k, entry);
                return `${label}→"${val}"`;
            });
            return {
                action: `修改了${parts.join("、")}`,
                expandableChanges: expandable.length ? expandable : undefined,
            };
        }
        if (action === "deleted") return { action: `删除了工作项${detail.title ? `「${detail.title}」` : ""}` };
        if (action === "comment_added") {
            const preview = String(detail.preview || "").trim();
            if (!preview) return { action: "添加了评论" };
            const inline = truncateText(preview, 50);
            const expandableChanges: DetailLogExpandable[] | undefined = preview.length > 50
                ? [{ label: "评论内容", before: "", after: preview }]
                : undefined;
            return { action: `添加了评论："${inline}"`, expandableChanges };
        }
        if (action === "comment_updated") {
            const fromText = String(detail.from || "");
            const toText = String(detail.to || "");
            if (!fromText && !toText) return { action: "修改了评论" };
            const fromInline = truncateText(fromText, 30) || "空";
            const toInline = truncateText(toText, 30) || "空";
            const expandableChanges: DetailLogExpandable[] | undefined = (fromText.length > 30 || toText.length > 30)
                ? [{ label: "评论内容", before: fromText, after: toText }]
                : undefined;
            return { action: `修改了评论：由"${fromInline}"改为"${toInline}"`, expandableChanges };
        }
        if (action === "comment_deleted") {
            const preview = String(detail.preview || "").trim();
            if (!preview) return { action: "删除了评论" };
            const inline = truncateText(preview, 50);
            const expandableChanges: DetailLogExpandable[] | undefined = preview.length > 50
                ? [{ label: "评论内容", before: preview, after: "" }]
                : undefined;
            return { action: `删除了评论："${inline}"`, expandableChanges };
        }
        if (action === "link_added") return { action: "添加了关联工作项" };
        if (action === "link_removed") return { action: "移除了关联工作项" };
        if (action === "doc_linked") return { action: "关联了文档" };
        if (action === "doc_created") return { action: "创建了文档" };
        if (action === "doc_uploaded") return { action: "上传了文档" };
        if (action === "doc_unlinked") return { action: "取消关联文档" };
        if (action === "member_added") return { action: "添加了成员" };
        if (action === "member_removed") return { action: "移除了成员" };
        if (action === "member_role_changed") return { action: "修改了成员角色" };
        if (action === "story_added") return { action: "添加了需求" };
        if (action === "story_removed") return { action: "移除了需求" };
        if (action === "task_added") return { action: "添加了任务" };
        if (action === "task_removed") return { action: "移除了任务" };
        if (action === "bug_added") return { action: "添加了缺陷" };
        if (action === "bug_removed") return { action: "移除了缺陷" };
        if (action === "released") return { action: "已发布" };
        return { action };
    };

    /** 远程加载历史活动日志，按 workNo 写入 detailLogsMap */
    const loadActivityLogs = async (entityType: string, entityId: string) => {
        const workNo = opts.workNo.value;
        if (!workNo) return;
        try {
            const res: any = await getVortflowActivity(entityType, entityId);
            const items = ((res?.items) || []) as any[];
            detailLogsMap[workNo] = items.map((e: any) => {
                const formatted = formatActivityLog(e.action, e.detail);
                return {
                    id: String(e.id),
                    actor: opts.getMemberNameById(e.actor_id) || e.actor_id || "系统",
                    createdAt: formatTimeAgo(e.created_at),
                    action: formatted.action,
                    expandableChanges: formatted.expandableChanges,
                };
            });
        } catch {
            if (!detailLogsMap[workNo]) detailLogsMap[workNo] = [];
        }
    };

    /** 没有 backendId 的草稿工作项也要保证 logsMap 存在空数组 */
    const ensureLogsForCurrentWorkNo = () => {
        const workNo = opts.workNo.value;
        if (!workNo) return;
        if (!detailLogsMap[workNo]) detailLogsMap[workNo] = [];
    };

    /** 本地乐观追加一条「刚刚」时间的日志 */
    const appendDetailLog = (action: string, detail?: any) => {
        const workNo = opts.workNo.value;
        if (!workNo) return;
        if (!detailLogsMap[workNo]) detailLogsMap[workNo] = [];
        const logs = detailLogsMap[workNo];
        if (!logs) return;
        let displayAction = action;
        let expandableChanges: DetailLogExpandable[] | undefined;
        if (detail !== undefined) {
            const formatted = formatActivityLog(action, detail);
            displayAction = formatted.action;
            expandableChanges = formatted.expandableChanges;
        }
        logs.unshift({
            id: `${workNo}-l-${Date.now()}`,
            actor: opts.currentUser.value,
            createdAt: "刚刚",
            action: displayAction,
            expandableChanges,
        });
    };

    return {
        detailLogsMap,
        logExpandedMap,
        detailLogs,
        toggleLogExpand,
        formatTimeAgo,
        formatActivityLog,
        appendDetailLog,
        loadActivityLogs,
        ensureLogsForCurrentWorkNo,
    };
}
