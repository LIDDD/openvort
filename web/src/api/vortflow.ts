import request from "@/utils/request";
import { fetchAllPages, type PaginatedItems } from "./iterationOptions";

// ---- Dashboard ----

export function getVortflowStats(project_id?: string, project_ids?: string) {
    const params: Record<string, string> = {};
    if (project_ids) params.project_ids = project_ids;
    else if (project_id) params.project_id = project_id;
    return request.get("/vortflow/dashboard/stats", { params });
}

/** 单成员工作量聚合（成员关注面板用）。后端 dashboard.py members_workload */
export interface MemberWorkloadItem {
    member_id: string;
    /** 在手未完成总数 */
    pending_total: number;
    /** 按工作项类型拆分的在手数 */
    by_type: { story: number; task: number; bug: number };
    /** 逾期数（需求仅统计待测试前；任务/缺陷统计未完成，且 deadline < 今日 0 点） */
    overdue: number;
    /** 即将到期数（今日 0 点 <= deadline < 今日 0 点 + due_soon_days+1 天） */
    due_soon: number;
    /** 紧急/严重数（需求 priority∈1,2，缺陷 severity∈1,2） */
    urgent: number;

    /** 最近 velocity_days 天完成数（按 end_at 落地） */
    completed_recent: number;
    /** 上一个 velocity_days 天完成数（同比基线） */
    completed_prev: number;
    /** 个人平均流转天数（end_at - start_at） */
    avg_lead_time_days: number;
    /** 本批成员的团队均值流转天数（同窗口、同过滤） */
    team_avg_lead_time_days: number;

    /**
     * 在手项中超过 stale_days 没有 Event/Comment 且 **未逾期** 的数量。
     * 注意：与 overdue 互斥，已逾期项不会重复计入此处。
     */
    stale_count: number;

    /** 长度 history_days 的活动数组（旧→新），FlowEvent + FlowComment 每日总数 */
    activity_7d: number[];
    /** 长度 history_days 的在手数估算（旧→新） */
    pending_history_7d: number[];
    /** 长度 history_days 的每日完成数（旧→新） */
    daily_completed?: number[];
    /** 长度 history_days 的每日新增数（旧→新） */
    daily_created?: number[];
    /** 长度 forecast_days 的未来每日到期数（明天→远期） */
    future_due?: number[];
    /** 长度 forecast_days 的未来每日累计逾期数（含当前已逾期，明天→远期） */
    future_overdue_cumulative?: number[];
}

export function getVortflowMembersWorkload(params: {
    member_ids: string;
    project_id?: string;
    project_ids?: string;
    iteration_id?: string;
    due_soon_days?: number;
    history_days?: number;
    forecast_days?: number;
    velocity_days?: number;
    stale_days?: number;
}): Promise<MemberWorkloadItem[]> {
    return request.get("/vortflow/members/workload", { params });
}

// ---- Projects ----

export function getVortflowProjects() {
    return request.get("/vortflow/projects");
}

export function getVortflowProject(id: string) {
    return request.get(`/vortflow/projects/${id}`);
}

export function createVortflowProject(data: {
    name: string; code?: string; color?: string; description?: string;
    start_date?: string; end_date?: string;
    owner_id?: string; member_ids?: string[]; repo_ids?: string[];
}) {
    return request.post("/vortflow/projects", data);
}

export function updateVortflowProject(id: string, data: {
    name?: string; code?: string; color?: string; description?: string;
    start_date?: string; end_date?: string;
    owner_id?: string;
}) {
    return request.put(`/vortflow/projects/${id}`, data);
}

export function deleteVortflowProject(id: string) {
    return request.delete(`/vortflow/projects/${id}`);
}

export function starVortflowProject(id: string) {
    return request.put(`/vortflow/projects/${id}/star`);
}

export function unstarVortflowProject(id: string) {
    return request.delete(`/vortflow/projects/${id}/star`);
}

export function getVortflowProjectMembers(projectId: string) {
    return request.get(`/vortflow/projects/${projectId}/members`);
}

export function addVortflowProjectMember(projectId: string, data: { member_id: string; role?: string }) {
    return request.post(`/vortflow/projects/${projectId}/members`, data);
}

export function updateVortflowProjectMemberRole(projectId: string, memberId: string, role: string) {
    return request.put(`/vortflow/projects/${projectId}/members/${memberId}`, { member_id: memberId, role });
}

export function removeVortflowProjectMember(projectId: string, memberId: string) {
    return request.delete(`/vortflow/projects/${projectId}/members/${memberId}`);
}

// ---- Stories ----

export function getVortflowStories(params: { project_id?: string; project_ids?: string; state?: string; keyword?: string; priority?: number; parent_id?: string; submitter_id?: string; assignee_id?: string; pm_id?: string; participant_id?: string; iteration_id?: string; archived?: boolean; include_archived?: boolean; sort_by?: string; sort_order?: string; page?: number; page_size?: number }) {
    return request.get("/vortflow/stories", { params });
}

export function getVortflowStory(id: string) {
    return request.get(`/vortflow/stories/${id}`);
}

export function createVortflowStory(data: { project_id: string; title: string; description?: string; priority?: number; priority_score?: number; parent_id?: string; assignee_id?: string; tags?: string[]; collaborators?: string[]; attachments?: { name: string; url: string; size: number }[]; plan_start?: string; deadline?: string; start_at?: string; end_at?: string; test_time?: string; draft_time?: string; release_time?: string; repo_id?: string; branch?: string }) {
    return request.post("/vortflow/stories", data);
}

export function updateVortflowStory(id: string, data: {
    title?: string;
    description?: string;
    state?: string;
    priority?: number;
    priority_score?: number;
    parent_id?: string | null;
    assignee_id?: string | null;
    tags?: string[];
    collaborators?: string[];
    attachments?: { name: string; url: string; size: number }[];
    plan_start?: string;
    deadline?: string;
    test_time?: string;
    draft_time?: string;
    release_time?: string;
    pm_id?: string | null;
    project_id?: string | null;
    start_at?: string;
    end_at?: string;
    repo_id?: string | null;
    branch?: string;
    progress?: number;
}) {
    return request.put(`/vortflow/stories/${id}`, data);
}

export function deleteVortflowStory(id: string) {
    return request.delete(`/vortflow/stories/${id}`);
}

export function copyVortflowStory(id: string) {
    return request.post(`/vortflow/stories/${id}/copy`);
}

export function transitionVortflowStory(id: string, target_state: string) {
    return request.post(`/vortflow/stories/${id}/transition`, { target_state });
}

/**
 * 拖拽排序：支持同 parent 内调序，或跨 parent（含挪到顶层，传 parent_id=null）。
 * 参数语义：
 * - before_id: source 落到该需求之前
 * - after_id:  source 落到该需求之后
 * - parent_id: 显式指定父节点；和锚点同时传时以锚点的 parent 为准
 */
export function reorderVortflowStory(id: string, data: {
    parent_id?: string | null;
    before_id?: string;
    after_id?: string;
}) {
    return request.post(`/vortflow/stories/${id}/reorder`, data);
}

/**
 * 任务拖拽排序：支持同 parent 内调序、跨 story 移动、嵌入到需求/任务下。
 * - 拖到任务 same parent 同级 → 仅排序
 * - 拖到任务 inside → 成为该任务的子任务（同 story）
 * - 拖到需求 inside → story_id 改为该需求，parent_id 清空
 */
export function reorderVortflowTask(id: string, data: {
    story_id?: string | null;
    parent_id?: string | null;
    before_id?: string;
    after_id?: string;
}) {
    return request.post(`/vortflow/tasks/${id}/reorder`, data);
}

/**
 * 缺陷拖拽排序：缺陷之间没有父子关系，但可嵌入到需求/任务下。
 * - 拖到缺陷 same parent 同级 → 仅排序
 * - 拖到需求 inside → story_id 改为该需求，task_id 清空
 * - 拖到任务 inside → task_id 改为该任务，story_id 继承自任务
 */
export function reorderVortflowBug(id: string, data: {
    story_id?: string | null;
    task_id?: string | null;
    before_id?: string;
    after_id?: string;
}) {
    return request.post(`/vortflow/bugs/${id}/reorder`, data);
}

export function getVortflowStoryTransitions(id: string) {
    return request.get(`/vortflow/stories/${id}/transitions`);
}

// ---- Tasks ----

export function getVortflowTasks(params: { story_id?: string; parent_id?: string; state?: string; task_type?: string; assignee_id?: string; keyword?: string; project_id?: string; project_ids?: string; creator_id?: string; participant_id?: string; iteration_id?: string; archived?: boolean; include_archived?: boolean; sort_by?: string; sort_order?: string; page?: number; page_size?: number }) {
    return request.get("/vortflow/tasks", { params });
}

export function getVortflowTask(id: string) {
    return request.get(`/vortflow/tasks/${id}`);
}

export function createVortflowTask(data: { project_id?: string; story_id?: string; parent_id?: string; title: string; description?: string; task_type?: string; assignee_id?: string; tags?: string[]; collaborators?: string[]; attachments?: { name: string; url: string; size: number }[]; estimate_hours?: number; priority_score?: number; plan_start?: string; deadline?: string; start_at?: string; end_at?: string; repo_id?: string; branch?: string }) {
    return request.post("/vortflow/tasks", data);
}

export function updateVortflowTask(id: string, data: {
    project_id?: string | null;
    title?: string;
    description?: string;
    task_type?: string;
    state?: string;
    assignee_id?: string;
    tags?: string[];
    collaborators?: string[];
    attachments?: { name: string; url: string; size: number }[];
    estimate_hours?: number;
    actual_hours?: number;
    plan_start?: string;
    deadline?: string;
    start_at?: string;
    end_at?: string;
    repo_id?: string | null;
    branch?: string;
    progress?: number;
    priority_score?: number;
}) {
    return request.put(`/vortflow/tasks/${id}`, data);
}

export function deleteVortflowTask(id: string) {
    return request.delete(`/vortflow/tasks/${id}`);
}

export function copyVortflowTask(id: string) {
    return request.post(`/vortflow/tasks/${id}/copy`);
}

export function transitionVortflowTask(id: string, target_state: string) {
    return request.post(`/vortflow/tasks/${id}/transition`, { target_state });
}

export function getVortflowTaskTransitions(id: string) {
    return request.get(`/vortflow/tasks/${id}/transitions`);
}

// ---- Bugs ----

export function getVortflowBugs(params: { story_id?: string; state?: string; severity?: number; assignee_id?: string; keyword?: string; project_id?: string; project_ids?: string; reporter_id?: string; participant_id?: string; iteration_id?: string; archived?: boolean; include_archived?: boolean; sort_by?: string; sort_order?: string; page?: number; page_size?: number }) {
    return request.get("/vortflow/bugs", { params });
}

export function getVortflowBug(id: string) {
    return request.get(`/vortflow/bugs/${id}`);
}

export function createVortflowBug(data: { project_id?: string; story_id?: string; task_id?: string; title: string; description?: string; severity?: number; priority_score?: number; assignee_id?: string; tags?: string[]; collaborators?: string[]; attachments?: { name: string; url: string; size: number }[]; plan_start?: string; deadline?: string; start_at?: string; end_at?: string; repo_id?: string; branch?: string }) {
    return request.post("/vortflow/bugs", data);
}

export function updateVortflowBug(id: string, data: {
    project_id?: string | null;
    title?: string;
    description?: string;
    severity?: number;
    state?: string;
    assignee_id?: string;
    developer_id?: string;
    tags?: string[];
    collaborators?: string[];
    attachments?: { name: string; url: string; size: number }[];
    estimate_hours?: number;
    actual_hours?: number;
    plan_start?: string;
    deadline?: string;
    start_at?: string;
    end_at?: string;
    repo_id?: string | null;
    branch?: string;
    priority_score?: number;
}) {
    return request.put(`/vortflow/bugs/${id}`, data);
}

export function deleteVortflowBug(id: string) {
    return request.delete(`/vortflow/bugs/${id}`);
}

export function copyVortflowBug(id: string) {
    return request.post(`/vortflow/bugs/${id}/copy`);
}

export function transitionVortflowBug(id: string, target_state: string) {
    return request.post(`/vortflow/bugs/${id}/transition`, { target_state });
}

export function getVortflowBugTransitions(id: string) {
    return request.get(`/vortflow/bugs/${id}/transitions`);
}

// ---- Archive ----

export function batchArchiveWorkItems(data: { ids: string[]; type: string; archived: boolean }) {
    return request.post("/vortflow/work-items/batch-archive", data);
}

// ---- Work Wall (跨类型聚合查询) ----

export function getVortflowWorkItems(params: {
    types?: string;
    project_id?: string;
    project_ids?: string;
    iteration_id?: string;
    state?: string;
    keyword?: string;
    assignee_id?: string;
    creator_id?: string;
    participant_id?: string;
    archived?: boolean;
    include_archived?: boolean;
    sort_by?: string;
    sort_order?: string;
    page?: number;
    page_size?: number;
    /** 「当日已完成」过滤起点（ISO datetime）：仅对 done 类型 state 强制 end_at>=该时间 */
    completed_after?: string;
}) {
    return request.get("/vortflow/work-items", { params });
}

// ---- Work Item Links ----

export function getVortflowWorkItemLinks(params: { entity_type: string; entity_id: string }) {
    return request.get("/vortflow/work-item-links", { params });
}

export function createVortflowWorkItemLink(data: { source_type: string; source_id: string; target_type: string; target_id: string }) {
    return request.post("/vortflow/work-item-links", data);
}

export function deleteVortflowWorkItemLink(linkId: string) {
    return request.delete(`/vortflow/work-item-links/${linkId}`);
}

// ---- Events ----

export function getVortflowEvents(params: { entity_type?: string; entity_id?: string; page?: number; page_size?: number }) {
    return request.get("/vortflow/events", { params });
}

export function generateVortflowDescriptionPrompt(entityType: string, projectName: string, title: string) {
    return request.get("/vortflow/generate-description-prompt", {
        params: { entity_type: entityType, project_name: projectName, title },
    });
}

// ---- Iterations ----

export interface VortflowIterationListParams {
    project_id?: string;
    project_ids?: string;
    status?: string;
    keyword?: string;
    owner_id?: string;
    page?: number;
    page_size?: number;
}

export function getVortflowIterations(params: VortflowIterationListParams = {}) {
    return request.get("/vortflow/iterations", { params });
}

/**
 * 获取需要完整迭代列表的展示/导航场景数据。
 *
 * `/iterations` 是分页接口，不能把第一页误当成完整选项列表；这里按返回的
 * total 自动继续请求后续页，同时遵守服务端 page_size 上限。
 */
export async function getAllVortflowIterations(
    params: Omit<VortflowIterationListParams, "page"> = {},
) {
    const { page_size: requestedPageSize, ...filters } = params;
    return fetchAllPages<any>(
        (page, pageSize) => getVortflowIterations({
            ...filters,
            page,
            page_size: pageSize,
        }) as Promise<PaginatedItems<any>>,
        { pageSize: requestedPageSize ?? 200, maxPageSize: 200 },
    );
}

export function getVortflowIteration(id: string) {
    return request.get(`/vortflow/iterations/${id}`);
}

export function getVortflowIterationHealth(id: string) {
    return request.get(`/vortflow/iterations/${id}/health`);
}

export function createVortflowIteration(data: {
    project_id: string;
    name: string;
    goal?: string;
    owner_id?: string;
    start_date?: string;
    end_date?: string;
    status?: string;
    estimate_hours?: number;
}) {
    return request.post("/vortflow/iterations", data);
}

export function updateVortflowIteration(id: string, data: {
    name?: string;
    goal?: string;
    owner_id?: string;
    start_date?: string;
    end_date?: string;
    status?: string;
    estimate_hours?: number;
}) {
    return request.put(`/vortflow/iterations/${id}`, data);
}

export function deleteVortflowIteration(id: string) {
    return request.delete(`/vortflow/iterations/${id}`);
}

export function getVortflowIterationStories(iterationId: string) {
    return request.get(`/vortflow/iterations/${iterationId}/stories`);
}

export function addVortflowIterationStory(iterationId: string, data: { story_id: string; story_order?: number }) {
    return request.post(`/vortflow/iterations/${iterationId}/stories`, data);
}

export function removeVortflowIterationStory(iterationId: string, storyId: string) {
    return request.delete(`/vortflow/iterations/${iterationId}/stories/${storyId}`);
}

export function getVortflowIterationTasks(iterationId: string) {
    return request.get(`/vortflow/iterations/${iterationId}/tasks`);
}

export function addVortflowIterationTask(iterationId: string, data: { task_id: string; task_order?: number }) {
    return request.post(`/vortflow/iterations/${iterationId}/tasks`, data);
}

export function removeVortflowIterationTask(iterationId: string, taskId: string) {
    return request.delete(`/vortflow/iterations/${iterationId}/tasks/${taskId}`);
}

export function addVortflowIterationBug(iterationId: string, data: { bug_id: string; bug_order?: number }) {
    return request.post(`/vortflow/iterations/${iterationId}/bugs`, data);
}

export function removeVortflowIterationBug(iterationId: string, bugId: string) {
    return request.delete(`/vortflow/iterations/${iterationId}/bugs/${bugId}`);
}

// ---- Versions ----

export function getVortflowVersions(params: { project_id?: string; project_ids?: string; status?: string; keyword?: string; owner_id?: string; page?: number; page_size?: number }) {
    return request.get("/vortflow/versions", { params });
}

export function getVortflowVersion(id: string) {
    return request.get(`/vortflow/versions/${id}`);
}

export function createVortflowVersion(data: {
    project_id: string;
    name: string;
    description?: string;
    owner_id?: string;
    planned_release_at?: string;
    actual_release_at?: string;
    progress?: number;
    release_date?: string;
    status?: string;
    release_log?: string;
}) {
    return request.post("/vortflow/versions", data);
}

export function updateVortflowVersion(id: string, data: {
    name?: string;
    description?: string;
    owner_id?: string;
    planned_release_at?: string;
    actual_release_at?: string;
    progress?: number;
    release_date?: string;
    status?: string;
    release_log?: string;
}) {
    return request.put(`/vortflow/versions/${id}`, data);
}

export function deleteVortflowVersion(id: string) {
    return request.delete(`/vortflow/versions/${id}`);
}

export function releaseVortflowVersion(id: string) {
    return request.post(`/vortflow/versions/${id}/release`);
}

export function getVortflowVersionStories(versionId: string) {
    return request.get(`/vortflow/versions/${versionId}/stories`);
}

export function addVortflowVersionStory(versionId: string, data: { story_id: string; added_reason?: string; story_order?: number }) {
    return request.post(`/vortflow/versions/${versionId}/stories`, data);
}

export function removeVortflowVersionStory(versionId: string, storyId: string) {
    return request.delete(`/vortflow/versions/${versionId}/stories/${storyId}`);
}

export function addVortflowVersionBug(versionId: string, data: { bug_id: string; bug_order?: number }) {
    return request.post(`/vortflow/versions/${versionId}/bugs`, data);
}

export function removeVortflowVersionBug(versionId: string, bugId: string) {
    return request.delete(`/vortflow/versions/${versionId}/bugs/${bugId}`);
}

// ---- Comments & Activity ----

export function getVortflowComments(entityType: string, entityId: string) {
    return request.get(`/vortflow/comments/${entityType}/${entityId}`);
}

export function createVortflowComment(entityType: string, entityId: string, data: { content: string; mentions?: string[]; parent_id?: number | null }) {
    return request.post(`/vortflow/comments/${entityType}/${entityId}`, data);
}

export function updateVortflowComment(commentId: number | string, data: { content: string; mentions?: string[] }) {
    return request.patch(`/vortflow/comments/${commentId}`, data);
}

export function deleteVortflowComment(commentId: number | string) {
    return request.delete(`/vortflow/comments/${commentId}`);
}

export function getVortflowActivity(entityType: string, entityId: string, params?: { page?: number; page_size?: number }) {
    return request.get(`/vortflow/activity/${entityType}/${entityId}`, { params });
}

// ---- Views & Column Settings ----

export function getVortflowViews(work_item_type?: string) {
    return request.get("/vortflow/views", { params: { work_item_type: work_item_type || "" } });
}

export function createVortflowView(data: { name: string; work_item_type: string; scope?: string; filters?: Record<string, any>; columns?: Array<{ key: string; visible: boolean }> }) {
    return request.post("/vortflow/views", data);
}

export function updateVortflowView(id: string, data: { name?: string; filters?: Record<string, any>; columns?: Array<{ key: string; visible: boolean }>; view_order?: number }) {
    return request.put(`/vortflow/views/${id}`, data);
}

export function deleteVortflowView(id: string) {
    return request.delete(`/vortflow/views/${id}`);
}

export function getVortflowColumnSettings(work_item_type?: string) {
    return request.get("/vortflow/column-settings", { params: { work_item_type: work_item_type || "" } });
}

export function saveVortflowColumnSettings(data: { work_item_type: string; columns: Array<{ key: string; visible: boolean }> }) {
    return request.put("/vortflow/column-settings", data);
}

// ---- Tags ----

export function getVortflowTags() {
    return request.get("/vortflow/tags");
}

export function createVortflowTag(data: { name: string; color?: string }) {
    return request.post("/vortflow/tags", data);
}

export function updateVortflowTag(id: string, data: { name?: string; color?: string }) {
    return request.put(`/vortflow/tags/${id}`, data);
}

export function deleteVortflowTag(id: string) {
    return request.delete(`/vortflow/tags/${id}`);
}

export function reorderVortflowTags(ids: string[]) {
    return request.post("/vortflow/tags/reorder", { ids });
}

export function migrateVortflowTag(id: string, data: { target_tag_id?: string | null }) {
    return request.post(`/vortflow/tags/${id}/migrate`, data);
}

// ---- Statuses ----

export function getVortflowStatuses(params?: { keyword?: string; work_item_type?: string }) {
    return request.get("/vortflow/statuses", { params });
}

export function createVortflowStatus(data: { name: string; icon?: string; icon_color?: string; command?: string; work_item_types?: string[] }) {
    return request.post("/vortflow/statuses", data);
}

export function updateVortflowStatus(id: string, data: { name?: string; icon?: string; icon_color?: string; command?: string; work_item_types?: string[] }) {
    return request.put(`/vortflow/statuses/${id}`, data);
}

export function deleteVortflowStatus(id: string) {
    return request.delete(`/vortflow/statuses/${id}`);
}

// ---- Description Templates ----

export function getVortflowDescriptionTemplates() {
    return request.get("/vortflow/description-templates");
}

export function updateVortflowDescriptionTemplate(workItemType: string, data: { content: string }) {
    return request.put(`/vortflow/description-templates/${encodeURIComponent(workItemType)}`, data);
}

// ---- Test Modules ----

export function getVortflowTestModules(params?: { project_id?: string }) {
    return request.get("/vortflow/test-modules", { params });
}

export function createVortflowTestModule(data: { project_id: string; parent_id?: string | null; name: string }) {
    return request.post("/vortflow/test-modules", data);
}

export function updateVortflowTestModule(id: string, data: { name?: string; parent_id?: string | null; sort_order?: number }) {
    return request.put(`/vortflow/test-modules/${id}`, data);
}

export function deleteVortflowTestModule(id: string) {
    return request.delete(`/vortflow/test-modules/${id}`);
}

export function reorderVortflowTestModule(data: { module_id: string; parent_id?: string | null; target_index: number }) {
    return request.post("/vortflow/test-modules/reorder", data);
}

// ---- Test Cases ----

export function getVortflowTestCases(params?: {
    project_id?: string;
    project_ids?: string;
    module_id?: string;
    keyword?: string;
    case_type?: string;
    priority?: number;
    review_result?: string;
    maintainer_id?: string;
    page?: number;
    page_size?: number;
}) {
    return request.get("/vortflow/test-cases", { params });
}

export function getVortflowTestCase(id: string) {
    return request.get(`/vortflow/test-cases/${id}`);
}

export function createVortflowTestCase(data: {
    project_id: string;
    module_id?: string | null;
    title: string;
    precondition?: string;
    notes?: string;
    case_type?: string;
    priority?: number;
    maintainer_id?: string | null;
    steps?: { order: number; description: string; expected_result: string }[];
}) {
    return request.post("/vortflow/test-cases", data);
}

export function updateVortflowTestCase(id: string, data: {
    module_id?: string | null;
    title?: string;
    precondition?: string;
    notes?: string;
    case_type?: string;
    priority?: number;
    maintainer_id?: string | null;
    review_result?: string;
    steps?: { order: number; description: string; expected_result: string }[];
}) {
    return request.put(`/vortflow/test-cases/${id}`, data);
}

export function deleteVortflowTestCase(id: string) {
    return request.delete(`/vortflow/test-cases/${id}`);
}

// ---- Test Case Links ----

export function getVortflowTestCaseLinks(params: {
    test_case_id?: string;
    entity_type?: string;
    entity_id?: string;
}) {
    return request.get("/vortflow/test-case-links", { params });
}

export function createVortflowTestCaseLink(data: {
    test_case_id: string;
    entity_type: string;
    entity_id: string;
}) {
    return request.post("/vortflow/test-case-links", data);
}

export function deleteVortflowTestCaseLink(linkId: string) {
    return request.delete(`/vortflow/test-case-links/${linkId}`);
}

// ---- Test Plans ----

export function getVortflowTestPlans(params: {
    project_id?: string;
    project_ids?: string;
    status?: string;
    keyword?: string;
    page?: number;
    page_size?: number;
}) {
    return request.get("/vortflow/test-plans", { params });
}

export function getVortflowTestPlan(id: string) {
    return request.get(`/vortflow/test-plans/${id}`);
}

export function createVortflowTestPlan(data: {
    project_id: string;
    title: string;
    description?: string;
    status?: string;
    owner_id?: string | null;
    iteration_id?: string | null;
    version_id?: string | null;
    start_date?: string | null;
    end_date?: string | null;
}) {
    return request.post("/vortflow/test-plans", data);
}

export function updateVortflowTestPlan(id: string, data: {
    title?: string;
    description?: string;
    status?: string;
    owner_id?: string | null;
    iteration_id?: string | null;
    version_id?: string | null;
    start_date?: string | null;
    end_date?: string | null;
}) {
    return request.put(`/vortflow/test-plans/${id}`, data);
}

export function deleteVortflowTestPlan(id: string) {
    return request.delete(`/vortflow/test-plans/${id}`);
}

export function copyVortflowTestPlan(id: string) {
    return request.post(`/vortflow/test-plans/${id}/copy`);
}

export function getVortflowTestPlanCases(planId: string, params?: {
    module_id?: string;
    keyword?: string;
    case_type?: string;
    priority?: string;
    latest_result?: string;
    sort_by?: string;
    page?: number;
    page_size?: number;
}) {
    return request.get(`/vortflow/test-plans/${planId}/cases`, { params });
}

export function addVortflowTestPlanCases(planId: string, data: { test_case_ids: string[] }) {
    return request.post(`/vortflow/test-plans/${planId}/cases`, data);
}

export function removeVortflowTestPlanCase(planId: string, planCaseId: string) {
    return request.delete(`/vortflow/test-plans/${planId}/cases/${planCaseId}`);
}

export function addVortflowTestPlanExecution(planId: string, planCaseId: string, data: {
    result: string;
    executor_id?: string | null;
    notes?: string;
    bug_id?: string | null;
}) {
    return request.post(`/vortflow/test-plans/${planId}/cases/${planCaseId}/executions`, data);
}

export function getVortflowTestPlanExecutions(planId: string, planCaseId: string) {
    return request.get(`/vortflow/test-plans/${planId}/cases/${planCaseId}/executions`);
}

// ---- Test Plan Reviews ----

export function getVortflowTestPlanReviews(planId: string) {
    return request.get(`/vortflow/test-plans/${planId}/reviews`);
}

export function addVortflowTestPlanReviews(planId: string, data: {
    reviews: Array<{
        repo_id: string;
        pr_number: number;
        pr_url: string;
        pr_title: string;
        head_branch: string;
        base_branch: string;
    }>;
}) {
    return request.post(`/vortflow/test-plans/${planId}/reviews`, data);
}

export function updateVortflowTestPlanReview(planId: string, reviewId: string, data: {
    reviewer_id?: string | null;
    review_status?: string;
    review_notes?: string;
}) {
    return request.put(`/vortflow/test-plans/${planId}/reviews/${reviewId}`, data);
}

export function removeVortflowTestPlanReview(planId: string, reviewId: string) {
    return request.delete(`/vortflow/test-plans/${planId}/reviews/${reviewId}`);
}

export function getVortflowAvailablePRs(planId: string, repoId: string) {
    return request.get(`/vortflow/test-plans/${planId}/available-prs`, { params: { repo_id: repoId } });
}

export function getVortflowReviewHistory(planId: string, reviewId: string) {
    return request.get(`/vortflow/test-plans/${planId}/reviews/${reviewId}/history`);
}

export function triggerVortflowAiReview(planId: string, reviewId: string) {
    return request.post(`/vortflow/test-plans/${planId}/reviews/${reviewId}/ai-review`, null, { timeout: 120000 });
}

// ---- Test Reports ----

export function getVortflowTestReports(params: { plan_id?: string; project_id?: string; page?: number; page_size?: number }) {
    return request.get("/vortflow/test-reports", { params });
}

export function getVortflowTestReport(reportId: string) {
    return request.get(`/vortflow/test-reports/${reportId}`);
}

export function createVortflowTestReport(data: { plan_id: string; title?: string }) {
    return request.post("/vortflow/test-reports", data);
}

export function updateVortflowTestReport(reportId: string, data: { title?: string; summary?: string }) {
    return request.put(`/vortflow/test-reports/${reportId}`, data);
}

export function deleteVortflowTestReport(reportId: string) {
    return request.delete(`/vortflow/test-reports/${reportId}`);
}

// ---- Work Item Convert ----

export function convertWorkItem(data: { from_type: string; id: string; to_type: string }) {
    return request.post("/vortflow/work-items/convert", data);
}

// ---- File Uploads ----

export function uploadVortflowFile(file: File): Promise<{ url: string; name: string; size: number }> {
    const formData = new FormData();
    formData.append("file", file);
    return request.post("/uploads/vortflow/file", formData, {
        headers: { "Content-Type": "multipart/form-data" },
    });
}

// ---- Notify ----

export function sendVortflowNotify(data: {
    entity_type: string;
    entity_id: string;
    title: string;
    project_id?: string;
    notify_type: "remind" | "urge";
    recipient_ids: string[];
    message?: string;
}) {
    return request.post("/vortflow/notify", data);
}

/**
 * 给"成员关注面板"卡片上的某个成员发送一条工作量提醒/催办。
 * 不绑定具体工作项；后端会把传入的计数（在手 / 逾期 / 即将到期 / 停滞）拼到 IM 文案里。
 */
export function sendVortflowMemberNotify(data: {
    recipient_id: string;
    notify_type: "remind" | "urge";
    message?: string;
    project_id?: string;
    pending_total?: number;
    overdue?: number;
    due_soon?: number;
    stale_count?: number;
}) {
    return request.post("/vortflow/notify/member", data);
}

// ---- Document Links ----

export function getVortflowDocLinks(params: { entity_type: string; entity_id: string }) {
    return request.get("/vortflow/document-links", { params });
}

export function createVortflowDocLink(data: { document_id: string; entity_type: string; entity_id: string }) {
    return request.post("/vortflow/document-links", data);
}

export function createVortflowDocWithLink(data: {
    title: string;
    content?: string;
    entity_type: string;
    entity_id: string;
    project_id: string;
}) {
    return request.post("/vortflow/document-links/with-doc", data);
}

export function uploadVortflowDocWithLink(file: File, entityType: string, entityId: string, projectId: string) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("entity_type", entityType);
    formData.append("entity_id", entityId);
    formData.append("project_id", projectId);
    return request.post("/vortflow/document-links/with-upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60000,
    });
}

export function reorderVortflowDocLinks(data: { link_ids: string[] }) {
    return request.put("/vortflow/document-links/reorder", data);
}

export function deleteVortflowDocLink(linkId: string) {
    return request.delete(`/vortflow/document-links/${linkId}`);
}

// ---- Reminder Settings ----

export function listVortflowReminderSettings() {
    return request.get("/vortflow/reminder-settings");
}

export function getVortflowReminderSettings(projectId: string) {
    return request.get(`/vortflow/reminder-settings/${projectId}`);
}

export function bulkUpdateVortflowReminderSettings(data: {
    project_ids: string[];
    enabled: boolean;
    scenes: Record<string, any>;
    work_days: string;
    near_deadline_days: number;
    ai_suggestion: boolean;
    skip_empty: boolean;
    min_threshold: number;
}) {
    return request.put("/vortflow/reminder-settings/bulk", data);
}

export function updateVortflowReminderSettings(projectId: string, data: any) {
    return request.put(`/vortflow/reminder-settings/${projectId}`, data);
}

export function testVortflowReminder(projectIds: string[], scene: string = "morning") {
    return request.post("/vortflow/reminder-settings/test", {
        project_ids: projectIds,
        scene,
    });
}
