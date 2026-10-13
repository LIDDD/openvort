import { compareWorkItemDate } from "../src/views/vortflow/work-item/workItemSort.ts";

// 模拟“创建人筛选后再按创建时间倒序”的最小数据：展示字符串会把 8 月 6 日排在 8 月 26 日前。
const rows = [
    {
        id: "aug-26",
        createdAt: "8月26日 09:47",
        _createdAtRaw: "2026-08-26T09:47:47.549053",
    },
    {
        id: "aug-6",
        createdAt: "8月6日 15:14",
        _createdAtRaw: "2026-08-06T15:14:02.057750",
    },
];

const sorted = [...rows].sort((a, b) =>
    compareWorkItemDate(a, b, "_createdAtRaw", "createdAt", "descend")
);

if (sorted[0]?.id !== "aug-26") {
    throw new Error(`创建时间倒序错误：${sorted.map((row) => row.id).join(",")}`);
}

const ascending = [...rows].sort((a, b) =>
    compareWorkItemDate(a, b, "_createdAtRaw", "createdAt", "ascend")
);

if (ascending[0]?.id !== "aug-6") {
    throw new Error(`创建时间升序错误：${ascending.map((row) => row.id).join(",")}`);
}

console.log("创建人筛选后的创建时间排序回归测试通过");
