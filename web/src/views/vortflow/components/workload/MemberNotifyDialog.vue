<template>
    <Dialog
        :open="open"
        title="发送通知"
        :confirm-loading="submitting"
        ok-text="发送"
        @ok="handleSubmit"
        @update:open="$emit('update:open', $event)"
    >
        <div class="space-y-5">
            <div>
                <div class="text-sm font-medium text-gray-700 mb-2">通知类型</div>
                <vort-radio-group v-model="form.notifyType">
                    <vort-radio-button value="remind">
                        <span class="inline-flex items-center gap-1">
                            <Bell :size="14" />
                            提醒
                        </span>
                    </vort-radio-button>
                    <vort-radio-button value="urge">
                        <span class="inline-flex items-center gap-1">
                            <AlarmClock :size="14" />
                            催办
                        </span>
                    </vort-radio-button>
                </vort-radio-group>
                <p class="text-xs text-gray-400 mt-1">
                    {{ form.notifyType === "urge"
                        ? "催办将以更高优先级提醒对方尽快处理在手工作量"
                        : "温和地提醒对方关注当前在手工作量与风险" }}
                </p>
            </div>

            <div>
                <div class="text-sm font-medium text-gray-700 mb-2">通知对象</div>
                <div class="member-card-row">
                    <span
                        class="inline-flex items-center justify-center w-8 h-8 rounded-full text-white text-xs font-medium flex-shrink-0 overflow-hidden"
                        :style="{ background: avatarBg }"
                    >
                        <img
                            v-if="member.avatarUrl"
                            :src="member.avatarUrl"
                            class="w-full h-full object-cover"
                        />
                        <template v-else>{{ avatarLabel }}</template>
                    </span>
                    <div class="flex-1 min-w-0">
                        <div class="text-sm text-gray-800 truncate">{{ member.name }}</div>
                        <div v-if="member.dept" class="text-xs text-gray-400 truncate">{{ member.dept }}</div>
                    </div>
                </div>

                <div v-if="workloadSummary.length" class="workload-summary">
                    <span
                        v-for="tag in workloadSummary"
                        :key="tag.label"
                        class="workload-tag"
                        :class="`tone-${tag.tone}`"
                    >
                        {{ tag.label }}
                    </span>
                </div>
                <p class="text-xs text-gray-400 mt-2">
                    将向对方推送站内消息 + IM 通知，并附上以上工作量数据。
                </p>
            </div>

            <div>
                <div class="text-sm font-medium text-gray-700 mb-2">
                    附言 <span class="text-gray-400 font-normal">(可选)</span>
                </div>
                <vort-textarea
                    v-model="form.message"
                    placeholder="补充想说的话，比如「下午站会前请同步进度」"
                    :rows="3"
                    :maxlength="200"
                />
            </div>
        </div>
    </Dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Dialog, message } from "@openvort/vort-ui";
import { AlarmClock, Bell } from "lucide-vue-next";
import { sendVortflowMemberNotify } from "@/api";

interface MemberInfo {
    id: string;
    name: string;
    avatarUrl?: string;
    dept?: string;
}

interface WorkloadInfo {
    pending_total?: number;
    overdue?: number;
    due_soon?: number;
    stale_count?: number;
}

const props = defineProps<{
    open: boolean;
    member: MemberInfo;
    workload?: WorkloadInfo;
    projectId?: string;
}>();

const emit = defineEmits<{
    (e: "update:open", val: boolean): void;
    (e: "sent"): void;
}>();

const submitting = ref(false);
const form = ref({
    notifyType: "remind" as "remind" | "urge",
    message: "",
});

// Stable hash-based color so a member always maps to the same chip color,
// independent of where the dialog is opened from.
const palette = ["#2f80ed", "#5b8ff9", "#9b59b6", "#27ae60", "#f39c12", "#e67e22", "#16a085", "#8b44ad"];
const avatarBg = computed(() => {
    const name = props.member?.name || "?";
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    }
    return palette[hash % palette.length];
});

const avatarLabel = computed(() => {
    const n = (props.member?.name || "").trim();
    return n ? n.slice(0, 1).toUpperCase() : "?";
});

interface SummaryTag {
    label: string;
    tone: "info" | "danger" | "warn" | "stale";
}

const workloadSummary = computed<SummaryTag[]>(() => {
    const w = props.workload || {};
    const arr: SummaryTag[] = [];
    if ((w.pending_total ?? 0) > 0) arr.push({ label: `在手 ${w.pending_total}`, tone: "info" });
    if ((w.overdue ?? 0) > 0) arr.push({ label: `逾期 ${w.overdue}`, tone: "danger" });
    if ((w.due_soon ?? 0) > 0) arr.push({ label: `即将到期 ${w.due_soon}`, tone: "warn" });
    if ((w.stale_count ?? 0) > 0) arr.push({ label: `停滞 ${w.stale_count}`, tone: "stale" });
    return arr;
});

watch(
    () => props.open,
    (val) => {
        if (val) {
            form.value = { notifyType: "remind", message: "" };
            submitting.value = false;
        }
    },
);

async function handleSubmit() {
    if (!props.member?.id) {
        message.warning("缺少成员信息");
        return;
    }
    submitting.value = true;
    try {
        await sendVortflowMemberNotify({
            recipient_id: props.member.id,
            notify_type: form.value.notifyType,
            message: form.value.message || undefined,
            project_id: props.projectId || undefined,
            pending_total: props.workload?.pending_total || 0,
            overdue: props.workload?.overdue || 0,
            due_soon: props.workload?.due_soon || 0,
            stale_count: props.workload?.stale_count || 0,
        });
        message.success("通知已发送");
        emit("sent");
        emit("update:open", false);
    } catch {
        message.error("发送通知失败");
    } finally {
        submitting.value = false;
    }
}
</script>

<style scoped>
.member-card-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    background: #fafafa;
}

.workload-summary {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.workload-tag {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    line-height: 1.6;
    font-weight: 500;
}
.workload-tag.tone-info {
    background: rgba(59, 130, 246, 0.1);
    color: #1d4ed8;
}
.workload-tag.tone-danger {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
}
.workload-tag.tone-warn {
    background: rgba(245, 158, 11, 0.12);
    color: #b45309;
}
.workload-tag.tone-stale {
    background: rgba(107, 114, 128, 0.12);
    color: #4b5563;
}
</style>
