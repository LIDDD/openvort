export type WorkItemType = "缺陷" | "需求" | "任务";

export type Priority = "urgent" | "high" | "medium" | "low" | "none";

// 优先级精排分数 0-100：80-100=紧急 / 60-79=高 / 40-59=中 / 20-39=低 / 0-19=无
// 默认值=段起始值（紧急 80、高 60、中 40、低 20、无 0），同段内 score 越大越优先。
// 仅需求支持精排；任务/缺陷返回派生默认值。
export type PriorityScore = number;

export type Status =
    | "待确认"
    | "修复中"
    | "已修复"
    | "延期处理"
    | "延期修复"
    | "设计如此"
    | "再次打开"
    | "无法复现"
    | "已关闭"
    | "暂时搁置"
    | "已取消"
    | "已拒绝"
    | "收集中"
    | "意向"
    | "暂搁置"
    | "设计中"
    | "设计完成"
    | "待开发"
    | "开发中"
    | "开发完成"
    | "待测试"
    | "测试中"
    | "测试完成"
    | "已测完回归中"
    | "待发布"
    | "发布完成"
    | "已完成"
    | "待办的"
    | "进行中";

export type DateRange = [string, string];

export interface ViewFilters {
    owner?: string;
    status?: string;
    parentOnly?: boolean;
    creator?: string;
    participant?: string;
    archived?: boolean;
    /** 为 true 时忽略 archived，同时返回归档+未归档（「包含已归档」开关） */
    include_archived?: boolean;
}

export interface WorkItemTableProps {
    /** 工作项类型；不传或 "" 表示工作墙模式（跨类型聚合） */
    type?: WorkItemType | "";
    pageTitle?: string;
    createButtonText?: string;
    createDrawerTitle?: string;
    detailDrawerTitle?: string;
    descriptionPlaceholder?: string;
    useApi?: boolean;
    projectId?: string;
    /** 多项目筛选范围（浏览场景）；非空时优先于 projectId，空数组表示全部项目 */
    projectIds?: string[];
    iterationId?: string;
    viewFilters?: ViewFilters;
}

export interface AttachmentItem {
    name: string;
    url: string;
    size: number;
}

export interface NewBugForm {
    title: string;
    owner: string;
    collaborators: string[];
    type: WorkItemType;
    planTime: DateRange | [];
    project: string;
    projectId?: string;
    iteration: string;
    version: string;
    parentId?: string;
    storyId?: string;
    priority: Priority | "";
    /** 创建时的精排分数 0-100，仅需求生效；未设置时按 priority 派生段起始值。 */
    priorityScore?: PriorityScore;
    tags: string[];
    attachments: AttachmentItem[];
    repo: string;
    branch: string;
    startAt: string;
    endAt: string;
    remark: string;
    description: string;
}

export interface RowItem {
    backendId?: string;
    workNo: string;
    title: string;
    parentId?: string;
    parentTitle?: string;
    childrenCount?: number;
    taskCount?: number;
    isChild?: boolean;
    /** 手动排序键（仅需求有效），用于拖拽排序，按 ASC 排列 */
    sortOrder?: number | null;
    priority: Priority;
    /** 精排分数 0-100，仅需求(story)有真实值；任务/缺陷为派生默认值。 */
    priorityScore?: PriorityScore;
    tags: string[];
    status: Status;
    createdAt: string;
    updatedAt?: string;
    collaborators: string[];
    /** 服务端已保存的协作者 ID，用于保留或移除已不在成员列表中的历史成员。 */
    collaboratorIds?: string[];
    type: WorkItemType;
    planTime: DateRange;
    planStartDate?: string;
    planEndDate?: string;
    description: string;
    ownerId?: string;
    owner: string;
    creator: string;
    projectId?: string;
    projectName?: string;
    iterationId?: string;
    iteration?: string;
    versionId?: string;
    version?: string;
    progress?: number;
    estimateHours?: number | string;
    loggedHours?: number | string;
    remainHours?: number | string;
    repoId?: string;
    repo?: string;
    branch?: string;
    attachments?: AttachmentItem[];
    startAt?: string;
    endAt?: string;
    testTime?: string;
    draftTime?: string;
    releaseTime?: string;
    isArchived?: boolean;
    children?: RowItem[];
    _prevIteration?: string;
    _prevVersion?: string;
    /** 后端原始 state（如 dev_done/todo/fixing），用于逾期/停滞等与后端口径对齐的判断 */
    _stateRaw?: string;
    _createdAtRaw?: string;
    _updatedAtRaw?: string;
    _lastActivityAtRaw?: string;
}

export interface DetailComment {
    id: string;
    author: string;
    authorId?: string;
    createdAt: string;
    content: string;
    parentId?: number | null;
    parentAuthor?: string;
    parentContent?: string;
}

export interface DetailLogExpandable {
    label: string;
    before: string;
    after: string;
}

export interface DetailLog {
    id: string;
    actor: string;
    createdAt: string;
    action: string;
    expandableChanges?: DetailLogExpandable[];
}

export interface CreateBugAttachment {
    id: string;
    name: string;
    size: number;
}

export interface MemberOption {
    id: string;
    name: string;
    avatarUrl: string;
}

export interface StatusOption {
    label: string;
    value: Status;
    icon: string;
    iconClass: string;
    iconColor?: string;
    /** false 表示该状态没有对应的后端 state（command 为空），点击后无法同步到后端。 */
    syncable?: boolean;
}
