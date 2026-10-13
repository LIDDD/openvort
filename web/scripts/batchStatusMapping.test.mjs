import { readFileSync } from "node:fs";
import { resolveBatchStatusState } from "../src/views/vortflow/work-item/batchStatusMapping.ts";

const componentSource = readFileSync(
    new URL("../src/views/vortflow/components/BatchPropertyEditor.vue", import.meta.url),
    "utf8",
);

// 回归约束：批量状态映射必须把每一行的工作项类型传给 mapper，
// 不能退化成旧的 getBackendStatesByDisplayStatus(val) 漏参调用。
if (!/resolveBatchStatusState\(\s*row\.type/.test(componentSource)) {
    throw new Error("批量状态编辑未按 row.type 调用状态映射 helper");
}
if (/getBackendStatesByDisplayStatus\(\s*val\s*\)/.test(componentSource)) {
    throw new Error("批量状态编辑仍存在漏传工作项类型的状态映射调用");
}

const calls = [];
const resolver = (type, status) => {
    calls.push([type, status]);
    const map = {
        需求: { "已完成": ["done"], "已取消": ["rejected"] },
        任务: { "已完成": ["done"], "已取消": ["closed"] },
        缺陷: { "已完成": ["resolved"] },
    };
    return map[type]?.[status];
};

const storyDone = resolveBatchStatusState("需求", "已完成", resolver);
if (storyDone !== "done") {
    throw new Error(`需求状态映射错误：${storyDone}`);
}
if (JSON.stringify(calls[0]) !== JSON.stringify(["需求", "已完成"])) {
    throw new Error(`状态映射参数顺序错误：${JSON.stringify(calls[0])}`);
}

const taskCanceled = resolveBatchStatusState("任务", { value: "已取消", label: "已取消" }, resolver);
if (taskCanceled !== "closed") {
    throw new Error(`对象形式状态映射错误：${taskCanceled}`);
}

if (resolveBatchStatusState("需求", "待确认", resolver) !== null) {
    throw new Error("类型不支持的状态应安全返回空映射");
}
if (resolveBatchStatusState("需求", { label: "已完成" }, resolver) !== "done") {
    throw new Error("仅含 label 的状态对象应可安全映射");
}
if (resolveBatchStatusState("需求", { value: { nested: true } }, resolver) !== null) {
    throw new Error("非标量状态值不应被强制转换为 [object Object]");
}

console.log("批量状态映射回归测试通过");
