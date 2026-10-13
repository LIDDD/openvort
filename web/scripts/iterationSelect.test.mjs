import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import { compileScript, parse } from "@vue/compiler-sfc";
import ts from "typescript";
import { createRenderer, defineComponent, h, nextTick, reactive } from "vue";

// 编译真实选择器，保留 Vue 响应式、模板和事件链，只替换接口与底层 Select。
const filename = new URL("../src/components/vort-biz/work-item/IterationSelect.vue", import.meta.url);
const { descriptor } = parse(readFileSync(filename, "utf8"), { filename: filename.pathname });
const { content } = compileScript(descriptor, { id: "iteration-select-test", inlineTemplate: true });
const { outputText } = ts.transpileModule(content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const require = createRequire(import.meta.url);
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

const flush = async () => {
    await new Promise((resolve) => setImmediate(resolve));
    await nextTick();
};

function mountSelect(t, initialProps, overrides = {}) {
    const detailCalls = [];
    const listCalls = [];
    const optionsEvents = [];
    const changeEvents = [];
    let selectProps;
    let selectEmit;
    const api = {
        async getVortflowIteration(id) {
            detailCalls.push(id);
            return overrides.detail ? overrides.detail(id) : { id, name: "D0133-bugfix" };
        },
        async getVortflowIterations(params) {
            listCalls.push(params);
            return overrides.list ? overrides.list(params) : { items: [], total: 0 };
        },
    };
    const Select = defineComponent({
        props: ["modelValue", "options"],
        emits: ["update:modelValue", "change", "focus", "blur", "search"],
        setup(props, { emit }) {
            selectProps = props;
            selectEmit = emit;
            return () => h("span", props.options.find((option) => option.value === props.modelValue)?.label || "");
        },
    });
    const module = { exports: {} };
    new Function("require", "exports", outputText)((id) => {
        if (id === "@/api/vortflow") return api;
        if (id === "@openvort/vort-ui") return { Select };
        return require(id);
    }, module.exports);
    const props = reactive({ ...initialProps });
    const root = { children: [] };
    const app = renderer.createApp({
        render: () => h(module.exports.default, {
            ...props,
            "onUpdate:modelValue": (value) => { props.modelValue = value; },
            onChange: (...args) => { changeEvents.push(args); },
            onOptionsChange: (options) => { optionsEvents.push(options); },
        }),
    });
    app.mount(root);
    t.after(() => app.unmount());
    return {
        props, detailCalls, listCalls, optionsEvents, changeEvents,
        text: () => root.children[0].children[0].text,
        options: () => selectProps.options,
        open: () => root.children[0].props.onMousedownCapture(),
        emit: (...args) => selectEmit(...args),
        unmount: () => app.unmount(),
    };
}

const iterationId = "47ea6258ff2642e29ebef4c44c8a2642";

test("新建表单仅带入迭代 ID 时，无须展开下拉就显示名称", async (t) => {
    const view = mountSelect(t, { modelValue: iterationId, selectedLabel: iterationId, projectId: "project-1" });
    await flush();
    assert.equal(view.text(), "D0133-bugfix");
    assert.equal(view.props.modelValue, iterationId, "回显不能改变关联的迭代 ID");
    assert.deepEqual(view.detailCalls, [iterationId]);
    assert.equal(view.listCalls.length, 0, "回显不应提前加载分页列表");
    assert.deepEqual(view.changeEvents, [], "名称补齐不能模拟手动选择");
});

test("当前迭代不在第一页时，展开后仍显示名称", async (t) => {
    const view = mountSelect(t, { modelValue: iterationId }, {
        list: () => ({ items: [{ id: "another", name: "其他迭代" }], total: 101 }),
    });
    await flush();
    view.open();
    await flush();
    assert.equal(view.text(), "D0133-bugfix");
    assert.equal(view.listCalls.length, 1);
    assert.equal(view.listCalls[0].page, 1);
});

test("已知名称、未选择和静态模式不会额外请求", async (t) => {
    for (const props of [
        { modelValue: iterationId, selectedLabel: "已知迭代" },
        { modelValue: "" },
        { modelValue: "__unplanned__" },
        { modelValue: "Sprint 1", useApi: false, staticOptions: [{ id: "Sprint 1", name: "静态迭代" }] },
    ]) {
        const view = mountSelect(t, props);
        await flush();
        assert.deepEqual(view.detailCalls, []);
        assert.deepEqual(view.listCalls, []);
        if (props.selectedLabel) assert.equal(view.text(), props.selectedLabel);
        if (props.staticOptions) assert.equal(view.text(), "静态迭代");
    }
});
