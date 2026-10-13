import { ref, type Ref } from "vue";
import {
    getVortflowProjects,
    getVortflowVersions,
    getVortgitRepos,
    getVortgitRepoBranches,
} from "@/api";
import type { RowItem } from "@/components/vort-biz/work-item/WorkItemTable.types";

interface NamedOption {
    id: string;
    name: string;
    /** 迭代选项附带的日期，用于缺陷计划时间联动。 */
    start_date?: string;
    end_date?: string;
}

export interface UseWorkItemDetailFieldOptionsOptions {
    /** 当前打开的工作项 */
    record: Ref<RowItem | null>;
}

/**
 * 工作项详情面板「字段下拉选项」加载与同步。
 *
 * 抽离自 WorkItemDetail.vue 阶段 D3b：
 * - 项目 / 迭代 / 版本 / 仓库 / 分支选项 ref
 * - 迭代由详情里的选择器按用户打开/搜索/翻页懒加载；切项目时仅刷新版本/仓库
 * - 切仓库时联动重新加载分支（loadBranchOptions）
 * - 显示标签同步（syncDetailLinkedLabels / syncDetailRepoLabel）
 * - 通用日期格式化（formatDate / normalizeDateValue）
 *
 * 字段编辑器 computed（detailPlanTimeModel/detailProjectName/...）仍留在主组件，
 * 因为它们与 emit/appendDetailLog 强耦合；这里只把"远程数据 + 工具"集中。
 */
export function useWorkItemDetailFieldOptions(opts: UseWorkItemDetailFieldOptionsOptions) {
    const apiProjects = ref<NamedOption[]>([]);
    const apiIterations = ref<NamedOption[]>([]);
    const apiVersions = ref<NamedOption[]>([]);
    const apiRepos = ref<NamedOption[]>([]);
    const apiBranches = ref<Array<{ name: string }>>([]);
    const branchLoading = ref(false);

    const formatDate = (value: Date) => {
        const y = value.getFullYear();
        const m = String(value.getMonth() + 1).padStart(2, "0");
        const d = String(value.getDate()).padStart(2, "0");
        return `${y}-${m}-${d}`;
    };

    const normalizeDateValue = (value: unknown): string => {
        if (value instanceof Date) return formatDate(value);
        if (typeof value === "string") {
            const direct = value.trim();
            if (!direct) return "";
            if (/^\d{4}-\d{2}-\d{2}$/.test(direct)) return direct;
            const parsed = new Date(direct);
            if (!Number.isNaN(parsed.getTime())) return formatDate(parsed);
        }
        return "";
    };

    const loadBranchOptions = async (repoId?: string) => {
        if (!repoId) {
            apiBranches.value = [];
            return;
        }
        branchLoading.value = true;
        try {
            const res: any = await getVortgitRepoBranches(repoId);
            apiBranches.value = ((res?.items || []) as any[])
                .map((item) => ({ name: String(item.name || "") }))
                .filter((item) => item.name);
        } catch {
            apiBranches.value = [];
        } finally {
            branchLoading.value = false;
        }
    };

    const syncDetailLinkedLabels = () => {
        const rec = opts.record.value;
        if (!rec) return;
        if (rec.iterationId && !rec.iteration) {
            rec.iteration = apiIterations.value.find((item) => item.id === rec.iterationId)?.name || "";
        }
        if (rec.versionId && !rec.version) {
            rec.version = apiVersions.value.find((item) => item.id === rec.versionId)?.name || "";
        }
    };

    const syncDetailRepoLabel = () => {
        const rec = opts.record.value;
        if (!rec) return;
        if (rec.repoId) {
            rec.repo = apiRepos.value.find((item) => item.id === rec.repoId)?.name || rec.repo || "";
        }
    };

    const mapNamed = (items: any[]): NamedOption[] =>
        items.map((p: any) => ({ id: String(p.id), name: String(p.name || p.id) }));

    const mapRepo = (items: any[]): NamedOption[] =>
        items.map((item: any) => ({
            id: String(item.id || ""),
            name: String(item.name || item.full_name || item.id || ""),
        })).filter((item) => item.id && item.name);

    const resetIterationOptions = () => {
        apiIterations.value = [];
    };

    const mergeIterationOptions = (items: Array<{ id: string; name: string; [key: string]: unknown }>) => {
        const merged = new Map(apiIterations.value.map((item) => [item.id, item]));
        for (const item of items || []) {
            const id = String(item?.id || "");
            const name = String(item?.name || "");
            if (!id || !name) continue;
            const previous = merged.get(id);
            const startDate = item.start_date == null || item.start_date === ""
                ? previous?.start_date || ""
                : String(item.start_date);
            const endDate = item.end_date == null || item.end_date === ""
                ? previous?.end_date || ""
                : String(item.end_date);
            merged.set(id, { id, name, start_date: startDate, end_date: endDate });
        }
        apiIterations.value = [...merged.values()];
        syncDetailLinkedLabels();
    };

    const loadFieldOptions = async () => {
        // 记录切换时清除旧项目迭代缓存，新的迭代候选等用户打开下拉后再请求。
        resetIterationOptions();
        const projectId = opts.record.value?.projectId || "";
        const [projRes, verRes, repoRes] = await Promise.allSettled([
            getVortflowProjects(),
            projectId ? getVortflowVersions({ project_id: projectId, page: 1, page_size: 100 }) : Promise.resolve({ items: [] }),
            projectId ? getVortgitRepos({ project_id: projectId, page: 1, page_size: 100 }) : Promise.resolve({ items: [] }),
        ]);
        if (projRes.status === "fulfilled") {
            apiProjects.value = mapNamed(((projRes.value as any)?.items || []));
        }
        if (verRes.status === "fulfilled") {
            apiVersions.value = mapNamed(((verRes.value as any)?.items || []));
        }
        if (repoRes.status === "fulfilled") {
            apiRepos.value = mapRepo(((repoRes.value as any)?.items || []));
        }
        syncDetailLinkedLabels();
        syncDetailRepoLabel();
        await loadBranchOptions(opts.record.value?.repoId || "");
    };

    const loadProjectLinkedOptions = async (projectId?: string) => {
        const pid = projectId || opts.record.value?.projectId || "";
        resetIterationOptions();
        if (!pid) {
            apiVersions.value = [];
            apiRepos.value = [];
            apiBranches.value = [];
            return;
        }
        const [verRes, repoRes] = await Promise.allSettled([
            getVortflowVersions({ project_id: pid, page: 1, page_size: 100 }),
            getVortgitRepos({ project_id: pid, page: 1, page_size: 100 }),
        ]);
        if (verRes.status === "fulfilled") {
            apiVersions.value = mapNamed(((verRes.value as any)?.items || []));
        }
        if (repoRes.status === "fulfilled") {
            apiRepos.value = mapRepo(((repoRes.value as any)?.items || []));
        }
        syncDetailLinkedLabels();
        syncDetailRepoLabel();
        await loadBranchOptions(opts.record.value?.repoId || "");
    };

    return {
        apiProjects,
        apiIterations,
        apiVersions,
        apiRepos,
        apiBranches,
        branchLoading,
        formatDate,
        normalizeDateValue,
        loadBranchOptions,
        mergeIterationOptions,
        resetIterationOptions,
        loadFieldOptions,
        loadProjectLinkedOptions,
        syncDetailLinkedLabels,
        syncDetailRepoLabel,
    };
}
