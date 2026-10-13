import { resolveProjectIdFromScope } from "../src/views/vortflow/work-item/projectScope.ts";

const cases = [
    { name: "单项目自动回填", ids: ["project-a"], explicit: "", expected: "project-a" },
    { name: "多项目保持空白", ids: ["project-a", "project-b"], explicit: "", expected: "" },
    { name: "全部项目保持空白", ids: [], explicit: "", expected: "" },
    { name: "重复项目仍按单项目处理", ids: ["project-a", "project-a"], explicit: "", expected: "project-a" },
    { name: "显式项目优先于筛选范围", ids: ["project-a", "project-b"], explicit: "child-project", expected: "child-project" },
];

for (const item of cases) {
    const actual = resolveProjectIdFromScope(item.ids, item.explicit);
    if (actual !== item.expected) {
        throw new Error(`${item.name}失败：期望 ${item.expected || "空"}，实际 ${actual || "空"}`);
    }
}

console.log("项目默认回填范围回归测试通过");
