import { computed, reactive, ref, type ComputedRef, type Ref } from "vue";
import { dialog, message } from "@openvort/vort-ui";
import {
    createVortflowComment,
    deleteVortflowComment,
    getVortflowComments,
    updateVortflowComment,
} from "@/api";
import type {
    DetailComment,
    RowItem,
} from "@/components/vort-biz/work-item/WorkItemTable.types";

export interface UseWorkItemDetailCommentsOptions {
    /** 当前打开的工作项；用于读取 backendId 拼接评论 API */
    record: Ref<RowItem | null>;
    /** 当前抽屉对应的 workNo（作为 commentsMap 的 key） */
    workNo: ComputedRef<string>;
    /** 当前操作人显示名（评论提交后乐观插入用） */
    currentUser: ComputedRef<string>;
    /** 当前操作人成员 ID（用于「编辑/删除自己的评论」权限判定） */
    currentMemberId: ComputedRef<string>;
    /** 把成员 ID 转成显示名 */
    getMemberNameById: (id: string) => string;
    /** 把当前 record.type 转换成后端 entity_type（story/task/bug） */
    getEntityType: () => string;
    /** 时间格式化（与活动日志侧共用一份） */
    formatTimeAgo: (iso: string) => string;
}

/**
 * 工作项详情面板「评论」相关状态与操作。
 *
 * 抽离自 WorkItemDetail.vue 阶段 D1：
 * - 草稿/编辑/回复/@提及 状态
 * - CRUD（saveEditComment / handleDeleteComment / submitDetailComment）
 * - 复制评论锚点链接
 * - 远程加载评论列表（loadComments）
 */
export function useWorkItemDetailComments(opts: UseWorkItemDetailCommentsOptions) {
    const detailCommentsMap = reactive<Record<string, DetailComment[]>>({});
    const detailCommentDraft = ref("");
    const editingCommentId = ref<string | null>(null);
    const editingCommentContent = ref("");
    const editingCommentMentionIds = ref<string[]>([]);
    const replyingToComment = ref<DetailComment | null>(null);
    const commentMentionIds = ref<string[]>([]);

    const detailComments = computed<DetailComment[]>(() => {
        const id = opts.workNo.value;
        return id ? detailCommentsMap[id] || [] : [];
    });

    const startEditComment = (item: DetailComment) => {
        replyingToComment.value = null;
        editingCommentId.value = item.id;
        editingCommentContent.value = item.content;
    };

    const cancelEditComment = () => {
        editingCommentId.value = null;
        editingCommentContent.value = "";
        editingCommentMentionIds.value = [];
    };

    const saveEditComment = async (item: DetailComment) => {
        const content = editingCommentContent.value.trim();
        if (!content) return;
        try {
            await updateVortflowComment(item.id, {
                content,
                mentions: editingCommentMentionIds.value.length > 0
                    ? [...editingCommentMentionIds.value]
                    : undefined,
            });
            item.content = content;
            message.success("评论已更新");
            editingCommentId.value = null;
            editingCommentContent.value = "";
            editingCommentMentionIds.value = [];
        } catch {
            message.error("更新评论失败");
        }
    };

    const handleDeleteComment = (item: DetailComment) => {
        dialog.confirm({
            title: "确认删除",
            content: "确定要删除这条评论吗？删除后不可恢复。",
            okType: "danger",
            okText: "删除",
            onOk: async () => {
                try {
                    await deleteVortflowComment(item.id);
                    const workNo = opts.workNo.value;
                    const comments = workNo ? detailCommentsMap[workNo] : null;
                    if (comments) {
                        const idx = comments.findIndex(c => c.id === item.id);
                        if (idx >= 0) comments.splice(idx, 1);
                    }
                    message.success("评论已删除");
                } catch {
                    message.error("删除评论失败");
                }
            },
        });
    };

    const startReplyComment = (item: DetailComment) => {
        editingCommentId.value = null;
        replyingToComment.value = item;
        detailCommentDraft.value = "";
    };

    const cancelReply = () => {
        replyingToComment.value = null;
        detailCommentDraft.value = "";
    };

    const copyCommentLink = async (item: DetailComment) => {
        const link = `${window.location.href}#comment-${item.id}`;
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
            message.success("评论链接已复制");
        } catch {
            message.error("复制链接失败");
        }
    };

    const submitDetailComment = async () => {
        const content = detailCommentDraft.value.trim();
        if (!content) {
            message.warning("请先输入评论内容");
            return;
        }
        const entityId = opts.record.value?.backendId;
        if (!entityId) return;
        const workNo = opts.workNo.value;
        const parentComment = replyingToComment.value;
        const parentId = parentComment ? Number(parentComment.id) : undefined;
        try {
            const res: any = await createVortflowComment(opts.getEntityType(), entityId, {
                content,
                parent_id: parentId || null,
                mentions: commentMentionIds.value.length > 0
                    ? [...commentMentionIds.value]
                    : undefined,
            });
            const comments = detailCommentsMap[workNo] || (detailCommentsMap[workNo] = []);
            const newComment: DetailComment = {
                id: String(res?.id || `${workNo}-c-${Date.now()}`),
                author: opts.currentUser.value,
                authorId: opts.currentMemberId.value,
                createdAt: "刚刚",
                content,
                parentId: parentId || null,
                parentAuthor: parentComment?.author,
                parentContent: parentComment?.content?.slice(0, 200),
            };
            comments.push(newComment);
            detailCommentDraft.value = "";
            replyingToComment.value = null;
            commentMentionIds.value = [];
            message.success("评论已发布");
        } catch (error: any) {
            message.error(error?.message || "评论发布失败");
        }
    };

    /** 远程加载评论列表，按 workNo 写入 detailCommentsMap */
    const loadComments = async (entityType: string, entityId: string) => {
        const workNo = opts.workNo.value;
        if (!workNo) return;
        try {
            const res: any = await getVortflowComments(entityType, entityId);
            const items = ((res?.items) || []) as any[];
            detailCommentsMap[workNo] = items.map((c: any) => ({
                id: String(c.id),
                author: opts.getMemberNameById(c.author_id) || c.author_id || "未知",
                authorId: c.author_id || "",
                createdAt: opts.formatTimeAgo(c.created_at),
                content: c.content || "",
                parentId: c.parent_id || null,
                parentAuthor: c.parent_author_id
                    ? (opts.getMemberNameById(c.parent_author_id) || c.parent_author_id)
                    : undefined,
                parentContent: c.parent_content || undefined,
            }));
        } catch {
            if (!detailCommentsMap[workNo]) detailCommentsMap[workNo] = [];
        }
    };

    /** 没有 backendId 的草稿工作项也要保证 commentsMap 存在空数组 */
    const ensureCommentsForCurrentWorkNo = () => {
        const workNo = opts.workNo.value;
        if (!workNo) return;
        if (!detailCommentsMap[workNo]) detailCommentsMap[workNo] = [];
    };

    return {
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
        loadComments,
        ensureCommentsForCurrentWorkNo,
    };
}
