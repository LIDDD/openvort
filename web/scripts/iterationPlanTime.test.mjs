import { resolveBugIterationPlanTime } from "../src/views/vortflow/work-item/iterationPlanTime.ts";

const iterations = [
    { id: "bug-iteration", name: "缺陷迭代", start_date: "2026-08-01T00:00:00", end_date: "2026-08-15T23:59:59" },
    { id: "end-only", name: "仅结束日期", start_date: "", end_date: "2026-09-30" },
    { id: "start-only", name: "仅开始日期", start_date: "2026-10-01", end_date: null },
    { id: "no-dates", name: "无日期" },
];

const fullRange = resolveBugIterationPlanTime("缺陷", "bug-iteration", iterations);
if (JSON.stringify(fullRange) !== JSON.stringify(["2026-08-01", "2026-08-15"])) {
    throw new Error(`缺陷迭代日期映射错误：${JSON.stringify(fullRange)}`);
}

const endOnlyRange = resolveBugIterationPlanTime("缺陷", "end-only", iterations);
if (JSON.stringify(endOnlyRange) !== JSON.stringify(["2026-09-30", "2026-09-30"])) {
    throw new Error(`缺少开始日期时未正确补齐：${JSON.stringify(endOnlyRange)}`);
}

const startOnlyRange = resolveBugIterationPlanTime("缺陷", "start-only", iterations);
if (JSON.stringify(startOnlyRange) !== JSON.stringify(["2026-10-01", "2026-10-01"])) {
    throw new Error(`缺少结束日期时未正确补齐：${JSON.stringify(startOnlyRange)}`);
}

if (resolveBugIterationPlanTime("缺陷", "no-dates", iterations) !== null) {
    throw new Error("迭代无日期时不应覆盖计划时间");
}
if (resolveBugIterationPlanTime("需求", "bug-iteration", iterations) !== null) {
    throw new Error("需求不应触发缺陷专属计划时间联动");
}
if (resolveBugIterationPlanTime("任务", "bug-iteration", iterations) !== null) {
    throw new Error("任务不应触发缺陷专属计划时间联动");
}
if (resolveBugIterationPlanTime("缺陷", "__unplanned__", iterations) !== null) {
    throw new Error("未规划迭代不应触发计划时间联动");
}

console.log("缺陷迭代计划时间联动回归测试通过");
