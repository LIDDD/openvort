import { fetchAllPages } from "../src/api/iterationOptions.ts";

// 模拟迭代接口：目标迭代位于第二页，验证下拉选项会继续拉取后续页。
const target = { id: "d1167", name: "D1167-pointsMall" };
const pages = [
    Array.from({ length: 100 }, (_, index) => ({ id: `iter-${index}`, name: `迭代${index}` })),
    [target],
];
const calls = [];

const result = await fetchAllPages(
    async (page, pageSize) => {
        calls.push({ page, pageSize });
        return { items: pages[page - 1] || [], total: 101 };
    },
    { pageSize: 100, maxPageSize: 200 },
);

if (!result.items.some((item) => item.id === target.id)) {
    throw new Error("分页迭代选项缺少 D1167-pointsMall");
}
if (calls.length !== 2 || calls[1]?.page !== 2) {
    throw new Error(`未继续拉取第二页：${JSON.stringify(calls)}`);
}

// total 已知时，即便中间页不足 pageSize，也不能提前停止。
const sparseCalls = [];
const sparseResult = await fetchAllPages(
    async (page, pageSize) => {
        sparseCalls.push({ page, pageSize });
        const sparsePages = [[{ id: "a", name: "A" }], [{ id: "b", name: "B" }, { id: "c", name: "C" }]];
        return { items: sparsePages[page - 1] || [], total: 3 };
    },
    { pageSize: 2 },
);
if (sparseResult.items.length !== 3 || sparseCalls.length !== 2) {
    throw new Error("total 已知时不应因中间短页提前停止");
}

console.log("迭代选项分页回归测试通过");
