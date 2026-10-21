<script setup lang="ts">
import { ref, watch } from "vue";
import { X } from "lucide-vue-next";
import VortEditor from "@/components/vort-biz/editor/VortEditor.vue";

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

const props = withDefaults(defineProps<{
    mentionMembers?: MentionMember[];
    quickPhrases?: QuickPhrase[];
    placeholder?: string;
    minHeight?: string;
    submitText?: string;
    loading?: boolean;
    replyTo?: { id: number; authorName: string } | null;
    initialContent?: string;
    initialMentions?: string[];
    showCancel?: boolean;
}>(), {
    mentionMembers: () => [],
    quickPhrases: () => [],
    placeholder: "输入 @ 可提及成员，Ctrl/Cmd + Enter 发送",
    minHeight: "100px",
    submitText: "发表评论",
    loading: false,
    replyTo: null,
    initialContent: "",
    initialMentions: () => [],
    showCancel: false,
});

const emit = defineEmits<{
    submit: [payload: { content: string; mentions: string[] }];
    cancel: [];
    cancelReply: [];
}>();

const content = ref(props.initialContent || "");
const mentionIds = ref<string[]>([...(props.initialMentions || [])]);

watch(() => props.initialContent, (val) => {
    content.value = val || "";
});
watch(() => props.initialMentions, (val) => {
    mentionIds.value = [...(val || [])];
});

function handleMentionChange(ids: string[]) {
    mentionIds.value = ids;
}

function plainText(html: string): string {
    return html.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim();
}

function pickPhrase(phrase: QuickPhrase) {
    const token = phrase.emoji ? `${phrase.emoji} ${phrase.label}` : phrase.label;
    const current = (content.value || "").trim();
    content.value = current ? `${current}\n${token}` : token;
}

function handleSubmit() {
    if (props.loading) return;
    if (!plainText(content.value)) return;
    emit("submit", { content: content.value, mentions: mentionIds.value });
}

function handleCancel() {
    emit("cancel");
}

function handleCancelReply() {
    emit("cancelReply");
}

function reset() {
    content.value = "";
    mentionIds.value = [];
}

defineExpose({ reset });
</script>

<template>
    <div class="comment-input">
        <div v-if="replyTo" class="comment-input-reply-bar">
            <span class="comment-input-reply-text">回复 <strong>@{{ replyTo.authorName }}</strong></span>
            <button type="button" class="comment-input-reply-close" @click="handleCancelReply">
                <X :size="13" />
            </button>
        </div>

        <div v-if="quickPhrases.length" class="comment-input-quick">
            <button
                v-for="p in quickPhrases"
                :key="p.code"
                type="button"
                class="comment-input-quick-chip"
                @click="pickPhrase(p)"
            >
                <span v-if="p.emoji" class="comment-input-quick-emoji">{{ p.emoji }}</span>
                <span>{{ p.label }}</span>
            </button>
        </div>

        <VortEditor
            v-model="content"
            :mention-members="mentionMembers"
            :placeholder="placeholder"
            :min-height="minHeight"
            @mention-change="handleMentionChange"
        />
        <div class="comment-input-actions">
            <vort-button v-if="showCancel" size="small" @click="handleCancel">取消</vort-button>
            <vort-button
                size="small"
                variant="primary"
                :loading="loading"
                :disabled="!plainText(content)"
                @click="handleSubmit"
            >{{ submitText }}</vort-button>
        </div>
    </div>
</template>

<style scoped>
.comment-input {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.comment-input-reply-bar {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: #eff6ff;
    color: #1d4ed8;
    border-radius: 6px;
    font-size: 12px;
    align-self: flex-start;
}

.comment-input-reply-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    background: transparent;
    border: none;
    color: #1d4ed8;
    cursor: pointer;
    border-radius: 4px;
}

.comment-input-reply-close:hover {
    background: rgba(29, 78, 216, 0.15);
}

.comment-input-quick {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.comment-input-quick-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 999px;
    border: 1px solid #e5e7eb;
    background: #fff;
    color: #4b5563;
    font-size: 12px;
    line-height: 1.4;
    cursor: pointer;
    transition: all 0.15s ease;
}

.comment-input-quick-chip:hover {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
}

.comment-input-quick-emoji {
    font-size: 13px;
    line-height: 1;
}

.comment-input-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
}
</style>
