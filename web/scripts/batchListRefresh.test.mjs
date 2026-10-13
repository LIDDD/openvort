import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../src/views/vortflow/", import.meta.url);
const tableSource = readFileSync(
    fileURLToPath(new URL("WorkItemTable.vue", root)),
    "utf8",
);
const proTableSource = readFileSync(
    fileURLToPath(new URL("../../components/vort-biz/pro-table/ProTable.vue", root)),
    "utf8",
);

// 批量编辑成功后必须走表格实例的刷新方法；仅递增 refreshKey 依赖子组件
// 的深度 watch，无法保证当前请求已经完成，容易把旧行留在屏幕上。
const batchBlock = tableSource.match(/<BatchPropertyEditor[\s\S]*?\/>/u)?.[0] || "";
if (!batchBlock) {
    throw new Error("找不到 BatchPropertyEditor 挂载节点");
}
if (!/@done\s*=\s*"[^"]*handleBatchDone[^"]*"/u.test(batchBlock)) {
    throw new Error("批量完成事件没有绑定 handleBatchDone 回调");
}

const handler = tableSource.match(
    /const\s+handleBatchDone\s*=\s*async\s*\(\)\s*=>\s*\{([\s\S]*?)\n\};/u,
)?.[1] || "";
if (!/clearSelection\s*\(\)/u.test(handler)) {
    throw new Error("handleBatchDone 未清理选中行");
}
if (!/await\s+[^;]*tableRef\.value\?\.refresh\?\.\(\)/u.test(handler)) {
    throw new Error("handleBatchDone 未等待 tableRef.refresh 完成");
}

// ProTable 暴露的 refresh 必须返回 fetchData Promise，父层才能等待刷新完成。
const refreshFunction = proTableSource.match(
    /const\s+handleRefresh\s*=\s*(?:async\s*)?\(\)\s*=>\s*\{([\s\S]*?)\n\};/u,
)?.[1] || "";
if (!/await\s+fetchData\s*\(\)|return\s+fetchData\s*\(\)/u.test(refreshFunction)) {
    throw new Error("ProTable.handleRefresh 未返回/等待 fetchData Promise");
}

// 最小异步时序模型：若回调没有 await refresh，回调返回时行数据仍是旧值；
// 正确实现必须在回调完成前观察到服务端的新状态。
const serverRows = [{ id: "story-1", status: "测试完成" }];
let visibleRows = serverRows.map((row) => ({ ...row }));
let selectionCleared = false;

const tableRef = {
    async refresh() {
        await new Promise((resolve) => setTimeout(resolve, 5));
        visibleRows = serverRows.map((row) => ({ ...row }));
    },
};

const handleBatchDone = async () => {
    selectionCleared = true;
    await tableRef.refresh();
};

serverRows[0].status = "已完成";
await handleBatchDone();
if (!selectionCleared || visibleRows[0]?.status !== "已完成") {
    throw new Error(`批量完成后列表未同步：${JSON.stringify(visibleRows)}`);
}

console.log("批量修改后列表刷新回归测试通过");
