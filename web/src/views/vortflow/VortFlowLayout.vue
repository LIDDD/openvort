<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute } from "vue-router";
import { useVortFlowStore } from "@/stores";
import VortFlowToolbar from "./components/VortFlowToolbar.vue";
import ViewSidebar from "./components/ViewSidebar.vue";
import { SYSTEM_VIEWS } from "./composables/useVortFlowViews";
import type { WorkItemType } from "@/components/vort-biz/work-item/WorkItemTable.types";

const store = useVortFlowStore();
const route = useRoute();

const sidebarPinned = ref(false);

// 工作墙也可应用系统视图（我负责的/我创建的等），独立持久化于 viewIdByType["wall"]
type SidebarTypeKey = WorkItemType | "wall";

const SIDEBAR_ROUTES: Record<string, SidebarTypeKey> = {
    "vortflow-stories": "需求",
    "vortflow-tasks": "任务",
    "vortflow-bugs": "缺陷",
    "vortflow-wall": "wall",
};

const currentSidebarTypeKey = computed<SidebarTypeKey | null>(() => {
    const name = route.name as string;
    return SIDEBAR_ROUTES[name] ?? null;
});

const showSidebar = computed(() => sidebarPinned.value && currentSidebarTypeKey.value !== null);

const currentViewId = computed(() => {
    if (!currentSidebarTypeKey.value) return "all";
    return store.getViewId(currentSidebarTypeKey.value);
});

const onSidebarSelect = (viewId: string) => {
    if (currentSidebarTypeKey.value) {
        store.setViewId(currentSidebarTypeKey.value, viewId);
    }
};

onMounted(() => {
    if (!store.projectsLoaded) {
        store.loadProjects();
    }
});
</script>

<template>
    <div class="space-y-4">
        <VortFlowToolbar />
        <div class="vortflow-content" :class="{ 'with-sidebar': showSidebar }">
            <ViewSidebar
                v-if="showSidebar"
                :views="SYSTEM_VIEWS"
                :selected-id="currentViewId"
                @select="onSidebarSelect"
                @unpin="sidebarPinned = false"
            />
            <div class="vortflow-main">
                <router-view />
            </div>
        </div>
    </div>
</template>

<style scoped>
.vortflow-content {
    display: flex;
    gap: 16px;
}
.vortflow-content.with-sidebar .vortflow-main {
    flex: 1;
    min-width: 0;
}
.vortflow-main {
    width: 100%;
}
</style>
