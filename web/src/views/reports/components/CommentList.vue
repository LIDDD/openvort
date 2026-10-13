<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { dialog, message } from "@openvort/vort-ui";
import MarkdownView from "@/components/vort-biz/editor/MarkdownView.vue";
import {
    getReportComments,
    createReportComment,
    updateReportComment,
    deleteReportComment,
    getMembersSimple,
    getReactionPhrases,
} from "@/api";
import { useUserStore } from "@/stores";
import CommentInput from "./CommentInput.vue";

interface CommentItem {
    id: number;
    report_id: string;
    author_id: string;
    author_name: string;
    author_avatar_url: string;
    parent_id: number | null;
    content: string;
    mentions: string[];
    created_at: string;
    updated_at: string;
    parent_author_id?: string;
    parent_author_name?: string;
    parent_content?: string;
}

interface MentionMember {
    id: string;
    name: string;
    avatar_url?: string;
}

interface QuickPhrase {
    code: string;
    label: string;
    emoji: string;
}

const props = defineProps<{
    reportId: string;
}>();

const userStore = useUserStore();
const comments = ref<CommentItem[]>([]);
const loading = ref(false);
const submitting = ref(false);
const editingId = ref<number | null>(null);
const replyTo = ref<{ id: number; authorName: string } | null>(null);
const memberOptions = ref<MentionMember[]>([]);
const quickPhrases = ref<QuickPhrase[]>([]);
const newCommentInputRef = ref<{ reset: () => void } | null>(null);

const currentMemberId = computed(() => userStore.userInfo.member_id || "");

async function loadMembers() {
    if (memberOptions.value.length) return;
    try {
        const res: any = await getMembersSimple({ size: 200 });
        const list = res?.items || res?.members || res || [];
        memberOptions.value = (Array.isArray(list) ? list : []).map((m: any) => ({
            id: m.id || m.member_id,
            name: m.name || m.display_name || "",
            avatar_url: m.avatar_url || "",
        })).filter((m: MentionMember) => m.id && m.name);
    } catch {
        memberOptions.value = [];
    }
}

async function loadPhrases() {
    if (quickPhrases.value.length) return;
    try {
        const res: any = await getReactionPhrases({ enabled_only: true });
        quickPhrases.value = (res?.items || []).map((p: any) => ({
            code: p.code,
            label: p.label,
            emoji: p.emoji || "",
        }));
    } catch {
        quickPhrases.value = [];
    }
}

async function load() {
    if (!props.reportId) return;
    loading.value = true;
    try {
        const res: any = await getReportComments(props.reportId);
        comments.value = res?.items || [];
    } catch {
        comments.value = [];
    } finally {
        loading.value = false;
    }
}

watch(() => props.reportId, (id) => {
    if (id) {
        loadMembers();
        loadPhrases();
        load();
        editingId.value = null;
        replyTo.value = null;
    }
}, { immediate: true });

defineExpose({ refresh: load });

// Group: root comments + their replies (1 level only)
interface GroupedComment {
    root: CommentItem;
    replies: CommentItem[];
}

const grouped = computed<GroupedComment[]>(() => {
    const roots: CommentItem[] = [];
    const repliesByParent: Map<number, CommentItem[]> = new Map();
    for (const c of comments.value) {
        if (c.parent_id) {
            const arr = repliesByParent.get(c.parent_id) || [];
            arr.push(c);
            repliesByParent.set(c.parent_id, arr);
        } else {
            roots.push(c);
        }
    }
    return roots.map(root => ({
        root,
        replies: repliesByParent.get(root.id) || [],
    }));
});

function formatTime(iso: string): string {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const min = Math.floor(diffMs / 60000);
    if (min < 1) return "刚刚";
    if (min < 60) return `${min} 分钟前`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h} 小时前`;
    const day = Math.floor(h / 24);
    if (day < 7) return `${day} 天前`;
    return iso.slice(0, 16).replace("T", " ");
}

async function submitNew(payload: { content: string; mentions: string[] }) {
    submitting.value = true;
    try {
        await createReportComment(props.reportId, {
            content: payload.content,
            parent_id: replyTo.value?.id ?? null,
            mentions: payload.mentions,
        });
        replyTo.value = null;
        newCommentInputRef.value?.reset();
        await load();
    } catch (e: any) {
        message.error(e?.response?.data?.detail || "评论失败");
    } finally {
        submitting.value = false;
    }
}

function startReply(item: CommentItem) {
    replyTo.value = { id: item.id, authorName: item.author_name || "未知" };
}

function cancelReply() {
    replyTo.value = null;
}

function startEdit(item: CommentItem) {
    editingId.value = item.id;
}

function cancelEdit() {
    editingId.value = null;
}

async function saveEdit(item: CommentItem, payload: { content: string; mentions: string[] }) {
    submitting.value = true;
    try {
        await updateReportComment(item.id, {
            content: payload.content,
            mentions: payload.mentions,
        });
        editingId.value = null;
        await load();
    } catch (e: any) {
        message.error(e?.response?.data?.detail || "保存失败");
    } finally {
        submitting.value = false;
    }
}

async function removeComment(item: CommentItem) {
    dialog.confirm({
        title: "删除评论",
        content: "确定删除这条评论？此操作不可撤销。",
        okText: "删除",
        cancelText: "取消",
        onOk: async () => {
            try {
                await deleteReportComment(item.id);
                message.success("已删除");
                await load();
            } catch (e: any) {
                message.error(e?.response?.data?.detail || "删除失败");
            }
        },
    });
}

const AVATAR_COLORS = ["#1677ff", "#52c41a", "#faad14", "#eb2f96", "#722ed1", "#13c2c2", "#fa541c", "#2f54eb"];
function avatarBg(name: string): string {
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]!;
}
</script>

<template>
    <div class="report-comments">
        <div class="report-comments-header">
            <h4 class="report-comments-title">评论 <span class="report-comments-count">{{ comments.length }}</span></h4>
        </div>

        <vort-spin :spinning="loading">
            <div v-if="!loading && grouped.length === 0" class="report-comments-empty">暂无评论</div>
            <div v-else class="report-comments-list">
                <div v-for="g in grouped" :key="g.root.id" class="comment-thread">
                    <div class="comment-item">
                        <div
                            class="comment-avatar"
                            :style="{ backgroundColor: g.root.author_avatar_url ? undefined : avatarBg(g.root.author_name || '?') }"
                        >
                            <img v-if="g.root.author_avatar_url" :src="g.root.author_avatar_url" class="comment-avatar-img" />
                            <span v-else class="comment-avatar-text">{{ (g.root.author_name || '?')[0] }}</span>
                        </div>
                        <div class="comment-body">
                            <div class="comment-meta">
                                <span class="comment-author">{{ g.root.author_name }}</span>
                                <span class="comment-time">{{ formatTime(g.root.created_at) }}</span>
                            </div>
                            <template v-if="editingId === g.root.id">
                                <CommentInput
                                    :mention-members="memberOptions"
                                    :initial-content="g.root.content"
                                    :initial-mentions="g.root.mentions"
                                    :loading="submitting"
                                    submit-text="保存"
                                    show-cancel
                                    min-height="80px"
                                    @submit="(p) => saveEdit(g.root, p)"
                                    @cancel="cancelEdit"
                                />
                            </template>
                            <template v-else>
                                <div class="comment-content"><MarkdownView :content="g.root.content" /></div>
                                <div class="comment-actions">
                                    <span class="comment-action" @click="startReply(g.root)">回复</span>
                                    <template v-if="g.root.author_id === currentMemberId">
                                        <span class="comment-action" @click="startEdit(g.root)">编辑</span>
                                        <span class="comment-action comment-action-danger" @click="removeComment(g.root)">删除</span>
                                    </template>
                                </div>
                            </template>
                        </div>
                    </div>

                    <div v-for="reply in g.replies" :key="reply.id" class="comment-item comment-reply">
                        <div
                            class="comment-avatar"
                            :style="{ backgroundColor: reply.author_avatar_url ? undefined : avatarBg(reply.author_name || '?') }"
                        >
                            <img v-if="reply.author_avatar_url" :src="reply.author_avatar_url" class="comment-avatar-img" />
                            <span v-else class="comment-avatar-text">{{ (reply.author_name || '?')[0] }}</span>
                        </div>
                        <div class="comment-body">
                            <div class="comment-meta">
                                <span class="comment-author">{{ reply.author_name }}</span>
                                <span v-if="reply.parent_author_name" class="comment-reply-to">回复 @{{ reply.parent_author_name }}</span>
                                <span class="comment-time">{{ formatTime(reply.created_at) }}</span>
                            </div>
                            <template v-if="editingId === reply.id">
                                <CommentInput
                                    :mention-members="memberOptions"
                                    :initial-content="reply.content"
                                    :initial-mentions="reply.mentions"
                                    :loading="submitting"
                                    submit-text="保存"
                                    show-cancel
                                    min-height="80px"
                                    @submit="(p) => saveEdit(reply, p)"
                                    @cancel="cancelEdit"
                                />
                            </template>
                            <template v-else>
                                <div class="comment-content"><MarkdownView :content="reply.content" /></div>
                                <div class="comment-actions">
                                    <span class="comment-action" @click="startReply(reply)">回复</span>
                                    <template v-if="reply.author_id === currentMemberId">
                                        <span class="comment-action" @click="startEdit(reply)">编辑</span>
                                        <span class="comment-action comment-action-danger" @click="removeComment(reply)">删除</span>
                                    </template>
                                </div>
                            </template>
                        </div>
                    </div>
                </div>
            </div>
        </vort-spin>

        <div class="report-comments-footer">
            <CommentInput
                ref="newCommentInputRef"
                :mention-members="memberOptions"
                :quick-phrases="replyTo ? [] : quickPhrases"
                :placeholder="replyTo ? '输入回复内容…' : '输入 @ 可提及成员，Ctrl/Cmd + Enter 发送；也可以点上方标签快速填入'"
                :loading="submitting"
                :reply-to="replyTo"
                :submit-text="replyTo ? '回复' : '发表评论'"
                :show-cancel="!!replyTo"
                min-height="100px"
                @submit="submitNew"
                @cancel="cancelReply"
                @cancel-reply="cancelReply"
            />
        </div>
    </div>
</template>

<style scoped>
.report-comments {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.report-comments-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.report-comments-title {
    margin: 0;
    font-size: 13px;
    font-weight: 500;
    color: #4b5563;
}

.report-comments-count {
    display: inline-block;
    min-width: 18px;
    padding: 0 6px;
    margin-left: 4px;
    background: #f3f4f6;
    border-radius: 999px;
    color: #6b7280;
    font-weight: 400;
    text-align: center;
    line-height: 18px;
    font-size: 11px;
}

.report-comments-empty {
    padding: 20px 0;
    text-align: center;
    color: #9ca3af;
    font-size: 13px;
}

.report-comments-list {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.comment-thread {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.comment-item {
    display: flex;
    gap: 10px;
    align-items: flex-start;
}

.comment-reply {
    margin-left: 36px;
    padding-left: 12px;
    border-left: 2px solid #f3f4f6;
}

.comment-avatar {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    margin-top: 2px;
}

.comment-avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.comment-avatar-text {
    color: #fff;
    font-size: 12px;
    font-weight: 500;
}

.comment-body {
    flex: 1;
    min-width: 0;
}

.comment-meta {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 4px;
    font-size: 12px;
}

.comment-author {
    color: #111827;
    font-weight: 500;
}

.comment-reply-to {
    color: #6b7280;
    font-size: 11px;
}

.comment-time {
    color: #9ca3af;
    font-size: 11px;
}

.comment-content {
    color: #374151;
    font-size: 13px;
    line-height: 1.6;
    word-break: break-word;
}

.comment-content :deep(p) {
    margin: 0 0 4px;
}

.comment-content :deep(p:last-child) {
    margin-bottom: 0;
}

.comment-actions {
    display: flex;
    gap: 12px;
    margin-top: 6px;
}

.comment-action {
    font-size: 12px;
    color: #6b7280;
    cursor: pointer;
    user-select: none;
}

.comment-action:hover {
    color: #1d4ed8;
}

.comment-action-danger {
    color: #ef4444;
}

.comment-action-danger:hover {
    color: #dc2626;
}

.report-comments-footer {
    margin-top: 4px;
    padding-top: 12px;
    border-top: 1px solid #f3f4f6;
}
</style>
