import { defineStore } from "pinia";
import { ref, computed } from "vue";
import {
    getVortflowProjects,
    starVortflowProject, unstarVortflowProject,
    getVortflowViews, createVortflowView, updateVortflowView, deleteVortflowView,
    getVortflowColumnSettings, saveVortflowColumnSettings,
} from "@/api";

export interface VortFlowProject {
    id: string;
    name: string;
    description?: string;
    owner_id?: string;
    created_at?: string;
    story_count?: number;
    task_count?: number;
    bug_count?: number;
    is_starred?: boolean;
}

export interface CustomView {
    id: string;
    name: string;
    scope: "personal" | "shared";
    visible: boolean;
    filters: Record<string, any>;
    columns: Array<{ key: string; visible: boolean }>;
    order: number;
    work_item_type?: string;
    owner_id?: string;
}

export interface PersistedColumnSetting {
    key: string;
    visible: boolean;
    width?: number;
}

export const useVortFlowStore = defineStore(
    "vortflow",
    () => {
        // 多选筛选范围（浏览/统计场景），空数组 = 全部项目
        const selectedProjectIds = ref<string[]>([]);
        // 单项目上下文（新建默认项目、迭代/版本归属、项目详情等强单项目场景）
        const activeProjectId = ref<string>("");
        const viewIdByType = ref<Record<string, string>>({});
        // 按项目记忆工作墙的迭代选择；key 为 projectId（""=全部项目时用 "__all__"）
        // value: ""=全部 / "__active__"=当前迭代(默认) / "__unplanned__"=未排期 / 具体迭代 id
        const iterationIdByProject = ref<Record<string, string>>({});
        const projects = ref<VortFlowProject[]>([]);
        const projectsLoaded = ref(false);
        const customViews = ref<CustomView[]>([]);
        const viewsLoaded = ref(false);
        const columnSettingsByType = ref<Record<string, PersistedColumnSetting[]>>({});
        const columnSettingsLoaded = ref(false);
        const tablePageSize = ref(20);
        const viewMode = ref<"list" | "gantt">("list");
        const ganttZoomLevel = ref<"day" | "week" | "month" | "quarter">("day");
        const ganttDividerRatio = ref(0.5);

        // 兼容别名：旧代码大量读取/写入 selectedProjectId，映射到 activeProjectId
        const selectedProjectId = computed<string>({
            get: () => activeProjectId.value,
            set: (id: string) => setProjectId(id),
        });

        const selectedProject = computed(() => {
            if (!activeProjectId.value) return null;
            return projects.value.find(p => p.id === activeProjectId.value) ?? null;
        });

        // 多选选中的项目对象列表（保持 projects 中的顺序）
        const selectedProjects = computed(() => {
            if (!selectedProjectIds.value.length) return [];
            const set = new Set(selectedProjectIds.value);
            return projects.value.filter(p => set.has(p.id));
        });

        const starredProjects = computed(() => projects.value.filter(p => p.is_starred));

        // 单项目选择：同时收敛多选范围（id 为空表示全部项目）
        const setProjectId = (id: string) => {
            activeProjectId.value = id;
            selectedProjectIds.value = id ? [id] : [];
        };

        // 多选设置：同步 activeProjectId，保证单项目场景始终有合理默认值
        const setSelectedProjectIds = (ids: string[]) => {
            const next = Array.from(new Set(ids.filter(Boolean)));
            selectedProjectIds.value = next;
            if (next.length === 1) {
                activeProjectId.value = next[0]!;
            } else if (next.length === 0) {
                activeProjectId.value = "";
            } else if (!next.includes(activeProjectId.value)) {
                activeProjectId.value = next[0]!;
            }
        };

        const toggleProjectId = (id: string) => {
            if (!id) {
                setSelectedProjectIds([]);
                return;
            }
            const cur = selectedProjectIds.value;
            setSelectedProjectIds(
                cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]
            );
        };

        const getViewId = (type: string): string => {
            return viewIdByType.value[type] || "all";
        };

        const setViewId = (type: string, viewId: string) => {
            viewIdByType.value = { ...viewIdByType.value, [type]: viewId };
        };

        const _iterKey = (projectId: string) => projectId || "__all__";

        const getIterationId = (projectId: string): string => {
            return iterationIdByProject.value[_iterKey(projectId)] ?? "__active__";
        };

        const setIterationId = (projectId: string, iterId: string) => {
            iterationIdByProject.value = {
                ...iterationIdByProject.value,
                [_iterKey(projectId)]: iterId,
            };
        };

        // ---- Views (API-backed) ----

        const loadViews = async (workItemType?: string) => {
            try {
                const res: any = await getVortflowViews(workItemType);
                const items = (res?.items || []) as any[];
                customViews.value = items.map((v: any) => ({
                    id: v.id,
                    name: v.name,
                    scope: v.scope || "personal",
                    visible: true,
                    filters: v.filters || {},
                    columns: v.columns || [],
                    order: v.order ?? 0,
                    work_item_type: v.work_item_type,
                    owner_id: v.owner_id,
                }));
                viewsLoaded.value = true;
            } catch {
                customViews.value = [];
            }
        };

        const addCustomView = async (view: Omit<CustomView, "id"> & { work_item_type: string }) => {
            try {
                const res: any = await createVortflowView({
                    name: view.name,
                    work_item_type: view.work_item_type,
                    scope: view.scope,
                    filters: view.filters,
                    columns: view.columns || [],
                });
                if (res?.id) {
                    customViews.value.push({
                        id: res.id,
                        name: res.name,
                        scope: res.scope || "personal",
                        visible: true,
                        filters: res.filters || {},
                        columns: res.columns || [],
                        order: res.order ?? 0,
                        work_item_type: res.work_item_type,
                        owner_id: res.owner_id,
                    });
                }
                return res;
            } catch {
                return null;
            }
        };

        const updateCustomViewApi = async (id: string, data: Partial<Omit<CustomView, "id">>) => {
            try {
                await updateVortflowView(id, {
                    name: data.name,
                    filters: data.filters,
                    columns: data.columns,
                    view_order: data.order,
                });
                const idx = customViews.value.findIndex(v => v.id === id);
                if (idx !== -1) {
                    customViews.value[idx] = { ...customViews.value[idx]!, ...data };
                }
            } catch { /* silent */ }
        };

        const deleteCustomViewApi = async (id: string) => {
            try {
                await deleteVortflowView(id);
                customViews.value = customViews.value.filter(v => v.id !== id);
            } catch { /* silent */ }
        };

        const reorderViews = (ids: string[]) => {
            const map = new Map(customViews.value.map(v => [v.id, v]));
            const reordered: CustomView[] = [];
            for (let i = 0; i < ids.length; i++) {
                const view = map.get(ids[i]!);
                if (view) reordered.push({ ...view, order: i });
            }
            for (const v of customViews.value) {
                if (!ids.includes(v.id)) reordered.push(v);
            }
            customViews.value = reordered;
        };

        const toggleViewVisibility = (id: string, visible: boolean) => {
            const idx = customViews.value.findIndex(v => v.id === id);
            if (idx !== -1) {
                customViews.value[idx] = { ...customViews.value[idx]!, visible };
            }
        };

        // ---- Column Settings (API-backed) ----

        const loadColumnSettings = async (workItemType?: string) => {
            try {
                const res: any = await getVortflowColumnSettings(workItemType);
                if (res && typeof res === "object") {
                    for (const [type, cols] of Object.entries(res)) {
                        columnSettingsByType.value[type] = cols as PersistedColumnSetting[];
                    }
                }
                columnSettingsLoaded.value = true;
            } catch { /* silent */ }
        };

        const getColumnSettings = (type: string): PersistedColumnSetting[] | null => {
            return columnSettingsByType.value[type] || null;
        };

        const setColumnSettings = async (type: string, settings: PersistedColumnSetting[]) => {
            columnSettingsByType.value = {
                ...columnSettingsByType.value,
                [type]: settings,
            };
            try {
                await saveVortflowColumnSettings({ work_item_type: type, columns: settings });
            } catch { /* silent */ }
        };

        // ---- Projects ----

        const loadProjects = async () => {
            try {
                const res: any = await getVortflowProjects();
                projects.value = (res?.items || []).map((p: any) => ({
                    id: p.id,
                    name: p.name,
                    description: p.description || "",
                    owner_id: p.owner_id,
                    created_at: p.created_at,
                    story_count: p.story_count ?? 0,
                    task_count: p.task_count ?? 0,
                    bug_count: p.bug_count ?? 0,
                    is_starred: p.is_starred ?? false,
                }));
                projectsLoaded.value = true;
            } catch {
                projects.value = [];
            }
        };

        // 星标 toggle（乐观更新 + 失败回滚）
        const toggleStar = async (id: string) => {
            const p = projects.value.find(x => x.id === id);
            if (!p) return;
            const next = !p.is_starred;
            p.is_starred = next;
            try {
                if (next) await starVortflowProject(id);
                else await unstarVortflowProject(id);
            } catch {
                p.is_starred = !next;
            }
        };

        // 选中我关注的全部项目作为多选范围
        const selectStarredProjects = () => {
            setSelectedProjectIds(projects.value.filter(p => p.is_starred).map(p => p.id));
        };

        return {
            selectedProjectId, selectedProjectIds, activeProjectId,
            viewIdByType, iterationIdByProject, projects, projectsLoaded,
            customViews, viewsLoaded, columnSettingsByType, columnSettingsLoaded, tablePageSize,
            viewMode, ganttZoomLevel, ganttDividerRatio,
            selectedProject, selectedProjects, starredProjects,
            setProjectId, setSelectedProjectIds, toggleProjectId,
            toggleStar, selectStarredProjects,
            getViewId, setViewId, getIterationId, setIterationId, loadProjects,
            loadViews, addCustomView,
            updateCustomView: updateCustomViewApi,
            deleteCustomView: deleteCustomViewApi,
            reorderViews, toggleViewVisibility,
            loadColumnSettings, getColumnSettings, setColumnSettings,
        };
    },
    {
        persist: {
            pick: ["selectedProjectIds", "activeProjectId", "viewIdByType", "iterationIdByProject", "columnSettingsByType", "customViews", "tablePageSize", "viewMode", "ganttZoomLevel", "ganttDividerRatio"],
        },
    }
);
