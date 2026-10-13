<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useVortFlowStore } from "@/stores";
import ProjectSelector from "./ProjectSelector.vue";

const route = useRoute();
const store = useVortFlowStore();

const shouldHideToolbar = computed(() =>
    route.name === "vortflow-board" || route.name === "vortflow-settings"
);
</script>

<template>
    <div v-if="!shouldHideToolbar" class="bg-white rounded-xl px-4 py-3 flex items-center gap-4">
        <ProjectSelector
            :projects="store.projects"
            :selected-ids="store.selectedProjectIds"
            @update:selected-ids="store.setSelectedProjectIds"
            @toggle-star="store.toggleStar"
            @select-starred="store.selectStarredProjects"
        />
    </div>
</template>
