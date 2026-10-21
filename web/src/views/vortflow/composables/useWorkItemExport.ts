import { message } from "@openvort/vort-ui";
import type { RowItem } from "@/components/vort-biz/work-item/WorkItemTable.types";
import type { Ref } from "vue";

export interface UseWorkItemExportOptions {
    selectedRows: Ref<RowItem[]>;
    // Rows currently rendered on the table page. Used when no rows are selected
    // so the export matches what the user sees (not a stale cross-page cache).
    getCurrentPageRows: () => RowItem[];
}

export function useWorkItemExport(options: UseWorkItemExportOptions) {
    const { selectedRows, getCurrentPageRows } = options;

    const getExportData = (): RowItem[] => {
        if (selectedRows.value.length > 0) return selectedRows.value;
        return getCurrentPageRows();
    };

    const downloadFile = (content: string, filename: string, type: string) => {
        const bom = type.includes("csv") ? "\uFEFF" : "";
        const blob = new Blob([bom + content], { type });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    };

    // CSV cell escape: wrap in quotes and double inner quotes; newlines/commas are safe inside quotes.
    const csvCell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;

    // Notify whether we exported the user selection or only the currently loaded page.
    const notifyExportedCount = (count: number) => {
        if (selectedRows.value.length > 0) {
            message.success(`已导出选中 ${count} 条数据`);
        } else {
            message.success(`已导出当前页 ${count} 条数据`);
        }
    };

    const handleExportCsv = () => {
        const rows = getExportData();
        if (!rows.length) { message.warning("暂无数据可导出"); return; }
        const headers = ["项目", "迭代", "版本", "工作编号", "标题", "类型", "状态", "优先级", "负责人", "创建人", "标签", "协作者", "创建时间", "计划开始", "计划结束"];
        const csvRows = rows.map(r => [
            r.projectName || "", r.iteration || "", r.version || "",
            r.workNo || "", r.title || "", r.type || "",
            r.status || "", r.priority || "", r.owner || "", r.creator || "",
            (r.tags || []).join(";"), (r.collaborators || []).join(";"),
            r.createdAt || "", r.planTime?.[0] || "", r.planTime?.[1] || "",
        ].map(csvCell).join(","));
        downloadFile([headers.map(csvCell).join(","), ...csvRows].join("\n"), `工作项导出_${new Date().toISOString().slice(0, 10)}.csv`, "text/csv;charset=utf-8");
        notifyExportedCount(rows.length);
    };

    const handleExportExcel = () => {
        handleExportCsv();
        message.info("已导出为 CSV 格式，可使用 Excel 打开");
    };

    const handleExportJson = () => {
        const rows = getExportData();
        if (!rows.length) { message.warning("暂无数据可导出"); return; }
        const data = rows.map(r => ({
            projectName: r.projectName || "",
            iteration: r.iteration || "",
            version: r.version || "",
            workNo: r.workNo, title: r.title, type: r.type, status: r.status,
            priority: r.priority, owner: r.owner, creator: r.creator,
            tags: r.tags, collaborators: r.collaborators, createdAt: r.createdAt,
            planTimeStart: r.planTime?.[0] || "", planTimeEnd: r.planTime?.[1] || "",
            description: r.description || "",
        }));
        downloadFile(JSON.stringify(data, null, 2), `工作项导出_${new Date().toISOString().slice(0, 10)}.json`, "application/json;charset=utf-8");
        notifyExportedCount(rows.length);
    };

    return {
        getExportData,
        handleExportCsv,
        handleExportExcel,
        handleExportJson,
    };
}
