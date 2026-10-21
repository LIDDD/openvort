import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import { compileScript, parse } from "@vue/compiler-sfc";
import ts from "typescript";
import { createRenderer, defineComponent, h, nextTick, reactive, ref } from "vue";

const require = createRequire(import.meta.url);
const sourceRoot = new URL("../src/", import.meta.url);
const originalId = "3947e85da3d6469ba9d1521a57acbd0d";
const newMember = { id: "7a6759d32ac54e8b8c3f28b4c6e19180", name: "新协作者" };

// 执行真实成员加载、后端行映射和保存逻辑，仅替换 HTTP 与消息提示。
function createHarness(members) {
    const requests = [];
    const updates = [];
    const warnings = [];
    let saveError;
    const update = async (id, patch) => {
        if (saveError) throw saveError;
        updates.push({ id, patch });
        return {};
    };
    const api = {
        async getMembersSimple(params) {
            requests.push(params);
            const start = (params.page - 1) * params.size;
            return { members: members.slice(start, start + params.size), total: members.length };
        },
        updateVortflowStory: update,
        updateVortflowTask: update,
        updateVortflowBug: update,
    };
    const cache = new Map();
    function load(url) {
        if (cache.has(url.href)) return cache.get(url.href);
        const { outputText } = ts.transpileModule(readFileSync(url, "utf8"), {
            compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
        });
        const exports = {};
        cache.set(url.href, exports);
        new Function("require", "exports", outputText)((id) => {
            if (id === "@/api") return api;
            if (id === "@openvort/vort-ui") {
                return { message: { warning: (text) => warnings.push(text), error: (text) => warnings.push(text) } };
            }
            if (id.startsWith("@/")) return load(new URL(`${id.slice(2)}.ts`, sourceRoot));
            if (id.startsWith(".")) return load(new URL(`${id}.ts`, url));
            return require(id);
        }, exports);
        return exports;
    }
    const common = load(new URL("views/vortflow/work-item/useWorkItemCommon.ts", sourceRoot)).useWorkItemCommon();
    const options = {
        ...common,
        useApi: ref(true),
        propType: "需求",
        getDescriptionTemplate: () => "",
        formatCnTime: (date) => date.toISOString(),
        apiProjects: ref([]),
        apiIterations: ref([]),
        dynamicVersionOptions: ref([]),
        itemRowsById: {},
        itemChildrenMap: {},
        expandedItemIds: {},
        pinnedRowsByType: { 需求: [], 任务: [], 缺陷: [] },
        tableRef: ref(null),
        createWorkItemRef: ref(null),
        dynamicTagOptions: ref([]),
        baseTagOptions: [],
        priorityModel: {},
        priorityScoreModel: {},
        tagsModel: {},
        collaboratorsModel: {},
        planTimeModel: {},
        normalizeDateValue: String,
    };
    const source = load(new URL("views/vortflow/composables/useWorkItemDataSource.ts", sourceRoot)).useWorkItemDataSource(options);
    const crud = load(new URL("views/vortflow/composables/useWorkItemCrud.ts", sourceRoot)).useWorkItemCrud(options);
    const inline = load(new URL("views/vortflow/work-item/useWorkItemInlineEdit.ts", sourceRoot)).useWorkItemInlineEdit({ ...options, ...crud });
    return {
        common, requests, updates, warnings, crud, inline,
        failSave: () => { saveError = new Error("保存失败"); },
        row: (ids = [originalId], type = "需求") => source.mapBackendItemToRow({
            id: "0e88a6", title: "客户黑名单功能", collaborators: ids, state: "pending_dev",
        }, type, 0),
    };
}

test("第一页之外的已有协作者可以正常切换，并按 ID 保存", async () => {
    const members = [
        newMember,
        ...Array.from({ length: 99 }, (_, index) => ({ id: `member-${index}`, name: `成员${index}` })),
        { id: originalId, name: "原协作者" },
    ];
    const app = createHarness(members);
    await app.common.loadMemberOptions();
    const row = app.row();
    await app.crud.handleDetailUpdate(row, { collaborators: [...row.collaborators, newMember.name] });
    assert.deepEqual(app.warnings, [], "不应因成员在第二页而报未识别的协作人");
    assert.deepEqual(row.collaborators, ["原协作者", newMember.name]);
    assert.deepEqual(app.updates[0]?.patch.collaborators, [originalId, newMember.id]);
    assert.equal(app.common.ownerGroups.value.some((group) => group.members.includes("原协作者")), true);
    const requestCount = app.requests.length;
    await app.common.loadMemberOptions();
    assert.equal(app.requests.length, requestCount, "成功加载的完整成员集合应复用缓存");
});

for (const type of ["需求", "任务", "缺陷"]) {
    for (const mode of ["详情", "列表"]) {
        test(`${type}${mode}：成员已不在通讯录时，仍可保留或移除原协作者并保存其他变更`, async () => {
            const app = createHarness([newMember]);
            await app.common.loadMemberOptions();
            const row = app.row([originalId], type);
            const save = (values) => mode === "详情"
                ? app.crud.handleDetailUpdate(row, { collaborators: values })
                : app.inline.setRowCollaborators(row, values);
            await save([...row.collaborators, newMember.name]);
            assert.deepEqual(app.warnings, [], "已有成员 ID 不应阻止切换其他协作者");
            assert.deepEqual(app.updates.at(-1)?.patch.collaborators, [originalId, newMember.id]);
            await save([newMember.name]);
            assert.deepEqual(app.updates.at(-1)?.patch.collaborators, [newMember.id]);
            await save([]);
            assert.deepEqual(app.updates.at(-1)?.patch.collaborators, []);
            const savedCount = app.updates.length;
            await save([originalId]);
            assert.equal(app.updates.length, savedCount, "移除后不能把失效 ID 当作新的有效成员添加");
        });
    }
}

test("已知成员的 ID 和姓名都能识别，未知姓名及新传入的未知 ID 仍被拒绝", async () => {
    const app = createHarness([newMember]);
    await app.common.loadMemberOptions();
    const row = app.row([]);
    await app.crud.handleDetailUpdate(row, { collaborators: [newMember.id] });
    assert.deepEqual(app.warnings, []);
    assert.deepEqual(app.updates.at(-1)?.patch.collaborators, [newMember.id]);
    for (const value of ["不存在的成员", originalId]) {
        const savedCount = app.updates.length;
        await app.crud.handleDetailUpdate(row, { collaborators: [value] });
        assert.equal(app.updates.length, savedCount);
        assert.match(app.warnings.at(-1), /未识别的协作人/);
    }
});

test("历史误存的姓名不能作为成员 ID 再次写入", async () => {
    const app = createHarness([newMember]);
    await app.common.loadMemberOptions();
    const row = app.row(["旧成员姓名"]);
    await app.crud.handleDetailUpdate(row, { collaborators: [...row.collaborators, newMember.name] });
    assert.equal(app.updates.length, 0);
    assert.match(app.warnings.at(-1), /旧成员姓名/);
});

test("列表保存失败时恢复原协作者，仍可识别原有成员 ID", async () => {
    const app = createHarness([newMember]);
    await app.common.loadMemberOptions();
    const row = app.row();
    app.failSave();
    await app.inline.setRowCollaborators(row, [newMember.name]);
    assert.deepEqual(row.collaborators, [originalId]);
    assert.deepEqual(app.inline.getRowCollaborators(row), [originalId]);
    assert.deepEqual(app.warnings, ["保存失败"]);
});

test("选择器展示不在候选列表中的已有协作者，允许手动移除", async (t) => {
    const filename = new URL("components/vort-biz/work-item/WorkItemMemberPicker.vue", sourceRoot);
    const { descriptor } = parse(readFileSync(filename, "utf8"), { filename: filename.pathname });
    const { content } = compileScript(descriptor, { id: "member-picker-test", inlineTemplate: true });
    const { outputText } = ts.transpileModule(content, {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    });
    const exports = {};
    const PopoverSelect = defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) });
    new Function("require", "exports", outputText)((id) => id.endsWith("PopoverSelect.vue")
        ? { default: PopoverSelect }
        : require(id), exports);
    const renderer = createRenderer({
        createElement: (type) => ({ type, children: [], props: {}, text: "" }),
        createText: (text) => ({ text }),
        createComment: (text) => ({ text }),
        setText: (node, text) => { node.text = text; },
        setElementText: (node, text) => { node.text = text; },
        patchProp: (node, key, _previous, value) => { node.props[key] = value; },
        insert: (node, parent) => { node.parent = parent; parent.children.push(node); },
        remove: (node) => { node.parent.children = node.parent.children.filter((child) => child !== node); },
        parentNode: (node) => node.parent,
        nextSibling: () => null,
    });
    const props = reactive({
        mode: "assignee", open: true, collaborators: [originalId, newMember.name],
        groups: [{ label: "企业成员", members: [newMember.name] }],
    });
    const events = [];
    const root = { children: [] };
    const app = renderer.createApp({ render: () => h(exports.default, {
        ...props,
        "onUpdate:collaborators": (value) => { props.collaborators = value; events.push(value); },
    }) });
    app.component("vort-checkbox", defineComponent({ render: () => h("input") }));
    app.mount(root);
    t.after(() => app.unmount());
    const descendants = (node) => [node, ...(node.children || []).flatMap(descendants)];
    const label = descendants(root).find((node) => node.text === originalId);
    assert.ok(label, "已有协作者不能因不在通讯录候选中而无法取消选择");
    const row = label.parent.parent;
    const removeButton = descendants(row).find((node) => node.type === "button" && node.text.trim() === "协作者");
    assert.ok(removeButton);
    removeButton.props.onClick({ stopPropagation() {} });
    await nextTick();
    assert.deepEqual(events, [[newMember.name]]);
    assert.equal(descendants(root).some((node) => node.text === originalId), false);
});
