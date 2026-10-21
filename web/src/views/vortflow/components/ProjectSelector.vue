<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { Check, ChevronDown, ChevronRight, Layers, Loader2, Repeat, Star } from "lucide-vue-next";
import PopoverSelect from "@/components/vort-biz/popover-select/PopoverSelect.vue";
import { getVortflowIterations } from "@/api/vortflow";
import type { VortFlowProject } from "@/stores/modules/vortflow";

interface Props {
    projects: VortFlowProject[];
    selectedIds: string[];
}

const props = defineProps<Props>();

const emit = defineEmits<{
    "update:selectedIds": [value: string[]];
    "toggle-star": [id: string];
    "select-starred": [];
}>();

const router = useRouter();

const dropdownOpen = ref(false);
const searchKeyword = ref("");

const expandedProjectId = ref<string | null>(null);
const projectIterations = ref<Record<string, any[]>>({});
const loadingIterations = ref<Record<string, boolean>>({});
const loadedIterations = ref<Record<string, boolean>>({});
const iterationHasMore = ref<Record<string, boolean>>({});
const iterationLoadError = ref<Record<string, boolean>>({});
const iterationPages = ref<Record<string, number>>({});
const iterationRequestSeq = ref<Record<string, number>>({});

const iterStatusLabel: Record<string, string> = {
    planning: "规划中", active: "进行中", completed: "已完成",
};
const iterStatusColor: Record<string, string> = {
    planning: "#9ca3af", active: "#3b82f6", completed: "#22c55e",
};

const displayName = computed(() => {
    const ids = props.selectedIds;
    if (!ids.length) return "全部项目";
    if (ids.length === 1) {
        return props.projects.find(p => p.id === ids[0])?.name || "全部项目";
    }
    return `${ids.length} 个项目`;
});

const filteredProjects = computed(() => {
    const kw = searchKeyword.value.trim().toLowerCase();
    if (!kw) return props.projects;
    return props.projects.filter(p => p.name.toLowerCase().includes(kw));
});

const starredProjects = computed(() => filteredProjects.value.filter(p => p.is_starred));
const otherProjects = computed(() => filteredProjects.value.filter(p => !p.is_starred));
const hasStarred = computed(() => props.projects.some(p => p.is_starred));

const isSelected = (id: string) => props.selectedIds.includes(id);

const loadProjectIterations = async (projectId: string, reset = false) => {
    if (loadingIterations.value[projectId]) return;
    if (!reset && !iterationHasMore.value[projectId]) return;
    const page = reset ? 1 : (iterationPages.value[projectId] || 0) + 1;
    const seq = (iterationRequestSeq.value[projectId] || 0) + 1;
    iterationRequestSeq.value[projectId] = seq;
    if (reset) {
        projectIterations.value[projectId] = [];
        iterationPages.value[projectId] = 0;
        iterationHasMore.value[projectId] = false;
        loadedIterations.value[projectId] = false;
    }
    loadingIterations.value[projectId] = true;
    iterationLoadError.value[projectId] = false;
    try {
        const res: any = await getVortflowIterations({ project_id: projectId, page, page_size: 50 });
        if (iterationRequestSeq.value[projectId] !== seq) return;
        const items = ((res?.items || []) as any[]).map((item) => ({
            ...item,
            id: String(item.id || ""),
            name: String(item.name || item.id || ""),
        })).filter((item) => item.id && item.name);
        const merged = reset ? items : [...(projectIterations.value[projectId] || []), ...items];
        const seen = new Set<string>();
        projectIterations.value[projectId] = merged.filter((item) => {
            if (seen.has(item.id)) return false;
            seen.add(item.id);
            return true;
        });
        const rawTotal = typeof res?.total === "string" ? Number(res.total) : res?.total;
        const total = Number.isFinite(rawTotal) && rawTotal >= 0 ? Number(rawTotal) : undefined;
        iterationPages.value[projectId] = page;
        iterationHasMore.value[projectId] = total !== undefined
            ? projectIterations.value[projectId].length < total
            : items.length >= 50;
        loadedIterations.value[projectId] = true;
    } catch {
        if (iterationRequestSeq.value[projectId] === seq) {
            iterationLoadError.value[projectId] = true;
            loadedIterations.value[projectId] = true;
        }
    } finally {
        if (iterationRequestSeq.value[projectId] === seq) loadingIterations.value[projectId] = false;
    }
};

const toggleIterations = async (projectId: string, event: Event) => {
    event.stopPropagation();
    if (expandedProjectId.value === projectId) {
        expandedProjectId.value = null;
        return;
    }
    expandedProjectId.value = projectId;
    if (loadedIterations.value[projectId] && !iterationLoadError.value[projectId]) return;
    // 首屏失败时重新拉第一页；追加页失败时保留已有内容，重新展开后重试下一页。
    await loadProjectIterations(projectId, !projectIterations.value[projectId]?.length);
};

const handleIterationScroll = (projectId: string, event: Event) => {
    const target = event.currentTarget as HTMLElement | null;
    if (target && target.scrollHeight - target.scrollTop - target.clientHeight <= 24) {
        void loadProjectIterations(projectId);
    }
};

const selectIteration = (projectId: string, iterationId: string) => {
    dropdownOpen.value = false;
    router.push(`/vortflow/iterations/${iterationId}`);
};

// 勾选/取消勾选单个项目（多选）
const toggleProject = (id: string) => {
    const cur = props.selectedIds;
    const next = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id];
    emit("update:selectedIds", next);
};

// 选择「全部项目」= 清空多选范围
const selectAll = () => {
    emit("update:selectedIds", []);
    dropdownOpen.value = false;
};

const selectStarred = () => {
    emit("select-starred");
};

const toggleStar = (id: string, event: Event) => {
    event.stopPropagation();
    emit("toggle-star", id);
};

const goToBoard = () => {
    router.push("/vortflow/board");
};

// 面包屑「项目名」点击：恰好选中一个项目时进入其详情，否则回到看板
const goToProjectDetail = () => {
    if (props.selectedIds.length === 1) {
        router.push(`/vortflow/projects/${props.selectedIds[0]}`);
    } else {
        goToBoard();
    }
};

const formatDate = (dateStr?: string) => {
    if (!dateStr) return "";
    return dateStr.slice(0, 10);
};

const getWorkItemCount = (p: VortFlowProject) => {
    return (p.story_count ?? 0) + (p.task_count ?? 0) + (p.bug_count ?? 0);
};
</script>

<template>
    <div class="project-breadcrumb">
        <button type="button" class="breadcrumb-prefix" @click="goToBoard">
            <Layers :size="16" />
            <span>项目</span>
        </button>

        <span class="breadcrumb-sep">/</span>

        <button type="button" class="breadcrumb-name" @click="goToProjectDetail">
            {{ displayName }}
        </button>

        <PopoverSelect
            v-model:open="dropdownOpen"
            v-model:keyword="searchKeyword"
            :show-search="true"
            search-placeholder="搜索项目..."
            :dropdown-width="380"
            :dropdown-max-height="400"
            :bordered="false"
            placement="bottomLeft"
        >
            <template #trigger>
                <button
                    type="button"
                    class="breadcrumb-arrow"
                    :class="{ 'is-open': dropdownOpen }"
                    @click.stop="dropdownOpen = !dropdownOpen"
                >
                    <ChevronDown
                        :size="14"
                        :class="{ 'rotate-180': dropdownOpen }"
                    />
                </button>
            </template>

            <div class="py-1">
                <div
                    class="project-row"
                    :class="{ 'is-active': !props.selectedIds.length }"
                    @click.stop="selectAll"
                >
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center shrink-0">
                            <Layers :size="16" class="text-gray-400" />
                        </div>
                        <div class="min-w-0">
                            <div class="text-sm font-medium text-gray-800 truncate">全部项目</div>
                        </div>
                    </div>
                    <span v-if="!props.selectedIds.length" class="text-blue-500 text-sm shrink-0"><Check :size="15" /></span>
                </div>

                <button
                    v-if="hasStarred"
                    type="button"
                    class="quick-star-btn"
                    @click.stop="selectStarred"
                >
                    <Star :size="13" class="fill-amber-400 text-amber-400" />
                    <span>选中关注的项目</span>
                </button>

                <div v-if="filteredProjects.length" class="border-t border-gray-100 my-1" />

                <template v-if="starredProjects.length">
                    <div class="group-label">关注的项目</div>
                    <div v-for="project in starredProjects" :key="project.id">
                        <div
                            class="project-row"
                            :class="{ 'is-selected': isSelected(project.id) }"
                            @click.stop="toggleProject(project.id)"
                        >
                            <div class="flex items-center gap-3 min-w-0 flex-1">
                                <span class="checkbox" :class="{ 'is-checked': isSelected(project.id) }">
                                    <Check v-if="isSelected(project.id)" :size="12" />
                                </span>
                                <div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center shrink-0">
                                    <Layers :size="16" class="text-amber-500" />
                                </div>
                                <div class="min-w-0 flex-1">
                                    <div class="text-sm font-medium text-gray-800 truncate">{{ project.name }}</div>
                                    <div class="flex items-center gap-3 text-xs text-gray-400 mt-0.5">
                                        <span v-if="project.story_count != null">{{ project.story_count }} 需求</span>
                                        <span>{{ getWorkItemCount(project) }} 工作项</span>
                                        <span v-if="project.created_at">{{ formatDate(project.created_at) }}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-1 shrink-0">
                                <button
                                    type="button"
                                    class="star-btn is-starred"
                                    title="取消关注"
                                    @click.stop="toggleStar(project.id, $event)"
                                >
                                    <Star :size="14" class="fill-amber-400 text-amber-400" />
                                </button>
                                <button
                                    type="button"
                                    class="iter-expand-btn"
                                    :class="{ 'is-expanded': expandedProjectId === project.id }"
                                    @click.stop="toggleIterations(project.id, $event)"
                                >
                                    <Loader2 v-if="loadingIterations[project.id]" :size="14" class="animate-spin" />
                                    <ChevronRight v-else :size="14" />
                                </button>
                            </div>
                        </div>

                        <div v-if="expandedProjectId === project.id" class="iter-list" @scroll.passive="handleIterationScroll(project.id, $event)">
                            <template v-if="loadingIterations[project.id] && !projectIterations[project.id]?.length">
                                <div class="iter-empty">
                                    <Loader2 :size="14" class="animate-spin text-gray-300" />
                                    <span>加载中...</span>
                                </div>
                            </template>
                            <template v-else-if="projectIterations[project.id]?.length">
                                <div
                                    v-for="iter in projectIterations[project.id]"
                                    :key="iter.id"
                                    class="iter-row"
                                    @click.stop="selectIteration(project.id, iter.id)"
                                >
                                    <Repeat :size="13" class="text-gray-400 shrink-0" />
                                    <span class="iter-name">{{ iter.name }}</span>
                                    <span
                                        class="iter-status"
                                        :style="{ color: iterStatusColor[iter.status] || '#9ca3af' }"
                                    >{{ iterStatusLabel[iter.status] || iter.status }}</span>
                                </div>
                            </template>
                            <template v-else>
                                <div class="iter-empty">{{ iterationLoadError[project.id] ? '加载失败，请重新展开' : '暂无迭代' }}</div>
                            </template>
                        </div>
                    </div>
                    <div v-if="otherProjects.length" class="group-label">全部项目</div>
                </template>

                <div v-for="project in otherProjects" :key="project.id">
                    <div
                        class="project-row"
                        :class="{ 'is-selected': isSelected(project.id) }"
                        @click.stop="toggleProject(project.id)"
                    >
                        <div class="flex items-center gap-3 min-w-0 flex-1">
                            <span class="checkbox" :class="{ 'is-checked': isSelected(project.id) }">
                                <Check v-if="isSelected(project.id)" :size="12" />
                            </span>
                            <div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center shrink-0">
                                <Layers :size="16" class="text-amber-500" />
                            </div>
                            <div class="min-w-0 flex-1">
                                <div class="text-sm font-medium text-gray-800 truncate">{{ project.name }}</div>
                                <div class="flex items-center gap-3 text-xs text-gray-400 mt-0.5">
                                    <span v-if="project.story_count != null">{{ project.story_count }} 需求</span>
                                    <span>{{ getWorkItemCount(project) }} 工作项</span>
                                    <span v-if="project.created_at">{{ formatDate(project.created_at) }}</span>
                                </div>
                            </div>
                        </div>
                        <div class="flex items-center gap-1 shrink-0">
                            <button
                                type="button"
                                class="star-btn"
                                title="关注项目"
                                @click.stop="toggleStar(project.id, $event)"
                            >
                                <Star :size="14" />
                            </button>
                            <button
                                type="button"
                                class="iter-expand-btn"
                                :class="{ 'is-expanded': expandedProjectId === project.id }"
                                @click.stop="toggleIterations(project.id, $event)"
                            >
                                <Loader2 v-if="loadingIterations[project.id]" :size="14" class="animate-spin" />
                                <ChevronRight v-else :size="14" />
                            </button>
                        </div>
                    </div>

                    <div v-if="expandedProjectId === project.id" class="iter-list" @scroll.passive="handleIterationScroll(project.id, $event)">
                        <template v-if="loadingIterations[project.id] && !projectIterations[project.id]?.length">
                            <div class="iter-empty">
                                <Loader2 :size="14" class="animate-spin text-gray-300" />
                                <span>加载中...</span>
                            </div>
                        </template>
                        <template v-else-if="projectIterations[project.id]?.length">
                            <div
                                v-for="iter in projectIterations[project.id]"
                                :key="iter.id"
                                class="iter-row"
                                @click.stop="selectIteration(project.id, iter.id)"
                            >
                                <Repeat :size="13" class="text-gray-400 shrink-0" />
                                <span class="iter-name">{{ iter.name }}</span>
                                <span
                                    class="iter-status"
                                    :style="{ color: iterStatusColor[iter.status] || '#9ca3af' }"
                                >{{ iterStatusLabel[iter.status] || iter.status }}</span>
                            </div>
                        </template>
                        <template v-else>
                            <div class="iter-empty">{{ iterationLoadError[project.id] ? '加载失败，请重新展开' : '暂无迭代' }}</div>
                        </template>
                    </div>
                </div>

                <div v-if="!filteredProjects.length" class="px-4 py-6 text-center text-sm text-gray-400">
                    未找到匹配的项目
                </div>
            </div>
        </PopoverSelect>
    </div>
</template>

<style scoped>
.project-breadcrumb {
    display: inline-flex;
    align-items: center;
    gap: 0;
    font-size: 14px;
    white-space: nowrap;
}

.breadcrumb-prefix {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: 6px;
    color: #888;
    font-size: 14px;
    transition: color 0.2s, background 0.2s;
}

.breadcrumb-prefix:hover {
    color: var(--vort-primary, #1456f0);
    background: rgba(0, 0, 0, 0.04);
}

.breadcrumb-sep {
    color: #ccc;
    margin: 0 2px;
    user-select: none;
}

.breadcrumb-name {
    display: inline-flex;
    align-items: center;
    padding: 6px 8px;
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    color: #374151;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    transition: background 0.2s;
    margin-right: 6px;
}

.breadcrumb-name:hover {
    background: rgba(0, 0, 0, 0.04);
}

.breadcrumb-arrow {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: none;
    background: rgba(0, 0, 0, 0.04);
    cursor: pointer;
    border-radius: 4px;
    color: #aaa;
    transition: color 0.2s, background 0.2s;
}

.breadcrumb-arrow:hover,
.breadcrumb-arrow.is-open {
    color: var(--vort-primary, #1456f0);
    background: rgba(0, 0, 0, 0.08);
}

.breadcrumb-arrow svg {
    transition: transform 0.2s;
}

.project-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    margin: 0 4px;
    border-radius: 6px;
    cursor: pointer;
    transition: background-color 0.15s ease;
}

.project-row:hover {
    background: rgba(0, 0, 0, 0.04);
}

.project-row.is-active {
    background: #f1f5f9;
}

.project-row.is-selected {
    background: #eff6ff;
}

.checkbox {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border: 1.5px solid #cbd5e1;
    border-radius: 4px;
    color: #fff;
    flex-shrink: 0;
    transition: background 0.15s, border-color 0.15s;
}

.checkbox.is-checked {
    background: var(--vort-primary, #1456f0);
    border-color: var(--vort-primary, #1456f0);
}

.group-label {
    padding: 6px 12px 2px;
    margin: 0 4px;
    font-size: 11px;
    font-weight: 600;
    color: #9ca3af;
    letter-spacing: 0.02em;
}

.quick-star-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    width: calc(100% - 8px);
    margin: 2px 4px;
    padding: 6px 12px;
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: 6px;
    font-size: 12px;
    color: #6b7280;
    transition: background 0.15s;
}

.quick-star-btn:hover {
    background: rgba(0, 0, 0, 0.04);
}

.star-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: 4px;
    color: #cbd5e1;
    transition: color 0.15s, background 0.15s;
}

.star-btn:hover {
    color: #f59e0b;
    background: rgba(245, 158, 11, 0.1);
}

.star-btn.is-starred:hover {
    background: rgba(245, 158, 11, 0.1);
}

.iter-expand-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: 4px;
    color: #9ca3af;
    transition: color 0.15s, background 0.15s, transform 0.2s;
}

.iter-expand-btn:hover {
    color: #6b7280;
    background: rgba(0, 0, 0, 0.06);
}

.iter-expand-btn.is-expanded {
    color: var(--vort-primary, #1456f0);
}

.iter-expand-btn.is-expanded svg:not(.animate-spin) {
    transform: rotate(90deg);
}

.iter-list {
    padding: 2px 0 4px 0;
    margin: 0 4px;
    max-height: 220px;
    overflow-y: auto;
}

.iter-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px 6px 48px;
    border-radius: 5px;
    cursor: pointer;
    transition: background-color 0.15s;
    font-size: 12px;
}

.iter-row:hover {
    background: rgba(0, 0, 0, 0.04);
}

.iter-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #4b5563;
}

.iter-status {
    font-size: 11px;
    flex-shrink: 0;
}

.iter-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 12px 8px 48px;
    font-size: 12px;
    color: #9ca3af;
}

</style>
