<script setup lang="ts">
import { ref, computed, reactive, onMounted, watch, nextTick } from "vue";
import { message, dialog, Dropdown, DropdownMenuItem, DropdownMenuSeparator } from "@openvort/vort-ui";
import WorkItemMemberPicker from "@/components/vort-biz/work-item/WorkItemMemberPicker.vue";
import WorkItemStatus from "@/components/vort-biz/work-item/WorkItemStatus.vue";
import WorkItemPriority from "@/components/vort-biz/work-item/WorkItemPriority.vue";
import IterationSelect, { type IterationSelectOption } from "@/components/vort-biz/work-item/IterationSelect.vue";
import VortEditor from "@/components/vort-biz/editor/VortEditor.vue";
import MarkdownView from "@/components/vort-biz/editor/MarkdownView.vue";
import { Copy, CopyPlus, SquarePen, FileText, Bot, Loader2, MoreHorizontal, Send, Trash2, Paperclip, Download, X } from "lucide-vue-next";
import StatusIcon from "@/components/vort-biz/work-item/StatusIcon.vue";
import { useWorkItemCommon } from "./useWorkItemCommon";
import { useWorkItemDetailActivityLog } from "./useWorkItemDetailActivityLog";
import { useWorkItemDetailComments } from "./useWorkItemDetailComments";
import { useWorkItemDetailDescription } from "./useWorkItemDetailDescription";
import { useWorkItemDetailAttachments } from "./useWorkItemDetailAttachments";
import { useWorkItemDetailFieldOptions } from "./useWorkItemDetailFieldOptions";
import { resolveBugIterationPlanTime } from "./iterationPlanTime";
import WorkItemLinkPanel from "./WorkItemLinkPanel.vue";
import TestCaseLinkPanel from "./TestCaseLinkPanel.vue";
import DocLinkPanel from "./DocLinkPanel.vue";
import NotifyDialog from "./NotifyDialog.vue";
import { getVortflowDocLinks } from "@/api";
import { useUserStore } from "@/stores";
import { formatFileSize } from "@/utils/format";
import type { WorkItemType, Status, DateRange, RowItem, Priority } from "@/components/vort-biz/work-item/WorkItemTable.types";

interface Props {
    workNo: string;
    initialData?: RowItem;
    parentRecord?: RowItem | null;
    childRecords?: RowItem[];
    initialDescDraft?: string;
    initialDescEditing?: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
    close: [];
    update: [data: Partial<RowItem>];
    delete: [];
    copy: [];
    openRelated: [record: RowItem];
    createChild: [record: RowItem];
    unlinkChild: [child: RowItem];
}>();

const {
    memberOptions,
    ownerGroups,
    getStatusOptionsByType,
    getStatusOption,
    getAvatarBg,
    getAvatarLabel,
    getMemberAvatarUrl,
    loadMemberOptions,
    getMemberIdByName,
    getMemberNameById,
    getWorkItemTypeIconClass,
    getWorkItemTypeIcon,
    getEnrichedOwnerGroups,
    defaultCollapsedGroups,
    recordRecentMember,
} = useWorkItemCommon();

const userStore = useUserStore();
const detailCurrentUser = computed(() => userStore.userInfo.name || "未知用户");
const loading = ref(false);
const record = ref<RowItem | null>(props.initialData || null);
const detailActiveTab = ref("detail");
const detailBottomTab = ref<"comments" | "logs">("comments");
const docLinkCount = ref(0);
const detailStatusDropdownOpen = ref(false);
const detailStatusKeyword = ref("");
const detailAssigneeDropdownOpen = ref(false);
const detailAssigneeKeyword = ref("");
const detailAssigneeGroupOpen = reactive<Record<string, boolean>>({});
const detailEnrichedGroups = ref<{ label: string; members: string[] }[]>([]);
const detailEnrichedCollapsed = ref<string[]>([]);
const detailPriorityOpen = ref(false);
const detailDescEditing = ref(props.initialDescEditing || false);
const detailDescDraft = ref(props.initialDescDraft ?? "");

const notifyDialogOpen = ref(false);

const currentMemberId = computed(() => userStore.userInfo.member_id);

// 把 record.type 转换成后端 entity_type；评论/日志 composable 复用
function getEntityTypeKey(): string {
    const type = record.value?.type;
    if (type === "需求") return "story";
    if (type === "任务") return "task";
    return "bug";
}

const workNoRef = computed(() => props.workNo);

// ---- D1: 评论与活动日志（从原巨型 setup 抽出，统一通过解构保持模板/调用点不变） ----
const activityLog = useWorkItemDetailActivityLog({
    record,
    workNo: workNoRef,
    currentUser: detailCurrentUser,
    getMemberNameById,
});
const {
    detailLogsMap,
    logExpandedMap,
    detailLogs,
    toggleLogExpand,
    formatTimeAgo,
    formatActivityLog,
    appendDetailLog,
} = activityLog;

const comments = useWorkItemDetailComments({
    record,
    workNo: workNoRef,
    currentUser: detailCurrentUser,
    currentMemberId,
    getMemberNameById,
    getEntityType: getEntityTypeKey,
    formatTimeAgo,
});
const {
    detailCommentsMap,
    detailComments,
    detailCommentDraft,
    editingCommentId,
    editingCommentContent,
    editingCommentMentionIds,
    replyingToComment,
    commentMentionIds,
    startEditComment,
    cancelEditComment,
    saveEditComment,
    handleDeleteComment,
    startReplyComment,
    cancelReply,
    copyCommentLink,
    submitDetailComment,
} = comments;

// ---- D2: 描述编辑 + AI 增强 ----
const {
    descAi,
    descAiPhaseLabel,
    aiEnrichBtnLabel,
    openDetailDescEditor,
    saveDetailDescEditor,
    cancelDetailDescEditor,
    startAiEnrichDesc,
    applyAiDesc,
    buildSupplementPrompt,
} = useWorkItemDetailDescription({
    record,
    detailDescEditing,
    detailDescDraft,
    onUpdateDescription: (description) => emit("update", { description }),
    appendDetailLog,
    getEntityType: getEntityTypeKey,
});

// ---- D3a: 附件上传 / 删除 ----
const {
    detailAttachmentInputRef,
    detailAttachmentUploading,
    triggerDetailAttachmentInput,
    handleDetailAttachmentFiles,
    removeDetailAttachment,
} = useWorkItemDetailAttachments({
    record,
    onUpdateAttachments: (attachments) => emit("update", { attachments }),
    appendDetailLog,
});

// ---- D3b: 字段下拉选项加载 ----
const fieldOptions = useWorkItemDetailFieldOptions({ record });
const {
    apiProjects,
    apiIterations,
    apiVersions,
    apiRepos,
    apiBranches,
    branchLoading,
    normalizeDateValue,
    loadBranchOptions,
    mergeIterationOptions,
    loadFieldOptions,
    loadProjectLinkedOptions,
} = fieldOptions;

defineExpose({ detailDescEditing, detailDescDraft, editingCommentId, detailCommentDraft });

const detailCurrentRecord = computed(() => record.value);
const parentRecord = computed(() => props.parentRecord || null);
const childRecords = computed(() => props.childRecords || []);
const isHierarchyRecord = computed(() => record.value?.type === "需求" || record.value?.type === "任务");
const canCreateChild = computed(() => Boolean(record.value?.backendId) && isHierarchyRecord.value);
const linkEntityType = computed<"story" | "task" | "bug">(() => {
    const t = record.value?.type;
    if (t === "需求") return "story";
    if (t === "任务") return "task";
    return "bug";
});
const childItemLabel = computed(() => record.value?.type === "任务" ? "子任务" : "子需求");
const addChildLabel = computed(() => record.value?.type === "任务" ? "添加子任务" : "添加子需求");
const emptyChildText = computed(() => `暂无关联的${childItemLabel.value}`);

const handleCopyDetailLink = async () => {
    const baseUrl = window.location.href.split("#")[0] || window.location.href;
    const title = record.value?.title?.trim() || "";
    const link = title ? `${baseUrl}#${title}` : baseUrl;
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(link);
        } else {
            const input = document.createElement("input");
            input.value = link;
            document.body.appendChild(input);
            input.select();
            document.execCommand("copy");
            document.body.removeChild(input);
        }
        message.success("链接已复制");
    } catch {
        message.error("复制链接失败");
    }
};

const handleDelete = () => {
    dialog.confirm({
        title: "确认删除",
        content: `确定要删除${record.value?.type}「${record.value?.title}」吗？删除后不可恢复。`,
        okType: "danger",
        okText: "删除",
        onOk: () => {
            emit("delete");
        },
    });
};

const filteredDetailStatusOptions = computed(() => {
    const type = record.value?.type || "缺陷";
    const options = getStatusOptionsByType(type);
    const kw = detailStatusKeyword.value.trim().toLowerCase();
    if (!kw) return options;
    return options.filter((opt) => opt.label.toLowerCase().includes(kw));
});

const detailActiveGroups = computed(() =>
    detailEnrichedGroups.value.length > 0 ? detailEnrichedGroups.value : ownerGroups.value,
);

const filteredDetailAssigneeGroups = computed(() => {
    const groups = detailActiveGroups.value;
    const kw = detailAssigneeKeyword.value.trim();
    if (!kw) return groups;
    return groups
        .map((g) => ({
            ...g,
            members: g.members.filter((m) => m.includes(kw))
        }))
        .filter((g) => g.members.length > 0);
});

const ensureDetailPanelsData = async () => {
    const entityId = record.value?.backendId;
    if (!entityId) {
        comments.ensureCommentsForCurrentWorkNo();
        activityLog.ensureLogsForCurrentWorkNo();
        return;
    }
    const entityType = getEntityTypeKey();
    await Promise.allSettled([
        comments.loadComments(entityType, entityId),
        activityLog.loadActivityLogs(entityType, entityId),
    ]);
};

const toggleDetailStatusMenu = () => {
    detailStatusDropdownOpen.value = !detailStatusDropdownOpen.value;
    if (!detailStatusDropdownOpen.value) detailStatusKeyword.value = "";
};

const toggleDetailAssigneeMenu = () => {
    detailAssigneeDropdownOpen.value = !detailAssigneeDropdownOpen.value;
    if (!detailAssigneeDropdownOpen.value) detailAssigneeKeyword.value = "";
};

const toggleDetailAssigneeGroup = (group: string) => {
    detailAssigneeGroupOpen[group] = !detailAssigneeGroupOpen[group];
};

const selectDetailStatus = async (value: Status) => {
    if (!record.value) return;
    const prevStatus = record.value.status;
    record.value.status = value;
    detailStatusDropdownOpen.value = false;
    detailStatusKeyword.value = "";
    appendDetailLog("updated", { state: { from: prevStatus, to: value } });
    emit("update", { status: value });
};

const PRIORITY_DETAIL_DEFAULT_SCORES: Record<Priority, number> = {
    urgent: 80, high: 60, medium: 40, low: 20, none: 0,
};

const selectDetailPriority = (value: Priority) => {
    if (!record.value) return;
    const oldPriority = record.value.priority;
    record.value.priority = value;
    (record.value as any).priorityScore = PRIORITY_DETAIL_DEFAULT_SCORES[value];
    detailPriorityOpen.value = false;
    appendDetailLog("updated", { priority: { from: oldPriority, to: value } });
    emit("update", {
        priority: value,
        priorityScore: PRIORITY_DETAIL_DEFAULT_SCORES[value],
    });
};

const selectDetailPriorityScore = (score: number) => {
    if (!record.value) return;
    const normalized = Math.max(0, Math.min(100, Math.round(score)));
    const level: Priority = normalized >= 80 ? "urgent"
        : normalized >= 60 ? "high"
        : normalized >= 40 ? "medium"
        : normalized >= 20 ? "low"
        : "none";
    const oldLevel = record.value.priority;
    const oldScore = (record.value as any).priorityScore;
    record.value.priority = level;
    (record.value as any).priorityScore = normalized;
    if (oldLevel !== level) {
        appendDetailLog("updated", { priority: { from: oldLevel, to: level } });
    } else if (oldScore !== normalized) {
        appendDetailLog("updated", { priority_score: { from: oldScore, to: normalized } });
    }
    emit("update", { priority: level, priorityScore: normalized });
};

const isDetailOwner = (member: string): boolean => {
    return record.value?.owner === member;
};

const isDetailCollaborator = (member: string): boolean => {
    return (record.value?.collaborators || []).includes(member);
};

const setDetailOwner = async (member: string) => {
    if (!record.value) return;
    const prev = record.value.owner;
    const nextOwner = member || "未指派";
    record.value.owner = nextOwner;
    detailAssigneeDropdownOpen.value = false;
    detailAssigneeKeyword.value = "";
    appendDetailLog("updated", { assignee_id: { from: prev, to: nextOwner } });
    emit("update", { owner: nextOwner });
};

const toggleDetailCollaborator = async (member: string) => {
    if (!record.value) return;
    const oldCollaborators = [...record.value.collaborators];
    const collaborators = [...oldCollaborators];
    const idx = collaborators.indexOf(member);
    if (idx >= 0) {
        collaborators.splice(idx, 1);
    } else {
        collaborators.push(member);
    }
    record.value.collaborators = collaborators;
    emit("update", { collaborators });
    appendDetailLog("updated", { collaborators: { from: oldCollaborators, to: collaborators } });
};

const setDetailCollaborators = async (nextCollaborators: string[]) => {
    if (!record.value) return;
    const prev = [...record.value.collaborators];
    record.value.collaborators = [...nextCollaborators];
    try {
        emit("update", { collaborators: [...nextCollaborators] });
    } catch {
        record.value.collaborators = prev;
    }
};

const detailPlanTimeModel = computed<any>({
    get: () => {
        if (!record.value) return undefined;
        const pt = record.value.planTime;
        return pt && pt.length === 2 && pt[0] ? [pt[0], pt[1]] as DateRange : undefined;
    },
    set: (value) => {
        if (!record.value) return;
        const oldStart = record.value.planTime?.[0] || "";
        const oldEnd = record.value.planTime?.[1] || "";
        let newStart = "";
        let newEnd = "";
        if (Array.isArray(value) && value.length === 2) {
            newStart = normalizeDateValue(value[0]);
            newEnd = normalizeDateValue(value[1]);
        }
        record.value.planTime = [newStart, newEnd] as DateRange;
        emit("update", { planTime: record.value.planTime });
        const detail: Record<string, any> = {};
        if (oldStart !== newStart) detail.plan_start = { from: oldStart, to: newStart };
        if (oldEnd !== newEnd) detail.deadline = { from: oldEnd, to: newEnd };
        if (Object.keys(detail).length) appendDetailLog("updated", detail);
    },
});

const detailProjectName = computed({
    get: () => record.value?.projectName || "",
    set: (val: string) => {
        if (!record.value) return;
        const oldVal = record.value.projectName || "";
        const match = apiProjects.value.find(p => p.name === val);
        record.value.projectName = val;
        if (match) record.value.projectId = match.id;
        emit("update", { projectName: val, projectId: match?.id });
        appendDetailLog("updated", { project_name: { from: oldVal, to: val } });
        loadProjectLinkedOptions(match?.id || "");
    },
});

const detailIteration = computed({
    get: () => record.value?.iterationId || "",
    set: (val: string) => {
        if (!record.value) return;
        const oldName = record.value.iteration || "";
        const oldPlanStart = record.value.planTime?.[0] || "";
        const oldPlanEnd = record.value.planTime?.[1] || "";
        const nextId = String(val || "");
        const name = apiIterations.value.find(i => i.id === nextId)?.name
            || (nextId === record.value.iterationId ? record.value.iteration || "" : "");
        record.value.iterationId = nextId;
        record.value.iteration = name;
        // 迭代日期联动只对缺陷生效。复制缺陷后切换项目/迭代时，
        // 旧计划时间不能继续沿用，应改为新迭代的起止日期；需求和任务
        // 仍保持手动维护计划时间的原有行为。
        const iterationPlanTime = resolveBugIterationPlanTime(
            record.value.type,
            nextId,
            apiIterations.value,
        );
        const update: Partial<RowItem> = { iterationId: nextId, iteration: name };
        if (iterationPlanTime) {
            record.value.planTime = [...iterationPlanTime] as DateRange;
            record.value.planStartDate = iterationPlanTime[0];
            record.value.planEndDate = iterationPlanTime[1];
            update.planTime = [...iterationPlanTime] as DateRange;
        }
        emit("update", update);
        const iterationChange: Record<string, any> = {
            iteration: { from: oldName, to: name },
        };
        if (iterationPlanTime && (oldPlanStart !== iterationPlanTime[0] || oldPlanEnd !== iterationPlanTime[1])) {
            Object.assign(iterationChange, {
                plan_start: { from: oldPlanStart, to: iterationPlanTime[0] },
                deadline: { from: oldPlanEnd, to: iterationPlanTime[1] },
            });
        }
        appendDetailLog("updated", iterationChange);
    },
});

const handleDetailIterationOptionsChange = (options: IterationSelectOption[]) => {
    mergeIterationOptions(options);
};

const detailVersion = computed({
    get: () => record.value?.versionId || "",
    set: (val: string) => {
        if (!record.value) return;
        const oldName = record.value.version || "";
        const nextId = String(val || "");
        const name = apiVersions.value.find(v => v.id === nextId)?.name || "";
        record.value.versionId = nextId;
        record.value.version = name;
        emit("update", { versionId: nextId, version: name });
        appendDetailLog("updated", { version: { from: oldName, to: name } });
    },
});

const detailEstimateHours = computed<number | undefined>({
    get: () => {
        if (!record.value?.estimateHours && record.value?.estimateHours !== 0) return undefined;
        return Number(record.value.estimateHours);
    },
    set: (value) => {
        if (!record.value) return;
        const oldVal = record.value.estimateHours == null ? null : Number(record.value.estimateHours);
        const next = value == null ? undefined : Number(value);
        record.value.estimateHours = next;
        if (record.value.loggedHours != null && next != null) {
            record.value.remainHours = Math.max(0, next - Number(record.value.loggedHours || 0));
        } else if (next == null) {
            record.value.remainHours = undefined;
        }
        emit("update", { estimateHours: next });
        appendDetailLog("updated", { estimate_hours: { from: oldVal, to: next ?? null } });
    },
});

const detailRepoId = computed({
    get: () => record.value?.repoId || "",
    set: (val: string) => {
        if (!record.value) return;
        const oldRepoName = record.value.repo || "";
        const oldBranch = record.value.branch || "";
        const nextId = String(val || "");
        const nextRepo = apiRepos.value.find((item) => item.id === nextId)?.name || "";
        const repoChanged = nextId !== (record.value.repoId || "");
        record.value.repoId = nextId;
        record.value.repo = nextRepo;
        if (repoChanged) {
            record.value.branch = "";
        }
        emit("update", {
            repoId: nextId,
            repo: nextRepo,
            branch: repoChanged ? "" : record.value.branch || "",
        });
        const detail: Record<string, any> = { repo_name: { from: oldRepoName, to: nextRepo } };
        if (repoChanged && oldBranch) detail.branch = { from: oldBranch, to: "" };
        appendDetailLog("updated", detail);
        loadBranchOptions(nextId);
    },
});

const detailBranch = computed({
    get: () => record.value?.branch || "",
    set: (val: string) => {
        if (!record.value) return;
        const oldBranch = record.value.branch || "";
        const nextBranch = String(val || "");
        record.value.branch = nextBranch;
        emit("update", { branch: nextBranch });
        appendDetailLog("updated", { branch: { from: oldBranch, to: nextBranch } });
    },
});

const detailActualTimeModel = computed<any>({
    get: () => {
        if (!record.value) return undefined;
        const s = record.value.startAt || "";
        const e = record.value.endAt || "";
        return s || e ? [s, e] as DateRange : undefined;
    },
    set: (value) => {
        if (!record.value) return;
        const oldStart = record.value.startAt || "";
        const oldEnd = record.value.endAt || "";
        let startAt = "";
        let endAt = "";
        if (Array.isArray(value) && value.length === 2) {
            startAt = normalizeDateValue(String(value[0] || ""));
            endAt = normalizeDateValue(String(value[1] || ""));
        }
        record.value.startAt = startAt;
        record.value.endAt = endAt;
        emit("update", { startAt, endAt });
        const detail: Record<string, any> = {};
        if (oldStart !== startAt) detail.start_at = { from: oldStart, to: startAt };
        if (oldEnd !== endAt) detail.end_at = { from: oldEnd, to: endAt };
        if (Object.keys(detail).length) appendDetailLog("updated", detail);
    },
});

const detailTestTime = computed({
    get: () => record.value?.testTime || undefined,
    set: (val: string | undefined) => {
        if (!record.value) return;
        const oldVal = record.value.testTime || "";
        const v = val ? normalizeDateValue(val) : "";
        record.value.testTime = v;
        emit("update", { testTime: v });
        appendDetailLog("updated", { test_time: { from: oldVal, to: v } });
    },
});

const detailDraftTime = computed({
    get: () => record.value?.draftTime || undefined,
    set: (val: string | undefined) => {
        if (!record.value) return;
        const oldVal = record.value.draftTime || "";
        const v = val ? normalizeDateValue(val) : "";
        record.value.draftTime = v;
        emit("update", { draftTime: v });
        appendDetailLog("updated", { draft_time: { from: oldVal, to: v } });
    },
});

const detailReleaseTime = computed({
    get: () => record.value?.releaseTime || undefined,
    set: (val: string | undefined) => {
        if (!record.value) return;
        const oldVal = record.value.releaseTime || "";
        const v = val ? normalizeDateValue(val) : "";
        record.value.releaseTime = v;
        emit("update", { releaseTime: v });
        appendDetailLog("updated", { release_time: { from: oldVal, to: v } });
    },
});

const detailType = computed({
    get: () => record.value?.type || "缺陷",
    set: (val: string) => {
        if (!record.value || val === record.value.type) return;
        const oldType = record.value.type;
        // Do NOT mutate record.type before emit — the parent needs
        // the original type to detect the change and call convert API.
        emit("update", { type: val as WorkItemType });
        appendDetailLog("updated", { task_type: { from: oldType, to: val } });
    },
});

// ---- Inline edit: click-to-edit pattern ----
type EditableField =
    | "title"
    | "planTime"
    | "testTime"
    | "draftTime"
    | "releaseTime"
    | "iteration"
    | "type"
    | "project"
    | "version"
    | "progress"
    | "estimateHours"
    | "repo"
    | "branch"
    | "actualTime";
const editingField = ref<EditableField | null>(null);
const startEditing = (field: EditableField) => {
    editingField.value = field;
};
const stopEditing = () => {
    editingField.value = null;
};
const isEditing = (field: EditableField) => editingField.value === field;

const titleDraft = ref("");
const titleInputRef = ref<HTMLInputElement | null>(null);
const startEditingTitle = () => {
    if (!record.value) return;
    titleDraft.value = record.value.title;
    startEditing("title");
    nextTick(() => titleInputRef.value?.focus());
};
const saveTitle = () => {
    if (!record.value) return;
    const trimmed = titleDraft.value.trim();
    if (trimmed && trimmed !== record.value.title) {
        const oldTitle = record.value.title;
        record.value.title = trimmed;
        emit("update", { title: trimmed });
        appendDetailLog("updated", { title: { from: oldTitle, to: trimmed } });
    }
    titleDraft.value = "";
    stopEditing();
};
const cancelTitleEdit = () => {
    titleDraft.value = "";
    stopEditing();
};
const handleTitleKeydown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
        e.preventDefault();
        saveTitle();
    } else if (e.key === "Escape") {
        cancelTitleEdit();
    }
};

const canEditProject = computed(() => !!record.value);
const canEditIteration = computed(() => !!record.value);
const canEditVersion = computed(() => !!record.value);
const canEditEstimateHours = computed(() => !!record.value);

const isProgressReadonly = computed(() => {
    if (!record.value) return true;
    if (record.value.type === "需求") return false;
    if ((record.value.childrenCount || 0) > 0) return true;
    return false;
});

const detailProgress = computed({
    get: () => record.value?.progress ?? 0,
    set: (val: number) => {
        if (!record.value || isProgressReadonly.value) return;
        const oldVal = record.value.progress ?? 0;
        const clamped = Math.max(0, Math.min(100, Math.round(val)));
        record.value.progress = clamped;
        emit("update", { progress: clamped });
        appendDetailLog("updated", { progress: { from: oldVal, to: clamped } });
    },
});

const detailProgressRef = ref<any>(null);
const startEditingProgress = () => {
    if (isProgressReadonly.value) return;
    startEditing("progress");
    nextTick(() => detailProgressRef.value?.focus());
};

const detailEstimateRef = ref<any>(null);
const startEditingEstimate = () => {
    if (!canEditEstimateHours.value) return;
    startEditing("estimateHours");
    nextTick(() => detailEstimateRef.value?.focus());
};

onMounted(async () => {
    await loadMemberOptions();
    const pid = record.value?.projectId || "";
    if (pid) {
        getEnrichedOwnerGroups(pid).then((groups) => {
            detailEnrichedGroups.value = groups;
            detailEnrichedCollapsed.value = defaultCollapsedGroups(groups);
        });
    }
    await loadFieldOptions();
    detailAssigneeGroupOpen["全部成员"] = true;
    await ensureDetailPanelsData();
});

async function loadDocLinkCount() {
    if (!record.value?.backendId) { docLinkCount.value = 0; return; }
    try {
        const res = await getVortflowDocLinks({
            entity_type: linkEntityType.value,
            entity_id: record.value.backendId,
        }) as any;
        docLinkCount.value = res?.items?.length || 0;
    } catch { docLinkCount.value = 0; }
}

watch(() => props.initialData, (value) => {
    record.value = value || null;
    if (value) {
        loadFieldOptions();
        loadDocLinkCount();
    }
}, { immediate: true });
</script>

<template>
    <div class="bug-detail-drawer">
        <main class="bug-detail-main" v-if="record">
            <div class="bug-detail-meta-top">
                <div class="bug-detail-meta-left">
                    <span class="work-type-icon" :class="getWorkItemTypeIconClass(record.type)">
                        <component :is="getWorkItemTypeIcon(record.type)" :size="18" />
                    </span>
                    <span class="bug-detail-no">{{ record.workNo }}</span>
                    <button type="button" class="detail-copy-link-btn" @click="handleCopyDetailLink">
                        <Copy :size="14" />
                        复制链接
                    </button>
                    <button type="button" class="detail-copy-link-btn" @click="notifyDialogOpen = true">
                        <Send :size="14" />
                        发送通知
                    </button>
                    <WorkItemStatus
                        :model-value="record.status"
                        :options="filteredDetailStatusOptions"
                        :open="detailStatusDropdownOpen"
                        v-model:keyword="detailStatusKeyword"
                        @update:open="(open) => { detailStatusDropdownOpen = open; if (!open) detailStatusKeyword = ''; }"
                        @change="selectDetailStatus"
                    >
                        <template #trigger>
                            <VortButton class="detail-status-trigger" variant="text" @click.stop="toggleDetailStatusMenu">
                                <span class="detail-status-content">
                                    <span class="detail-status-icon" :class="getStatusOption(record.status, record.type).iconClass">
                                        <StatusIcon :name="getStatusOption(record.status, record.type).icon" :size="14" />
                                    </span>
                                    <span class="detail-status-text">{{ record.status }}</span>
                                </span>
                                <span class="status-arrow-simple" :class="{ open: detailStatusDropdownOpen }" />
                            </VortButton>
                        </template>
                    </WorkItemStatus>
                </div>
                <div class="bug-detail-meta-right">
                    <AiAssistButton
                        :prompt="`我要对${record.type}「${record.title}」(${record.workNo}) 进一步操作，请告诉我可以做什么。\n实体类型：${getEntityTypeKey()}，实体 ID：${record.backendId}`"
                        label="AI 助手"
                    />
                    <Dropdown trigger="click" placement="bottomRight">
                        <button type="button" class="detail-more-btn">
                            <MoreHorizontal :size="16" />
                        </button>
                        <template #overlay>
                            <DropdownMenuItem @click="emit('copy')">
                                <CopyPlus :size="14" class="mr-2 text-gray-400" />
                                <span>复制</span>
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem @click="handleDelete">
                                <Trash2 :size="14" class="mr-2 text-red-400" />
                                <span class="text-red-500">删除</span>
                            </DropdownMenuItem>
                        </template>
                    </Dropdown>
                </div>
            </div>

            <div v-if="isHierarchyRecord && parentRecord" class="story-tree-header">
                <div class="story-parent-node" @click="emit('openRelated', parentRecord)">
                    <span class="work-type-icon-small" :class="getWorkItemTypeIconClass(parentRecord.type)">
                        <component :is="getWorkItemTypeIcon(parentRecord.type)" :size="12" />
                    </span>
                    <span class="parent-title">{{ parentRecord.title }}</span>
                </div>
                <div class="story-child-node">
                    <div class="tree-line"></div>
                    <input
                        v-if="isEditing('title')"
                        ref="titleInputRef"
                        v-model="titleDraft"
                        class="bug-detail-title-input"
                        style="margin-bottom: 0;"
                        @blur="saveTitle"
                        @keydown="handleTitleKeydown"
                    />
                    <h2 v-else class="bug-detail-title bug-detail-title-editable" style="margin-bottom: 0;" @click="startEditingTitle">{{ record.title }}</h2>
                </div>
            </div>
            <template v-else>
                <input
                    v-if="isEditing('title')"
                    ref="titleInputRef"
                    v-model="titleDraft"
                    class="bug-detail-title-input"
                    @blur="saveTitle"
                    @keydown="handleTitleKeydown"
                />
                <h2 v-else class="bug-detail-title bug-detail-title-editable" @click="startEditingTitle">{{ record.title }}</h2>
            </template>
            <p class="bug-detail-sub" :style="isHierarchyRecord && parentRecord ? 'margin-top: 8px;' : ''">
                {{ record.creator || "未知" }} 创建于 {{ record.createdAt }}，指派给 {{ record.owner || "未指派" }}，最近更新于 {{ record.updatedAt || record.createdAt }}
            </p>
            <div class="bug-detail-tabs">
                <button :class="{ active: detailActiveTab === 'detail' }" @click="detailActiveTab = 'detail'">详情</button>
                <button :class="{ active: detailActiveTab === 'docs' }" @click="detailActiveTab = 'docs'">关联文档<span v-if="docLinkCount > 0" class="tab-count">{{ docLinkCount }}</span></button>
                <button :class="{ active: detailActiveTab === 'worklog' }" @click="detailActiveTab = 'worklog'">工作日志</button>
                <button :class="{ active: detailActiveTab === 'related' }" @click="detailActiveTab = 'related'">关联工作项</button>
                <button :class="{ active: detailActiveTab === 'test' }" @click="detailActiveTab = 'test'">关联测试用例</button>
            </div>

            <div class="bug-detail-panel" v-if="detailActiveTab === 'detail'">
                <div class="bug-detail-ai-bar">
                    <AiAssistButton
                        :prompt="buildSupplementPrompt()"
                        label="AI 一键补充"
                    />
                </div>
                <div class="bug-detail-top-grid">
                    <div class="bug-detail-left-col">
                        <div class="bug-detail-info-item bug-detail-info-item-row bug-detail-info-assignee" @click.stop>
                            <label>负责人 / 协作</label>
                            <WorkItemMemberPicker
                                mode="assignee"
                                :owner="record.owner === '未指派' ? '' : record.owner"
                                :collaborators="record.collaborators"
                                :groups="filteredDetailAssigneeGroups"
                                :open="detailAssigneeDropdownOpen"
                                v-model:keyword="detailAssigneeKeyword"
                                :dropdown-width="280"
                                :dropdown-max-height="320"
                                :bordered="false"
                                :collapsible="true"
                                :default-collapsed="detailEnrichedCollapsed"
                                :get-avatar-bg="getAvatarBg"
                                :get-avatar-label="getAvatarLabel"
                                :get-avatar-url="getMemberAvatarUrl"
                                @update:open="(open) => { detailAssigneeDropdownOpen = open; if (!open) detailAssigneeKeyword = ''; }"
                                @update:owner="(v) => { setDetailOwner(v); if (v) recordRecentMember(v); }"
                                @update:collaborators="(v) => { setDetailCollaborators(v); v.forEach(recordRecentMember); }"
                            >
                                <template #trigger>
                                    <VortButton
                                        class="detail-assignee-trigger"
                                        variant="text"
                                        :class="detailAssigneeDropdownOpen ? 'active' : ''"
                                        @click.stop="toggleDetailAssigneeMenu"
                                    >
                                        <div class="detail-assignee-split">
                                            <div class="detail-assignee-owner">
                                                <span
                                                    v-if="record.owner && record.owner !== '未指派'"
                                                    class="detail-assignee-avatar overflow-hidden"
                                                    :style="{ backgroundColor: getAvatarBg(record.owner) }"
                                                >
                                                    <img v-if="getMemberAvatarUrl(record.owner)" :src="getMemberAvatarUrl(record.owner)" class="w-full h-full object-cover" />
                                                    <template v-else>{{ getAvatarLabel(record.owner) }}</template>
                                                </span>
                                                <span class="detail-assignee-owner-name">
                                                    {{ record.owner || "未指派" }}
                                                </span>
                                            </div>
                                            <span class="detail-assignee-separator">/</span>
                                            <div class="detail-assignee-collaborators detail-collab-stack">
                                                <template v-if="record.collaborators.length > 0">
                                                    <span
                                                        v-for="name in record.collaborators"
                                                        :key="'detail-collab-' + name"
                                                        class="detail-assignee-avatar overflow-hidden"
                                                        :style="{ backgroundColor: getAvatarBg(name) }"
                                                        :title="name"
                                                    >
                                                        <img v-if="getMemberAvatarUrl(name)" :src="getMemberAvatarUrl(name)" class="w-full h-full object-cover" />
                                                        <template v-else>{{ getAvatarLabel(name) }}</template>
                                                    </span>
                                                </template>
                                                <span v-else class="detail-assignee-avatar detail-assignee-add">+</span>
                                            </div>
                                        </div>
                                    </VortButton>
                                </template>
                            </WorkItemMemberPicker>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>计划时间</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('planTime') }"
                                @mousedown.capture="startEditing('planTime')"
                            >
                                <vort-range-picker
                                    v-model="detailPlanTimeModel"
                                    format="YYYY-MM-DD"
                                    separator="~"
                                    allow-clear
                                    :placeholder="['未设置', '未设置']"
                                    class="detail-field-picker"
                                    @change="stopEditing"
                                    @open-change="(v: boolean) => { if (!v) stopEditing() }"
                                />
                            </div>
                        </div>
                        <div v-if="record?.type === '需求'" class="bug-detail-info-item bug-detail-info-item-row">
                            <label>提测时间</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('testTime') }"
                                @mousedown.capture="startEditing('testTime')"
                            >
                                <vort-date-picker
                                    v-model="detailTestTime"
                                    value-format="YYYY-MM-DD"
                                    format="YYYY-MM-DD"
                                    allow-clear
                                    placeholder="未设置"
                                    class="detail-field-picker"
                                    @change="stopEditing"
                                    @open-change="(v: boolean) => { if (!v) stopEditing() }"
                                />
                            </div>
                        </div>
                        <div v-if="record?.type === '需求'" class="bug-detail-info-item bug-detail-info-item-row">
                            <label>出稿时间</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('draftTime') }"
                                @mousedown.capture="startEditing('draftTime')"
                            >
                                <vort-date-picker
                                    v-model="detailDraftTime"
                                    value-format="YYYY-MM-DD"
                                    format="YYYY-MM-DD"
                                    allow-clear
                                    placeholder="未设置"
                                    class="detail-field-picker"
                                    @change="stopEditing"
                                    @open-change="(v: boolean) => { if (!v) stopEditing() }"
                                />
                            </div>
                        </div>
                        <div v-if="record?.type === '需求'" class="bug-detail-info-item bug-detail-info-item-row">
                            <label>发布时间</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('releaseTime') }"
                                @mousedown.capture="startEditing('releaseTime')"
                            >
                                <vort-date-picker
                                    v-model="detailReleaseTime"
                                    value-format="YYYY-MM-DD"
                                    format="YYYY-MM-DD"
                                    allow-clear
                                    placeholder="未设置"
                                    class="detail-field-picker"
                                    @change="stopEditing"
                                    @open-change="(v: boolean) => { if (!v) stopEditing() }"
                                />
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>迭代</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('iteration') }"
                                @mousedown.capture="canEditIteration && startEditing('iteration')"
                            >
                                <IterationSelect
                                    v-model="detailIteration"
                                    :project-id="record.projectId || ''"
                                    :selected-label="record.iteration || record.iterationId || ''"
                                    placeholder="未设置"
                                    allow-clear
                                    :disabled="!canEditIteration"
                                    :bordered="isEditing('iteration')"
                                    class="detail-field-select"
                                    @options-change="handleDetailIterationOptionsChange"
                                    @change="stopEditing"
                                    @blur="stopEditing"
                                />
                            </div>
                        </div>
                        <div v-if="record?.type === '需求' || record?.type === '任务'" class="bug-detail-info-item bug-detail-info-item-row">
                            <label>进度</label>
                            <div
                                class="detail-progress-shell"
                                @click.stop="!isProgressReadonly && startEditingProgress()"
                            >
                                <div class="detail-progress-bar">
                                    <div class="detail-progress-fill" :style="{ width: (detailProgress || 0) + '%' }" />
                                </div>
                                <template v-if="!isProgressReadonly && isEditing('progress')">
                                    <vort-input-number
                                        ref="detailProgressRef"
                                        v-model="detailProgress"
                                        :min="0"
                                        :max="100"
                                        :step="5"
                                        size="small"
                                        style="width:64px"
                                        @click.stop
                                        @blur="stopEditing"
                                        @keyup.enter="stopEditing"
                                    />
                                </template>
                                <span v-else class="detail-progress-text" :class="{ 'cursor-pointer': !isProgressReadonly }">{{ detailProgress || 0 }}%</span>
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>预估工时</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('estimateHours') }"
                                @mousedown.capture="startEditingEstimate"
                            >
                                <vort-input-number
                                    ref="detailEstimateRef"
                                    v-model="detailEstimateHours"
                                    placeholder="未设置"
                                    :disabled="!canEditEstimateHours"
                                    :min="0"
                                    :step="0.5"
                                    :bordered="isEditing('estimateHours')"
                                    class="detail-field-number"
                                    @blur="stopEditing"
                                />
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>实际时间</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('actualTime') }"
                                @mousedown.capture="startEditing('actualTime')"
                            >
                                <vort-range-picker
                                    v-model="detailActualTimeModel"
                                    format="YYYY-MM-DD"
                                    separator="~"
                                    :placeholder="['未设置', '未设置']"
                                    class="detail-field-picker"
                                    @change="stopEditing"
                                    @open-change="(v: boolean) => { if (!v) stopEditing() }"
                                />
                            </div>
                        </div>
                    </div>
                    <div class="bug-detail-right-col">
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>类型</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('type') }"
                                @mousedown.capture="startEditing('type')"
                            >
                                <vort-select
                                    v-model="detailType"
                                    :bordered="isEditing('type')"
                                    class="detail-field-select"
                                    @change="stopEditing"
                                    @blur="stopEditing"
                                >
                                    <vort-select-option value="需求">需求</vort-select-option>
                                    <vort-select-option value="任务">任务</vort-select-option>
                                    <vort-select-option value="缺陷">缺陷</vort-select-option>
                                </vort-select>
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row" @click.stop>
                            <label>优先级</label>
                            <WorkItemPriority
                                v-model:open="detailPriorityOpen"
                                :model-value="record.priority || 'none'"
                                :score="(record as any).priorityScore"
                                :enable-score-slider="true"
                                @change="selectDetailPriority"
                                @change-score="selectDetailPriorityScore"
                            />
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>项目</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('project') }"
                                @mousedown.capture="canEditProject && startEditing('project')"
                            >
                                <vort-select
                                    v-model="detailProjectName"
                                    :disabled="!canEditProject"
                                    :bordered="isEditing('project')"
                                    class="detail-field-select"
                                    @change="stopEditing"
                                    @blur="stopEditing"
                                >
                                    <vort-select-option v-for="item in apiProjects" :key="item.id" :value="item.name">{{ item.name }}</vort-select-option>
                                </vort-select>
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>版本</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('version') }"
                                @mousedown.capture="canEditVersion && startEditing('version')"
                            >
                                <vort-select
                                    v-model="detailVersion"
                                    placeholder="未设置"
                                    allow-clear
                                    :disabled="!canEditVersion"
                                    :bordered="isEditing('version')"
                                    class="detail-field-select"
                                    @change="stopEditing"
                                    @blur="stopEditing"
                                >
                                    <vort-select-option v-for="item in apiVersions" :key="item.id" :value="item.id">{{ item.name }}</vort-select-option>
                                </vort-select>
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>关联仓库</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('repo') }"
                                @mousedown.capture="startEditing('repo')"
                            >
                                <vort-select
                                    v-model="detailRepoId"
                                    placeholder="未设置"
                                    allow-clear
                                    :bordered="isEditing('repo')"
                                    class="detail-field-select"
                                    @change="stopEditing"
                                    @blur="stopEditing"
                                >
                                    <vort-select-option v-for="item in apiRepos" :key="item.id" :value="item.id">{{ item.name }}</vort-select-option>
                                </vort-select>
                            </div>
                        </div>
                        <div class="bug-detail-info-item bug-detail-info-item-row">
                            <label>关联分支</label>
                            <div
                                class="detail-field-shell"
                                :class="{ 'is-editing': isEditing('branch') }"
                                @mousedown.capture="record.repoId && startEditing('branch')"
                            >
                                <vort-select
                                    v-model="detailBranch"
                                    :placeholder="record.repoId ? (branchLoading ? '分支加载中' : '未设置') : '请先选择仓库'"
                                    allow-clear
                                    :disabled="!record.repoId"
                                    :bordered="isEditing('branch')"
                                    class="detail-field-select"
                                    @change="stopEditing"
                                    @blur="stopEditing"
                                >
                                    <vort-select-option v-for="item in apiBranches" :key="item.name" :value="item.name">{{ item.name }}</vort-select-option>
                                </vort-select>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bug-detail-sub-items" v-if="isHierarchyRecord">
                    <div class="bug-detail-sub-items-head">
                        <div class="flex items-center gap-2">
                            <h4>{{ childItemLabel }}</h4>
                            <span class="count">{{ childRecords.length }}</span>
                            <VortButton
                                class="add-sub-item-btn"
                                variant="text"
                                size="small"
                                :disabled="!canCreateChild"
                                @click="record && emit('createChild', record)"
                            >
                                <span class="icon">+</span> {{ addChildLabel }}
                            </VortButton>
                        </div>
                    </div>
                    
                    <div v-if="childRecords.length > 0" class="bug-detail-sub-items-content">
                        <div class="bug-detail-sub-items-list">
                            <div 
                                v-for="child in childRecords" 
                                :key="child.backendId || child.workNo"
                                class="bug-detail-sub-item group"
                                @click="emit('openRelated', child)"
                            >
                                <div class="sub-item-left">
                                    <span class="work-type-icon-small" :class="getWorkItemTypeIconClass(child.type)">
                                        <component :is="getWorkItemTypeIcon(child.type)" :size="12" />
                                    </span>
                                    <span class="sub-item-no">{{ child.workNo }}</span>
                                    <span class="sub-item-title group-hover:text-blue-600">{{ child.title }}</span>
                                </div>
                                <div class="sub-item-right">
                                    <div class="sub-item-owner">
                                        <span class="detail-assignee-avatar overflow-hidden" :style="{ backgroundColor: getAvatarBg(child.owner || '未指派'), width: '20px', height: '20px', fontSize: '10px' }">
                                            <img v-if="getMemberAvatarUrl(child.owner || '')" :src="getMemberAvatarUrl(child.owner || '')" class="w-full h-full object-cover" />
                                            <template v-else>{{ getAvatarLabel(child.owner || '未指派') }}</template>
                                        </span>
                                        <span class="owner-name">{{ child.owner || '未指派' }}</span>
                                    </div>
                                    <div class="sub-item-status">
                                        <span class="status-icon" :class="getStatusOption(child.status, child.type).iconClass"><StatusIcon :name="getStatusOption(child.status, child.type).icon" :size="12" /></span>
                                        <span class="status-text">{{ child.status }}</span>
                                    </div>
                                    <div @click.stop>
                                        <Dropdown trigger="click" placement="bottomRight">
                                            <button class="sub-item-more">
                                                <MoreHorizontal :size="14" />
                                            </button>
                                            <template #overlay>
                                                <DropdownMenuItem class="text-red-500" @click="emit('unlinkChild', child)">取消关联</DropdownMenuItem>
                                            </template>
                                        </Dropdown>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bug-detail-desc">
                    <div class="bug-detail-desc-head">
                        <h4>描述</h4>
                        <VortButton v-if="!detailDescEditing" class="bug-detail-desc-edit-btn" variant="text" size="small" @click="openDetailDescEditor">
                            <SquarePen :size="14" />
                        </VortButton>
                    </div>
                    <template v-if="detailDescEditing">
                        <VortEditor v-model="detailDescDraft" placeholder="请输入描述内容..." min-height="300px" />
                        <div class="bug-detail-desc-actions">
                            <vort-button variant="primary" @click="saveDetailDescEditor">保存</vort-button>
                            <vort-button @click="cancelDetailDescEditor">取消</vort-button>
                            <vort-button
                                class="ml-auto"
                                :loading="descAi.loading.value"
                                @click="startAiEnrichDesc"
                            >
                                <Bot :size="14" class="mr-1" /> {{ aiEnrichBtnLabel }}
                            </vort-button>
                        </div>

                        <!-- AI description result area -->
                        <div v-if="descAi.html.value || descAi.loading.value" class="bug-detail-ai-desc">
                            <div class="bug-detail-ai-desc-head">
                                <h4 class="flex items-center gap-1.5">
                                    <Bot :size="14" class="text-blue-500" /> AI 生成的描述
                                </h4>
                                <div class="flex items-center gap-2">
                                    <button
                                        v-if="!descAi.loading.value && descAi.html.value"
                                        class="text-xs text-gray-400 hover:text-blue-500 transition-colors"
                                        @click="startAiEnrichDesc"
                                    >
                                        重新生成
                                    </button>
                                    <button
                                        v-if="descAi.loading.value"
                                        class="text-xs text-gray-400 hover:text-red-500 transition-colors"
                                        @click="descAi.abort()"
                                    >
                                        停止
                                    </button>
                                </div>
                            </div>

                            <div v-if="descAi.loading.value && !descAi.html.value" class="flex items-center gap-2 py-4 text-sm text-gray-400">
                                <Loader2 class="w-4 h-4 animate-spin" />
                                <span>{{ descAiPhaseLabel }}...</span>
                            </div>

                            <div
                                v-if="descAi.html.value"
                                class="ai-content text-[13px] leading-[1.75] text-gray-700"
                                v-html="descAi.html.value"
                            />

                            <div v-if="descAi.error.value" class="text-sm text-red-500 py-2">{{ descAi.error.value }}</div>

                            <div v-if="descAi.loading.value && descAi.html.value" class="flex items-center gap-1.5 mt-2 text-xs text-gray-400">
                                <Loader2 class="w-3 h-3 animate-spin" />
                                <span>{{ descAiPhaseLabel }}...</span>
                            </div>

                            <div v-if="descAi.html.value && !descAi.loading.value" class="bug-detail-ai-desc-apply">
                                <vort-button variant="primary" size="small" @click="applyAiDesc">
                                    应用 AI 描述
                                </vort-button>
                                <vort-button size="small" @click="descAi.clear()">
                                    忽略
                                </vort-button>
                            </div>
                        </div>
                    </template>
                    <template v-else>
                        <div v-if="(record.description || '').trim()" class="bug-detail-desc-content">
                            <MarkdownView :content="record.description || ''" />
                        </div>
                        <div v-else class="bug-detail-desc-content">-</div>
                    </template>
                </div>

                <div class="bug-detail-attachments">
                    <div class="bug-detail-attachments-head">
                        <h4><Paperclip :size="14" /> 附件 ({{ (record.attachments || []).length }})</h4>
                        <VortButton variant="text" size="small" :disabled="detailAttachmentUploading" @click="triggerDetailAttachmentInput">
                            {{ detailAttachmentUploading ? "上传中..." : "+ 添加" }}
                        </VortButton>
                        <input ref="detailAttachmentInputRef" type="file" multiple style="display: none" @change="handleDetailAttachmentFiles" />
                    </div>
                    <div v-if="(record.attachments || []).length > 0" class="bug-detail-attachment-list">
                        <div v-for="(att, idx) in record.attachments" :key="att.url" class="bug-detail-attachment-item">
                            <div class="bug-detail-attachment-info">
                                <span class="bug-detail-attachment-name" :title="att.name">{{ att.name }}</span>
                                <span class="bug-detail-attachment-size">{{ formatFileSize(att.size) }}</span>
                            </div>
                            <div class="bug-detail-attachment-actions">
                                <a :href="att.url" :download="att.name" class="bug-detail-attachment-download" title="下载">
                                    <Download :size="14" />
                                </a>
                                <button type="button" class="bug-detail-attachment-remove" title="删除" @click="removeDetailAttachment(idx)">
                                    <X :size="14" />
                                </button>
                            </div>
                        </div>
                    </div>
                    <div v-else class="bug-detail-attachment-empty">暂无附件</div>
                </div>

                <div class="bug-detail-bottom-panel">
                    <div class="bug-detail-bottom-tabs">
                        <button
                            :class="{ active: detailBottomTab === 'comments' }"
                            @click="detailBottomTab = 'comments'"
                        >
                            评论
                            <span class="count">{{ detailComments.length }}</span>
                        </button>
                        <button
                            :class="{ active: detailBottomTab === 'logs' }"
                            @click="detailBottomTab = 'logs'"
                        >
                            操作日志
                            <span class="count">{{ detailLogs.length }}</span>
                        </button>
                    </div>

                    <div v-if="detailBottomTab === 'comments'" class="bug-detail-comments">
                        <div v-if="detailComments.length === 0" class="bug-detail-empty">暂无评论</div>
                        <div v-else class="bug-detail-comment-list">
                            <div v-for="item in detailComments" :key="item.id" :id="'comment-' + item.id" class="bug-detail-comment-item">
                                <span class="bug-detail-comment-avatar">{{ item.author.slice(0, 1) }}</span>
                                <div class="bug-detail-comment-main">
                                    <div class="bug-detail-comment-meta">
                                        <span class="author">{{ item.author }}</span>
                                        <span class="time">{{ item.createdAt }}</span>
                                    </div>

                                    <div v-if="item.parentId && item.parentContent" class="comment-reply-quote">
                                        <span class="comment-reply-author">@{{ item.parentAuthor || '未知' }}</span>
                                        {{ item.parentContent.length > 80 ? item.parentContent.slice(0, 80) + '...' : item.parentContent }}
                                    </div>

                                    <template v-if="editingCommentId === item.id">
                                        <VortEditor
                                            v-model="editingCommentContent"
                                            :mention-members="memberOptions"
                                            min-height="80px"
                                            @mention-change="(ids: string[]) => editingCommentMentionIds = ids"
                                        />
                                        <div class="bug-detail-desc-actions" style="margin-top: 8px;">
                                            <vort-button size="small" @click="cancelEditComment">取消</vort-button>
                                            <vort-button size="small" variant="primary" @click="saveEditComment(item)">保存</vort-button>
                                        </div>
                                    </template>
                                    <div v-else class="bug-detail-comment-content"><MarkdownView :content="item.content" /></div>

                                    <div v-if="editingCommentId !== item.id" class="comment-actions">
                                        <span class="comment-action-btn" @click="startReplyComment(item)">回复</span>
                                        <span v-if="item.authorId && item.authorId === currentMemberId"
                                              class="comment-action-btn" @click="startEditComment(item)">编辑</span>
                                        <span v-if="item.authorId && item.authorId === currentMemberId"
                                              class="comment-action-btn comment-action-danger" @click="handleDeleteComment(item)">删除</span>
                                        <span class="comment-action-btn" @click="copyCommentLink(item)">复制链接</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="bug-detail-comment-editor">
                            <div v-if="replyingToComment" class="comment-reply-bar">
                                <span class="comment-reply-bar-text">
                                    回复 <strong>@{{ replyingToComment.author }}</strong>
                                </span>
                                <button class="comment-reply-bar-close" @click="cancelReply">
                                    <X :size="14" />
                                </button>
                            </div>
                            <VortEditor
                                v-model="detailCommentDraft"
                                :mention-members="memberOptions"
                                :placeholder="replyingToComment ? '输入回复内容...' : '输入 @ 可提及成员（Ctrl/Command+Enter发送）'"
                                min-height="120px"
                                @mention-change="(ids: string[]) => commentMentionIds = ids"
                            />
                            <div class="bug-detail-desc-actions">
                                <vort-button v-if="replyingToComment" size="small" @click="cancelReply">取消</vort-button>
                                <vort-button variant="primary" @click="submitDetailComment">{{ replyingToComment ? '回复' : '评论' }}</vort-button>
                            </div>
                        </div>
                    </div>

                    <div v-else class="bug-detail-logs">
                        <div v-if="detailLogs.length === 0" class="bug-detail-empty">暂无操作日志</div>
                        <div v-else class="bug-detail-log-list">
                            <div
                                v-for="item in detailLogs"
                                :key="item.id"
                                class="bug-detail-log-item-wrapper"
                            >
                                <div class="bug-detail-log-item">
                                    <span class="bug-detail-log-dot" />
                                    <span class="actor">{{ item.actor }}</span>
                                    <span class="action">{{ item.action }}</span>
                                    <button
                                        v-if="item.expandableChanges?.length"
                                        type="button"
                                        class="bug-detail-log-toggle"
                                        @click="toggleLogExpand(item.id)"
                                    >{{ logExpandedMap[item.id] ? '收起' : '展开详情' }}</button>
                                    <span class="time">{{ item.createdAt }}</span>
                                </div>
                                <div
                                    v-if="logExpandedMap[item.id] && item.expandableChanges?.length"
                                    class="bug-detail-log-changes"
                                >
                                    <div
                                        v-for="ch in item.expandableChanges"
                                        :key="ch.label"
                                        class="bug-detail-log-change"
                                    >
                                        <div class="bug-detail-log-change-label">{{ ch.label }}</div>
                                        <div class="bug-detail-log-change-row">
                                            <span class="bug-detail-log-change-tag">修改前</span>
                                            <pre class="bug-detail-log-change-content">{{ ch.before || '空' }}</pre>
                                        </div>
                                        <div class="bug-detail-log-change-row">
                                            <span class="bug-detail-log-change-tag bug-detail-log-change-tag--after">修改后</span>
                                            <pre class="bug-detail-log-change-content">{{ ch.after || '空' }}</pre>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="bug-detail-panel" v-else-if="detailActiveTab === 'worklog'">
                <p class="bug-detail-empty">暂无工作日志</p>
            </div>
            <div class="bug-detail-panel" v-else-if="detailActiveTab === 'related'">
                <WorkItemLinkPanel
                    v-if="record?.backendId"
                    :entity-type="linkEntityType"
                    :entity-id="record.backendId"
                    @open-related="(r) => emit('openRelated', r as any)"
                />
                <p v-else class="bug-detail-empty">暂无关联工作项</p>
            </div>
            <div class="bug-detail-panel" v-else-if="detailActiveTab === 'test'">
                <TestCaseLinkPanel
                    v-if="record?.backendId"
                    :entity-type="linkEntityType"
                    :entity-id="record.backendId"
                />
                <p v-else class="bug-detail-empty">暂无关联测试用例</p>
            </div>
            <div class="bug-detail-panel" v-else-if="detailActiveTab === 'docs'">
                <DocLinkPanel
                    v-if="record?.backendId"
                    :entity-type="linkEntityType"
                    :entity-id="record.backendId"
                    :project-id="record.projectId || ''"
                    @count-change="docLinkCount = $event"
                />
                <p v-else class="bug-detail-empty">暂无关联文档</p>
            </div>
        </main>
        <div v-else class="p-4 text-center text-gray-500">加载中...</div>

        <NotifyDialog
            v-if="record"
            v-model:open="notifyDialogOpen"
            :entity-type="getEntityTypeKey()"
            :entity-id="record.backendId || ''"
            :title="record.title"
            :project-id="record.projectId || ''"
            :current-member-id="currentMemberId || ''"
            :owner-id="record.ownerId || ''"
            :owner-name="record.owner === '未指派' ? '' : record.owner"
            :collaborator-names="record.collaborators || []"
            :get-member-id-by-name="getMemberIdByName"
            :get-avatar-bg="getAvatarBg"
            :get-member-avatar-url="getMemberAvatarUrl"
        />
    </div>
</template>

<style scoped>
.bug-detail-drawer {
    height: 100%;
}

.bug-detail-main {
    padding: 0 4px;
}

.bug-detail-meta-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
}

.bug-detail-meta-left {
    display: flex;
    align-items: center;
    gap: 12px;
}

.bug-detail-meta-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
}

.detail-more-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #fff;
    cursor: pointer;
    color: #666;
    transition: all 0.15s;
}

.detail-more-btn:hover {
    border-color: var(--vort-primary, #1456f0);
    color: var(--vort-primary, #1456f0);
}

.work-type-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    font-size: 18px;
}

.work-type-icon-demand {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    color: white;
}

.work-type-icon-task {
    background: linear-gradient(135deg, #0ea5e9 0%, #06b6d4 100%);
    color: white;
}

.work-type-icon-bug {
    background: linear-gradient(135deg, #ef4444 0%, #f97316 100%);
    color: white;
}

.bug-detail-no {
    font-size: 14px;
    color: var(--vort-text-secondary);
    font-weight: 500;
}

.detail-copy-link-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--vort-text-secondary);
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
}

.detail-copy-link-btn:hover {
    background: var(--vort-primary-bg);
    color: var(--vort-text);
}

.detail-status-trigger {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    border-radius: 4px;
}

.detail-status-content {
    display: flex;
    align-items: center;
    gap: 4px;
}

.detail-status-icon {
    font-size: 14px;
}

.detail-status-text {
    font-size: 14px;
    color: var(--vort-text);
}

.status-arrow-simple {
    display: inline-block;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid var(--vort-text-tertiary);
    transition: transform 0.2s;
}

.status-arrow-simple.open {
    transform: rotate(180deg);
}

.bug-detail-title {
    font-size: 20px;
    font-weight: 600;
    color: var(--vort-text);
    margin: 0 0 8px 0;
    line-height: 1.4;
}

.bug-detail-title-editable {
    cursor: text;
    border-radius: 4px;
    padding: 2px 6px;
    margin-left: -6px;
    transition: background 0.15s;
}

.bug-detail-title-editable:hover {
    background: var(--vort-bg-hover, rgba(0, 0, 0, 0.04));
}

.bug-detail-title-input {
    font-size: 20px;
    font-weight: 600;
    color: var(--vort-text);
    margin: 0 0 8px 0;
    line-height: 1.4;
    padding: 2px 6px;
    margin-left: -6px;
    width: 100%;
    border: 1px solid var(--vort-primary);
    border-radius: 4px;
    outline: none;
    background: var(--vort-bg);
    box-shadow: 0 0 0 2px rgba(var(--vort-primary-rgb, 59, 130, 246), 0.15);
}

.bug-detail-sub {
    font-size: 13px;
    color: var(--vort-text-secondary);
    margin: 0 0 20px 0;
}

.story-tree-header {
    margin-bottom: 8px;
}

.story-parent-node {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--vort-text-secondary);
    cursor: pointer;
    font-size: 14px;
    transition: color 0.2s;
}

.story-parent-node:hover {
    color: var(--vort-primary);
}

.work-type-icon-small {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
}

.work-type-icon-svg-small {
    width: 16px;
    height: 16px;
}

.parent-title {
    max-width: 400px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.story-child-node {
    display: flex;
    align-items: flex-start;
    margin-top: 4px;
}

.tree-line {
    width: 16px;
    height: 20px;
    border-left: 1.5px solid var(--vort-border);
    border-bottom: 1.5px solid var(--vort-border);
    border-bottom-left-radius: 6px;
    margin-left: 7px;
    margin-right: 8px;
    margin-top: -4px;
    flex-shrink: 0;
}

.bug-detail-tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--vort-border-secondary);
    margin-bottom: 20px;
}

.bug-detail-tabs button {
    padding: 10px 16px;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--vort-text-secondary);
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
}

.bug-detail-tabs button:hover {
    color: var(--vort-text);
}

.bug-detail-tabs button.active {
    color: var(--vort-primary);
    border-bottom-color: var(--vort-primary);
}

.bug-detail-tabs .tab-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    margin-left: 4px;
    font-size: 12px;
    line-height: 1;
    border-radius: 9px;
    background: var(--vort-bg-hover, #f0f0f0);
    color: var(--vort-text-secondary);
}

.bug-detail-tabs button.active .tab-count {
    background: var(--vort-primary-bg, #eff6ff);
    color: var(--vort-primary);
}

.bug-detail-top-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px 48px;
    margin-bottom: 24px;
}

.bug-detail-left-col,
.bug-detail-right-col {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.bug-detail-info-item {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.bug-detail-info-item label {
    font-size: 13px;
    color: var(--vort-text-secondary);
    font-weight: 400;
}

.bug-detail-info-item > div {
    font-size: 14px;
    color: var(--vort-text);
}

.bug-detail-info-item-row {
    flex-direction: row;
    justify-content: flex-start;
    align-items: center;
    min-height: 32px;
}

.bug-detail-info-item-row label {
    flex-shrink: 0;
    width: 100px;
}

.bug-detail-info-assignee {
    cursor: pointer;
}

/* 子需求栏目样式 */
.bug-detail-sub-items {
    margin-bottom: 24px;
}

.bug-detail-sub-items-head {
    display: flex;
    align-items: center;
    margin-bottom: 12px;
}

.bug-detail-sub-items-head h4 {
    font-size: 14px;
    font-weight: 600;
    color: var(--vort-text);
    margin: 0;
}

.bug-detail-sub-items-head .count {
    background: var(--vort-border-secondary);
    color: var(--vort-text-secondary);
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
}

.add-sub-item-btn {
    color: var(--vort-primary) !important;
    font-size: 13px !important;
    padding: 4px 8px !important;
    height: auto !important;
}

.add-sub-item-btn:hover {
    background: var(--vort-primary-bg) !important;
}

.add-sub-item-btn .icon {
    margin-right: 4px;
    font-size: 16px;
    line-height: 1;
}

.bug-detail-sub-items-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px 0;
    background: var(--vort-border-secondary);
    border: 1px dashed var(--vort-border);
    border-radius: 8px;
}

.bug-detail-sub-items-empty .empty-text {
    color: var(--vort-text-tertiary);
    font-size: 13px;
}

.bug-detail-sub-items-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.bug-detail-sub-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    background: var(--vort-bg);
    border: 1px solid var(--vort-border-secondary);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
}

.bug-detail-sub-item:hover {
    border-color: var(--vort-primary-bg-hover);
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
}

.sub-item-left {
    display: flex;
    align-items: center;
    gap: 12px;
    overflow: hidden;
}

.sub-item-no {
    font-size: 12px;
    font-weight: 500;
    color: var(--vort-text-tertiary);
    flex-shrink: 0;
}

.sub-item-title {
    font-size: 13px;
    color: var(--vort-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transition: color 0.2s;
}

.sub-item-right {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
    margin-left: 16px;
}

.sub-item-owner {
    display: flex;
    align-items: center;
    gap: 6px;
}

.sub-item-owner .owner-name {
    font-size: 12px;
    color: var(--vort-text-secondary);
}

.sub-item-more {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: none;
    background: none;
    border-radius: 4px;
    color: var(--vort-text-tertiary);
    cursor: pointer;
    transition: all 0.15s;
}

.sub-item-more:hover {
    background: var(--vort-border-secondary);
    color: var(--vort-text);
}

.sub-item-status {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    background: var(--vort-bg-elevated);
    border: 1px solid var(--vort-border-secondary);
    border-radius: 4px;
    min-width: 72px;
    justify-content: center;
}

.sub-item-status .status-icon {
    font-size: 12px;
    line-height: 1;
}

.sub-item-status .status-text {
    font-size: 12px;
    color: var(--vort-text-secondary);
}

.detail-assignee-trigger {
    display: flex;
    align-items: center;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid transparent;
    margin-left: -10px;
}

.detail-assignee-trigger:hover,
.detail-assignee-trigger.active {
    background: var(--vort-bg-elevated);
    border-color: var(--vort-border-secondary);
}

.detail-assignee-split {
    display: flex;
    align-items: center;
    gap: 8px;
}

.detail-assignee-owner {
    display: flex;
    align-items: center;
    gap: 6px;
}

.detail-assignee-avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    font-size: 11px;
    color: white;
    font-weight: 500;
}

.detail-assignee-owner-name {
    font-size: 13px;
    color: var(--vort-text);
}

.detail-assignee-separator {
    color: var(--vort-border);
    font-size: 15px;
    margin: 0 6px;
}

.detail-assignee-collaborators {
    display: flex;
    align-items: center;
    gap: 4px;
}

.detail-assignee-add {
    background: var(--vort-border-secondary) !important;
    color: var(--vort-text-tertiary) !important;
    font-size: 14px !important;
    border: 1px dashed var(--vort-border);
}

.detail-assignee-dropdown {
    width: 280px;
    padding: 12px;
}

.detail-assignee-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-radius: 6px;
}

.detail-assignee-row:hover {
    background: var(--vort-bg-elevated);
}

.detail-assignee-row-left {
    display: flex;
    align-items: center;
    gap: 8px;
}

.detail-assignee-row-actions {
    display: flex;
    gap: 4px;
}

.detail-role-btn {
    font-size: 12px !important;
    padding: 4px 8px !important;
    color: var(--vort-text-secondary);
}

.detail-role-btn.active {
    color: var(--vort-primary);
    background: var(--vort-primary-bg);
}

.detail-role-btn.collab.active {
    color: #8b5cf6;
    background: #f5f3ff;
}

.bug-detail-desc {
    margin-bottom: 24px;
}

.bug-detail-desc-head {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-bottom: 12px;
}

.bug-detail-desc-head h4 {
    font-size: 14px;
    font-weight: 600;
    color: var(--vort-text);
    margin: 0;
}

.bug-detail-desc-edit-btn {
    color: var(--vort-text-secondary);
}

.bug-detail-desc-content {
    font-size: 14px;
    color: var(--vort-text-secondary);
    line-height: 1.6;
    padding: 12px;
    background: var(--vort-bg-elevated);
    border-radius: 8px;
    min-height: 60px;
}

.bug-detail-desc-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
}

.bug-detail-ai-bar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 8px;
}

.bug-detail-ai-desc {
    margin-top: 16px;
    padding: 16px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
}

.bug-detail-ai-desc-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
}

.bug-detail-ai-desc-head h4 {
    font-size: 13px;
    font-weight: 500;
    color: #374151;
    margin: 0;
}

.bug-detail-ai-desc-apply {
    display: flex;
    gap: 8px;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #e2e8f0;
}

.ai-content :deep(h1),
.ai-content :deep(h2),
.ai-content :deep(h3),
.ai-content :deep(h4) {
    font-size: 13px;
    font-weight: 600;
    color: #374151;
    margin-top: 1em;
    margin-bottom: 0.4em;
}
.ai-content :deep(h1:first-child),
.ai-content :deep(h2:first-child),
.ai-content :deep(h3:first-child) {
    margin-top: 0;
}
.ai-content :deep(p) {
    margin: 0.4em 0;
}
.ai-content :deep(ul),
.ai-content :deep(ol) {
    margin: 0.3em 0;
    padding-left: 1.5em;
}
.ai-content :deep(li) {
    margin: 0.15em 0;
}
.ai-content :deep(pre) {
    background: #f1f5f9;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 12px;
    line-height: 1.6;
    overflow-x: auto;
    margin: 0.5em 0;
}
.ai-content :deep(code) {
    font-size: 12px;
    background: #f3f4f6;
    border-radius: 3px;
    padding: 1px 4px;
}
.ai-content :deep(pre code) {
    background: none;
    padding: 0;
}
.ai-content :deep(strong) {
    font-weight: 600;
    color: #1f2937;
}
.ai-content :deep(table) {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin: 0.5em 0;
}
.ai-content :deep(th),
.ai-content :deep(td) {
    border: 1px solid #e5e7eb;
    padding: 4px 8px;
    text-align: left;
}
.ai-content :deep(th) {
    background: #f9fafb;
    font-weight: 600;
}

.bug-detail-attachments {
    border-top: 1px solid var(--vort-border-secondary);
    padding-top: 16px;
    margin-top: 16px;
}

.bug-detail-attachments-head {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
}

.bug-detail-attachments-head h4 {
    font-size: 14px;
    font-weight: 600;
    color: var(--vort-text);
    display: flex;
    align-items: center;
    gap: 4px;
    margin: 0;
    flex: 1;
}

.bug-detail-attachment-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.bug-detail-attachment-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    background: var(--vort-bg-elevated);
    border-radius: 6px;
    border: 1px solid var(--vort-border-secondary);
}

.bug-detail-attachment-info {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
}

.bug-detail-attachment-name {
    font-size: 13px;
    color: var(--vort-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.bug-detail-attachment-size {
    font-size: 12px;
    color: var(--vort-text-tertiary);
    white-space: nowrap;
}

.bug-detail-attachment-actions {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
}

.bug-detail-attachment-download,
.bug-detail-attachment-remove {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: none;
    border-radius: 4px;
    background: none;
    color: var(--vort-text-secondary);
    cursor: pointer;
    transition: all 0.15s;
}

.bug-detail-attachment-download:hover {
    color: var(--vort-primary);
    background: var(--vort-bg-hover);
}

.bug-detail-attachment-remove:hover {
    color: var(--vort-danger, #e53e3e);
    background: var(--vort-bg-hover);
}

.bug-detail-attachment-empty {
    font-size: 13px;
    color: var(--vort-text-tertiary);
    padding: 8px 0;
}

.bug-detail-bottom-panel {
    border-top: 1px solid var(--vort-border-secondary);
    padding-top: 20px;
    padding-bottom: 50px;
}

.bug-detail-bottom-tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 16px;
}

.bug-detail-bottom-tabs button {
    padding: 8px 12px;
    background: none;
    border: none;
    border-radius: 6px;
    color: var(--vort-text-secondary);
    font-size: 13px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
}

.bug-detail-bottom-tabs button:hover {
    background: var(--vort-border-secondary);
}

.bug-detail-bottom-tabs button.active {
    background: var(--vort-primary-bg);
    color: var(--vort-primary);
}

.bug-detail-bottom-tabs .count {
    background: var(--vort-border-secondary);
    padding: 2px 6px;
    border-radius: 10px;
    font-size: 11px;
}

.bug-detail-bottom-tabs button.active .count {
    background: var(--vort-primary-bg-hover);
}

.bug-detail-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 48px 20px;
    color: var(--vort-text-tertiary);
    font-size: 14px;
}

.bug-detail-empty-icon {
    color: var(--vort-text-quaternary, #d0d5dd);
}

.story-children-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.story-children-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    padding: 12px 14px;
    border: 1px solid var(--vort-border-secondary);
    border-radius: 10px;
    background: var(--vort-bg);
    text-align: left;
}

.story-children-item:hover {
    border-color: var(--vort-primary-bg-hover);
    background: var(--vort-primary-bg);
}

.story-children-title {
    color: var(--vort-text);
    font-size: 14px;
}

.story-children-status {
    color: var(--vort-text-secondary);
    font-size: 12px;
    white-space: nowrap;
}

.bug-detail-comment-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    margin-bottom: 20px;
}

.bug-detail-comment-item {
    display: flex;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid var(--vort-border-secondary, #f0f0f0);
}

.bug-detail-comment-item:last-child {
    border-bottom: none;
}

.bug-detail-comment-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: linear-gradient(135deg, #f59e0b, #f97316);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 600;
    flex-shrink: 0;
}

.bug-detail-comment-main {
    flex: 1;
    min-width: 0;
}

.bug-detail-comment-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
}

.bug-detail-comment-meta .author {
    font-size: 13px;
    font-weight: 600;
    color: var(--vort-text);
}

.bug-detail-comment-meta .time {
    font-size: 12px;
    color: var(--vort-text-tertiary);
}

.comment-reply-quote {
    background: #f7f8fa;
    border-left: 3px solid var(--vort-primary, #1456f0);
    padding: 6px 10px;
    margin-bottom: 6px;
    border-radius: 0 4px 4px 0;
    font-size: 13px;
    color: var(--vort-text-tertiary);
    line-height: 1.5;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.comment-reply-author {
    color: var(--vort-primary, #1456f0);
    font-weight: 500;
    margin-right: 4px;
}

.bug-detail-comment-content {
    font-size: 14px;
    color: var(--vort-text-secondary);
    line-height: 1.6;
}

.comment-actions {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-top: 6px;
    opacity: 0;
    transition: opacity 0.15s;
}

.bug-detail-comment-item:hover .comment-actions {
    opacity: 1;
}

.comment-action-btn {
    font-size: 12px;
    color: var(--vort-text-tertiary, #999);
    cursor: pointer;
    transition: color 0.15s;
    user-select: none;
}

.comment-action-btn:hover {
    color: var(--vort-primary, #1456f0);
}

.comment-action-danger:hover {
    color: #ef4444;
}

.bug-detail-comment-editor {
    border-top: 1px solid var(--vort-border-secondary);
    padding-top: 16px;
    padding-bottom: 50px;
}

.comment-reply-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    margin-bottom: 8px;
    background: #f7f8fa;
    border-radius: 6px;
    border: 1px solid var(--vort-border-secondary, #f0f0f0);
}

.comment-reply-bar-text {
    font-size: 13px;
    color: var(--vort-text-secondary);
}

.comment-reply-bar-text strong {
    color: var(--vort-primary, #1456f0);
}

.comment-reply-bar-close {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border: none;
    background: transparent;
    border-radius: 4px;
    cursor: pointer;
    color: var(--vort-text-tertiary);
    transition: all 0.15s;
}

.comment-reply-bar-close:hover {
    background: #e5e7eb;
    color: var(--vort-text);
}

.bug-detail-log-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.bug-detail-log-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
}

.bug-detail-log-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--vort-border);
    flex-shrink: 0;
}

.bug-detail-log-item .actor {
    font-weight: 500;
    color: var(--vort-text);
}

.bug-detail-log-item .action {
    color: var(--vort-text-secondary);
}

.bug-detail-log-item .time {
    color: var(--vort-text-tertiary);
    margin-left: auto;
}

.bug-detail-log-item-wrapper {
    display: flex;
    flex-direction: column;
}

.bug-detail-log-toggle {
    background: transparent;
    border: none;
    padding: 0 4px;
    color: var(--vort-primary, #1456f0);
    cursor: pointer;
    font-size: 12px;
    line-height: 1;
}

.bug-detail-log-toggle:hover {
    text-decoration: underline;
}

.bug-detail-log-changes {
    margin-left: 14px;
    margin-top: 8px;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    background: var(--vort-bg-secondary, #f7f8fa);
    border: 1px solid var(--vort-border-secondary, #f0f0f0);
    border-radius: 6px;
}

.bug-detail-log-change {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.bug-detail-log-change-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--vort-text);
}

.bug-detail-log-change-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
}

.bug-detail-log-change-tag {
    flex-shrink: 0;
    padding: 2px 6px;
    background: #fef3c7;
    color: #92400e;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    line-height: 1.5;
}

.bug-detail-log-change-tag--after {
    background: #dcfce7;
    color: #166534;
}

.bug-detail-log-change-content {
    flex: 1;
    margin: 0;
    padding: 6px 10px;
    background: var(--vort-bg, #fff);
    border: 1px solid var(--vort-border-secondary, #f0f0f0);
    border-radius: 4px;
    font-size: 13px;
    line-height: 1.5;
    color: var(--vort-text);
    font-family: inherit;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 240px;
    overflow-y: auto;
}

.detail-field-shell {
    display: inline-flex;
    align-items: center;
    min-width: 0;
    border-radius: 4px;
    transition: background 0.15s;
}

.detail-field-shell:not(.is-editing):hover {
    background: var(--vort-border-secondary);
}

.detail-field-shell :deep(.vort-select-selector) {
    width: auto;
}

.detail-field-shell:not(.is-editing) :deep(.vort-select-selector) {
    border-color: transparent !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 4px 8px !important;
}

.detail-field-shell:not(.is-editing) :deep(.vort-select-arrow-wrapper),
.detail-field-shell:not(.is-editing) :deep(.vort-select-clear),
.detail-field-shell:not(.is-editing) :deep(.vort-rangepicker-prefix),
.detail-field-shell:not(.is-editing) :deep(.vort-rangepicker-suffix),
.detail-field-shell:not(.is-editing) :deep(.vort-datepicker-prefix),
.detail-field-shell:not(.is-editing) :deep(.vort-datepicker-suffix),
.detail-field-shell:not(.is-editing) :deep(.vort-datepicker-clear),
.detail-field-shell:not(.is-editing) :deep(.vort-input-number-handler-wrap) {
    display: none !important;
}

.detail-field-shell:not(.is-editing) :deep(.vort-select-placeholder),
.detail-field-shell:not(.is-editing) :deep(.vort-rangepicker-placeholder),
.detail-field-shell:not(.is-editing) :deep(.vort-rangepicker-input-placeholder),
.detail-field-shell:not(.is-editing) :deep(.vort-datepicker-placeholder),
.detail-field-shell:not(.is-editing) :deep(.vort-input-number-input::placeholder) {
    color: var(--vort-text-tertiary) !important;
}

.detail-field-shell :deep(.vort-rangepicker-selector) {
    width: auto;
}

.detail-field-shell:not(.is-editing) :deep(.vort-rangepicker-selector) {
    border-color: transparent !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 4px 8px !important;
}

.detail-field-picker :deep(.vort-rangepicker-prefix) {
    display: none;
}

.detail-field-picker :deep(.vort-rangepicker-separator) {
    padding: 0 4px;
}

.detail-field-picker :deep(.vort-rangepicker-input) {
    font-size: 14px;
}

.detail-field-shell :deep(.vort-datepicker-selector) {
    width: auto;
}

.detail-field-shell:not(.is-editing) :deep(.vort-datepicker-selector) {
    border-color: transparent !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 4px 8px !important;
}

.detail-field-picker :deep(.vort-datepicker-value) {
    font-size: 14px;
}

.detail-field-shell :deep(.vort-input-number) {
    width: 120px;
}

.detail-field-shell:not(.is-editing) :deep(.vort-input-number) {
    border-color: transparent !important;
    background: transparent !important;
    box-shadow: none !important;
}

.detail-field-shell:not(.is-editing) :deep(.vort-input-number-input) {
    padding-left: 8px !important;
    padding-right: 8px !important;
    background: transparent !important;
}

.detail-progress-shell {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 160px;
    cursor: pointer;
    padding: 4px 0;
}
.detail-progress-bar {
    flex: 1;
    height: 8px;
    min-width: 60px;
    border-radius: 9999px;
    background-color: var(--vort-bg-secondary, #f0f0f0);
    overflow: hidden;
}
.detail-progress-fill {
    height: 100%;
    border-radius: 9999px;
    background-color: #22c55e;
    transition: width 0.2s ease;
}
.detail-progress-text {
    font-size: 13px;
    color: var(--vort-text-secondary, rgba(0, 0, 0, 0.65));
    white-space: nowrap;
    min-width: 36px;
}
</style>
