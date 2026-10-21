<script setup lang="ts">
import { computed } from "vue";
import { Dialog } from "@openvort/vort-ui";
import dayjs from "dayjs";

interface ProbeResult {
    domain: string;
    status: string;
    expires_at: string | null;
    days_remaining: number | null;
    issuer: string;
    error_message: string;
    san_list?: string[];
    probe_target?: string;
}

const props = defineProps<{
    open: boolean;
    domain: string;
    loading: boolean;
    result: ProbeResult | null;
}>();

const emit = defineEmits<{
    "update:open": [val: boolean];
}>();

const statusMeta = computed(() => {
    const map: Record<string, { color: string; label: string }> = {
        ok: { color: "green", label: "正常" },
        warning: { color: "orange", label: "即将到期" },
        critical: { color: "red", label: "紧急" },
        expired: { color: "red", label: "已过期" },
        error: { color: "default", label: "异常" },
    };
    return map[props.result?.status || ""] || { color: "default", label: props.result?.status || "未知" };
});

const expiresLabel = computed(() => {
    const r = props.result;
    if (!r?.expires_at) return "—";
    const date = dayjs(r.expires_at).format("YYYY-MM-DD HH:mm");
    if (r.days_remaining === null || r.days_remaining === undefined) return date;
    return `${date}（剩余 ${r.days_remaining} 天）`;
});

const probeTargetLabel = computed(() => {
    const r = props.result;
    if (!r?.probe_target) return "";
    if (r.probe_target === props.domain) return "";
    return r.probe_target;
});
</script>

<template>
    <Dialog
        :open="open"
        :title="`在线探测：${domain}`"
        :width="600"
        :footer="false"
        @update:open="emit('update:open', $event)"
    >
        <div v-if="loading" class="py-6 text-center text-sm text-gray-500">
            正在连接目标服务器并获取证书…
        </div>

        <div v-else-if="!result" class="py-6 text-center text-sm text-gray-400">
            暂无探测结果
        </div>

        <div v-else class="space-y-3 text-sm">
            <div class="grid grid-cols-[110px_1fr] gap-y-3 gap-x-3 items-start">
                <div class="text-gray-500">探测目标</div>
                <div class="text-gray-800 break-all">
                    {{ result.probe_target || domain }}:443
                    <span v-if="probeTargetLabel" class="text-xs text-gray-400 ml-1">
                        （通配符 {{ domain }} 实际探测 {{ probeTargetLabel }}）
                    </span>
                </div>

                <div class="text-gray-500">状态</div>
                <div>
                    <vort-tag :color="statusMeta.color" size="small">{{ statusMeta.label }}</vort-tag>
                </div>

                <div class="text-gray-500">颁发者</div>
                <div class="text-gray-800 break-all">{{ result.issuer || "—" }}</div>

                <div class="text-gray-500">到期时间</div>
                <div class="text-gray-800">{{ expiresLabel }}</div>

                <div v-if="result.san_list && result.san_list.length" class="text-gray-500">SAN</div>
                <div v-if="result.san_list && result.san_list.length" class="text-gray-800 flex flex-wrap gap-1">
                    <vort-tag v-for="s in result.san_list" :key="s" color="default" size="small">{{ s }}</vort-tag>
                </div>
            </div>

            <div v-if="result.error_message" class="p-3 rounded-lg bg-orange-50 text-sm text-orange-700 leading-relaxed whitespace-pre-line">
                {{ result.error_message }}
            </div>

            <div class="p-3 rounded-lg bg-gray-50 text-xs text-gray-500 leading-relaxed">
                在线探测会直接连接目标服务器 443 端口抓取实际部署的证书，不会修改域名主状态。如需刷新该域名在系统中的状态，请使用「检查」按钮。
            </div>
        </div>
    </Dialog>
</template>
