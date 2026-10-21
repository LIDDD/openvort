<script setup lang="ts">
import { ref, watch } from "vue";
import { dialog, message } from "@openvort/vort-ui";
import { Plus, Trash2 } from "lucide-vue-next";
import {
    getReactionPhrases,
    createReactionPhrase,
    updateReactionPhrase,
    deleteReactionPhrase,
} from "@/api";

interface Phrase {
    id: string;
    code: string;
    label: string;
    emoji: string;
    sort_order: number;
    enabled: boolean;
}

const props = defineProps<{
    open: boolean;
}>();

const emit = defineEmits<{
    "update:open": [val: boolean];
    saved: [];
}>();

const phrases = ref<Phrase[]>([]);
const loading = ref(false);
const saving = ref(false);

const showAddForm = ref(false);
const newCode = ref("");
const newLabel = ref("");
const newEmoji = ref("");

async function load() {
    loading.value = true;
    try {
        const res: any = await getReactionPhrases();
        phrases.value = res?.items || [];
    } catch {
        phrases.value = [];
    } finally {
        loading.value = false;
    }
}

watch(() => props.open, (val) => {
    if (val) {
        load();
        showAddForm.value = false;
        newCode.value = "";
        newLabel.value = "";
        newEmoji.value = "";
    }
});

function resetAddForm() {
    showAddForm.value = false;
    newCode.value = "";
    newLabel.value = "";
    newEmoji.value = "";
}

async function handleAdd() {
    const code = newCode.value.trim();
    const label = newLabel.value.trim();
    if (!code || !label) {
        message.warning("code 和 label 都是必填项");
        return;
    }
    if (!/^[a-z0-9_-]+$/i.test(code)) {
        message.warning("code 只能包含字母、数字、下划线和短横线");
        return;
    }
    saving.value = true;
    try {
        await createReactionPhrase({
            code,
            label,
            emoji: newEmoji.value.trim(),
            sort_order: (phrases.value.length + 1) * 10,
            enabled: true,
        });
        message.success("已添加");
        resetAddForm();
        await load();
        emit("saved");
    } catch (e: any) {
        message.error(e?.response?.data?.detail || "添加失败");
    } finally {
        saving.value = false;
    }
}

async function handleUpdateField(item: Phrase, field: "label" | "emoji" | "enabled", value: any) {
    if ((item as any)[field] === value) return;
    try {
        const data: any = {};
        data[field] = value;
        await updateReactionPhrase(item.id, data);
        (item as any)[field] = value;
        emit("saved");
    } catch (e: any) {
        message.error(e?.response?.data?.detail || "更新失败");
    }
}

async function handleMove(index: number, dir: -1 | 1) {
    const target = index + dir;
    if (target < 0 || target >= phrases.value.length) return;
    const a = phrases.value[index]!;
    const b = phrases.value[target]!;
    try {
        await Promise.all([
            updateReactionPhrase(a.id, { sort_order: b.sort_order }),
            updateReactionPhrase(b.id, { sort_order: a.sort_order }),
        ]);
        await load();
        emit("saved");
    } catch {
        message.error("排序失败");
    }
}

function handleDelete(item: Phrase) {
    dialog.confirm({
        title: "删除点评文案",
        content: `确定删除文案「${item.label}」？已有的点评记录会一并清除，此操作不可撤销。`,
        okText: "删除",
        cancelText: "取消",
        onOk: async () => {
            try {
                await deleteReactionPhrase(item.id);
                message.success("已删除");
                await load();
                emit("saved");
            } catch (e: any) {
                message.error(e?.response?.data?.detail || "删除失败");
            }
        },
    });
}
</script>

<template>
    <vort-drawer
        :open="open"
        title="点评文案设置"
        :width="520"
        @update:open="emit('update:open', $event)"
    >
        <vort-spin :spinning="loading">
            <div class="phrase-panel">
                <p class="phrase-tip">
                    维护汇报详情中可用的快速点评文案。code 是业务标识（仅字母/数字/下划线），用于绑定点评数据；label 是展示文案；emoji 可选。
                </p>

                <div class="phrase-list">
                    <div v-for="(item, idx) in phrases" :key="item.id" class="phrase-item">
                        <div class="phrase-item-main">
                            <div class="phrase-item-code">{{ item.code }}</div>
                            <div class="phrase-item-fields">
                                <vort-input
                                    :model-value="item.emoji"
                                    placeholder="emoji"
                                    style="width: 70px"
                                    @blur="(e: any) => handleUpdateField(item, 'emoji', (e.target.value || '').trim())"
                                />
                                <vort-input
                                    :model-value="item.label"
                                    placeholder="文案"
                                    style="flex: 1"
                                    @blur="(e: any) => handleUpdateField(item, 'label', (e.target.value || '').trim())"
                                />
                                <vort-switch
                                    :checked="item.enabled"
                                    @update:checked="(val: boolean) => handleUpdateField(item, 'enabled', val)"
                                />
                            </div>
                        </div>
                        <div class="phrase-item-actions">
                            <button type="button" class="phrase-icon-btn" :disabled="idx === 0" @click="handleMove(idx, -1)">↑</button>
                            <button type="button" class="phrase-icon-btn" :disabled="idx === phrases.length - 1" @click="handleMove(idx, 1)">↓</button>
                            <button type="button" class="phrase-icon-btn phrase-icon-btn-danger" @click="handleDelete(item)">
                                <Trash2 :size="14" />
                            </button>
                        </div>
                    </div>
                </div>

                <div v-if="!loading && phrases.length === 0" class="phrase-empty">暂无点评文案，请点击下方按钮添加</div>

                <div class="phrase-add">
                    <template v-if="showAddForm">
                        <div class="phrase-add-form">
                            <vort-input v-model="newCode" placeholder="code（英文，如 thanks）" style="width: 180px" />
                            <vort-input v-model="newEmoji" placeholder="emoji（可选）" style="width: 110px" />
                            <vort-input v-model="newLabel" placeholder="文案" style="flex: 1" />
                        </div>
                        <div class="phrase-add-actions">
                            <vort-button size="small" @click="resetAddForm">取消</vort-button>
                            <vort-button size="small" variant="primary" :loading="saving" @click="handleAdd">添加</vort-button>
                        </div>
                    </template>
                    <vort-button v-else block @click="showAddForm = true">
                        <Plus :size="14" class="mr-1" /> 添加点评文案
                    </vort-button>
                </div>
            </div>
        </vort-spin>
    </vort-drawer>
</template>

<style scoped>
.phrase-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.phrase-tip {
    margin: 0;
    color: #6b7280;
    font-size: 12px;
    line-height: 1.6;
}

.phrase-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.phrase-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    border: 1px solid #f3f4f6;
    border-radius: 8px;
    background: #fafafa;
}

.phrase-item-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
}

.phrase-item-code {
    font-size: 11px;
    color: #9ca3af;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.phrase-item-fields {
    display: flex;
    align-items: center;
    gap: 6px;
}

.phrase-item-actions {
    display: flex;
    align-items: center;
    gap: 4px;
}

.phrase-icon-btn {
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    color: #6b7280;
    cursor: pointer;
    font-size: 12px;
}

.phrase-icon-btn:hover:not(:disabled) {
    border-color: #93c5fd;
    color: #1d4ed8;
}

.phrase-icon-btn-danger:hover:not(:disabled) {
    border-color: #fca5a5;
    color: #dc2626;
}

.phrase-icon-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.phrase-empty {
    padding: 20px 0;
    color: #9ca3af;
    font-size: 13px;
    text-align: center;
}

.phrase-add {
    margin-top: 8px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.phrase-add-form {
    display: flex;
    gap: 6px;
}

.phrase-add-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
}
</style>
