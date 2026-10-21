<script setup lang="ts">
import { ref, onMounted, watch } from "vue";
import { useRouter } from "vue-router";
import { Bell, BellOff, Clock, Bot, CheckCheck, Settings, ExternalLink, GitPullRequestArrow, MonitorSmartphone } from "lucide-vue-next";
import { getNotifications, batchReadNotifications } from "@/api";
import { message } from "@openvort/vort-ui";
import { useNotificationStore } from "@/stores/modules/notification";
import { useDesktopNotification } from "@/composables/useDesktopNotification";

const router = useRouter();
const notificationStore = useNotificationStore();
const desktop = useDesktopNotification();

async function handleEnableDesktop() {
    if (desktop.isActive.value) {
        desktop.disable();
        message.success("已关闭桌面通知");
        return;
    }
    if (!desktop.supported) {
        message.error("当前浏览器不支持桌面通知");
        return;
    }
    if (desktop.isDenied.value) {
        message.warning("通知权限被浏览器拒绝，请到浏览器设置中允许 OpenVort 发送通知");
        return;
    }
    const ok = await desktop.enable();
    if (ok) {
        message.success("桌面通知已开启");
        desktop.notify({
            title: "OpenVort",
            body: "桌面通知已开启，新消息将出现在系统通知中心",
            tag: "openvort:welcome",
            force: true,
        });
    } else {
        message.warning("未获得通知权限");
    }
}

async function handleSendTest() {
    if (!desktop.supported) {
        message.error("当前浏览器不支持桌面通知");
        return;
    }
    if (desktop.isDenied.value) {
        message.warning("通知权限被浏览器拒绝，请到浏览器设置中允许 OpenVort 发送通知");
        return;
    }
    if (!desktop.isGranted.value) {
        const ok = await desktop.enable();
        if (!ok) {
            message.warning("未获得通知权限");
            return;
        }
    }
    await desktop.notify({
        title: "OpenVort 测试通知",
        body: `这是一条测试通知 · ${new Date().toLocaleTimeString()}`,
        tag: `openvort:test:${Date.now()}`,
        force: true,
    });
    message.info("已发送测试通知，请查看系统通知中心");
}

interface NotificationItem {
    id: number;
    source: string;
    source_id: string;
    session_id: string;
    title: string;
    summary: string;
    status: string;
    im_channel: string;
    data: Record<string, any>;
    created_at: string;
    read_at: string;
}

const popoverRef = ref<InstanceType<any> | null>(null);
const notifications = ref<NotificationItem[]>([]);
const loading = ref(false);
const total = ref(0);
const unreadCount = ref(0);

async function loadNotifications() {
    loading.value = true;
    try {
        const res: any = await getNotifications({ limit: 20 });
        notifications.value = res?.notifications || [];
        total.value = res?.total || 0;
        unreadCount.value = (res?.notifications || []).filter(
            (n: NotificationItem) => n.status === "pending" || n.status === "sent"
        ).length;
    } catch {
        notifications.value = [];
    } finally {
        loading.value = false;
    }
}

async function handleBatchRead() {
    try {
        await batchReadNotifications([], true);
        message.success("已全部标为已读");
        unreadCount.value = 0;
        notifications.value = notifications.value.map(n => ({ ...n, status: "read" }));
        notificationStore.fetchVortflowUnreadCount();
    } catch {
        message.error("操作失败");
    }
}

const _ENTITY_TYPE_ROUTE: Record<string, string> = {
    story: "stories",
    task: "tasks",
    bug: "bugs",
};

async function handleNotificationClick(n: NotificationItem) {
    popoverRef.value?.hide();
    if (n.status === "pending" || n.status === "sent") {
        batchReadNotifications([n.id]).catch(() => {});
        n.status = "read";
        unreadCount.value = Math.max(0, unreadCount.value - 1);
        if (n.source === "vortflow") {
            notificationStore.fetchVortflowUnreadCount();
        }
    }
    if (n.source === "vortflow" && n.data?.entity_type && n.data?.entity_id) {
        const routeSegment = _ENTITY_TYPE_ROUTE[n.data.entity_type];
        if (routeSegment) {
            const query: Record<string, string> = {
                action: "detail",
                id: n.data.entity_id,
            };
            if (n.data.project_id) query.project = n.data.project_id;
            router.push({ path: `/vortflow/${routeSegment}`, query });
            return;
        }
    }
    if (n.session_id) {
        router.push({ path: "/chat", query: { session: n.session_id } });
    }
}

function goToAll() {
    popoverRef.value?.hide();
    router.push("/notifications");
}

function goToSettings() {
    popoverRef.value?.hide();
    router.push({ path: "/profile", query: { tab: "notification" } });
}

function formatTime(iso: string): string {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60000) return "刚刚";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
    return d.toLocaleDateString();
}

function handleOpenChange(open: boolean) {
    if (open) {
        loadNotifications();
    }
}

onMounted(() => {
    loadNotifications();
});
</script>

<template>
    <vort-popover
        ref="popoverRef"
        trigger="click"
        placement="bottomRight"
        :arrow="false"
        overlay-class="notification-popover-overlay"
        @open-change="handleOpenChange"
    >
        <div class="relative flex items-center justify-center w-9 h-9 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors">
            <Bell :size="18" class="text-gray-500" />
            <span
                v-if="unreadCount > 0"
                class="absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center px-1 leading-none"
            >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
        </div>

        <template #content>
            <div class="w-[380px]">
                <!-- Header -->
                <div class="flex items-center justify-between pb-3 border-b border-gray-100">
                    <span class="text-sm font-medium text-gray-800">通知</span>
                    <div class="flex items-center gap-1">
                        <button
                            v-if="desktop.supported"
                            class="flex items-center justify-center w-6 h-6 rounded transition-colors"
                            :class="desktop.isActive.value
                                ? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
                                : 'text-gray-400 hover:text-blue-600 hover:bg-blue-50'"
                            :title="desktop.isActive.value ? '关闭桌面通知' : '开启桌面通知（系统通知中心）'"
                            @click="handleEnableDesktop"
                        >
                            <MonitorSmartphone v-if="desktop.isActive.value" :size="13" />
                            <BellOff v-else :size="13" />
                        </button>
                        <button
                            class="flex items-center gap-1 px-2 py-1 text-[11px] text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                            @click="handleBatchRead"
                        >
                            <CheckCheck :size="12" />
                            全部已读
                        </button>
                        <button
                            class="flex items-center justify-center w-6 h-6 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
                            @click="goToSettings"
                        >
                            <Settings :size="13" />
                        </button>
                    </div>
                </div>

                <!-- 桌面通知引导横幅：仅在浏览器支持且未授权/未开启时显示 -->
                <div
                    v-if="desktop.supported && !desktop.isActive.value && !desktop.isDenied.value"
                    class="mt-2 flex items-center gap-2 px-2.5 py-2 bg-blue-50/60 border border-blue-100 rounded-lg"
                >
                    <Bell :size="14" class="text-blue-500 flex-shrink-0" />
                    <span class="text-[12px] text-gray-600 flex-1">开启桌面通知，第一时间收到系统提醒</span>
                    <button
                        class="px-2 py-0.5 text-[11px] text-white bg-blue-600 hover:bg-blue-700 rounded transition-colors"
                        @click="handleEnableDesktop"
                    >
                        开启
                    </button>
                </div>
                <div
                    v-else-if="desktop.supported && desktop.isActive.value"
                    class="mt-2 flex items-center gap-2 px-2.5 py-2 bg-green-50/60 border border-green-100 rounded-lg"
                >
                    <MonitorSmartphone :size="14" class="text-green-600 flex-shrink-0" />
                    <span class="text-[12px] text-gray-600 flex-1">桌面通知已开启（页面前台聚焦时不弹）</span>
                    <button
                        class="px-2 py-0.5 text-[11px] text-blue-600 hover:bg-blue-100 border border-blue-200 rounded transition-colors"
                        @click="handleSendTest"
                    >
                        测试
                    </button>
                </div>
                <div
                    v-else-if="desktop.supported && desktop.isDenied.value"
                    class="mt-2 flex items-center gap-2 px-2.5 py-2 bg-amber-50/60 border border-amber-100 rounded-lg"
                >
                    <BellOff :size="14" class="text-amber-500 flex-shrink-0" />
                    <span class="text-[12px] text-gray-600 flex-1">桌面通知被浏览器拒绝，请到浏览器设置开启</span>
                </div>

                <!-- List -->
                <div class="max-h-[400px] overflow-y-auto -mx-3 px-3">
                    <div v-if="loading" class="py-10 text-center text-gray-400 text-xs">加载中...</div>
                    <div v-else-if="notifications.length === 0" class="py-10 text-center text-gray-400 text-xs">暂无通知</div>
                    <div v-else class="py-1">
                        <div
                            v-for="n in notifications"
                            :key="n.id"
                            class="flex items-start gap-2.5 px-2 py-2.5 -mx-2 rounded-lg cursor-pointer transition-colors"
                            :class="n.status === 'pending' || n.status === 'sent' ? 'hover:bg-blue-50/60 bg-blue-50/30' : 'hover:bg-gray-50'"
                            @click="handleNotificationClick(n)"
                        >
                            <div class="flex-shrink-0 mt-0.5">
                                <Clock v-if="n.source === 'schedule'" :size="15" class="text-blue-500" />
                                <Bot v-else-if="n.source === 'ai_message'" :size="15" class="text-blue-500" />
                                <GitPullRequestArrow v-else-if="n.source === 'vortflow'" :size="15" class="text-indigo-500" />
                                <Bell v-else :size="15" class="text-gray-400" />
                            </div>
                            <div class="flex-1 min-w-0">
                                <div class="flex items-center gap-1.5">
                                    <span
                                        v-if="n.status === 'pending' || n.status === 'sent'"
                                        class="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-blue-500"
                                    />
                                    <span class="text-[13px] font-medium text-gray-700 truncate">{{ n.title }}</span>
                                </div>
                                <p v-if="n.summary" class="text-[11px] text-gray-400 mt-0.5 line-clamp-1">{{ n.summary }}</p>
                            </div>
                            <span class="text-[11px] text-gray-300 flex-shrink-0 whitespace-nowrap mt-0.5">{{ formatTime(n.created_at) }}</span>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="pt-2 mt-1 border-t border-gray-100">
                    <button
                        class="flex items-center justify-center gap-1 w-full py-1.5 text-xs text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-colors"
                        @click="goToAll"
                    >
                        查看全部通知
                        <ExternalLink :size="11" />
                    </button>
                </div>
            </div>
        </template>
    </vort-popover>
</template>

<style>
.notification-popover-overlay.vort-popover {
    max-width: 420px;
    padding: 16px;
}
</style>
