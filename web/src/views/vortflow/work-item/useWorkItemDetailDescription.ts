import { computed, type ComputedRef, type Ref } from "vue";
import { useInlineAi } from "@/hooks";
import type { RowItem } from "@/components/vort-biz/work-item/WorkItemTable.types";

export interface UseWorkItemDetailDescriptionOptions {
    /** 当前打开的工作项 */
    record: Ref<RowItem | null>;
    /** 描述编辑模式开关；从 props.initialDescEditing 派生，需要支持外部 defineExpose */
    detailDescEditing: Ref<boolean>;
    /** 描述编辑草稿；从 props.initialDescDraft 派生，需要支持外部 defineExpose */
    detailDescDraft: Ref<string>;
    /** 描述保存后通过 emit 通知父级（保持原 emit 形态） */
    onUpdateDescription: (description: string) => void;
    /** 描述变化时同步追加日志（与 useWorkItemDetailActivityLog.appendDetailLog 同源） */
    appendDetailLog: (action: string, detail?: any) => void;
    /** 把 record.type 转换成后端 entity_type；buildSupplementPrompt 用 */
    getEntityType: () => string;
}

/**
 * 工作项详情面板「描述编辑 + AI 增强」相关状态与操作。
 *
 * 抽离自 WorkItemDetail.vue 阶段 D2：
 * - 描述编辑器开关与保存/取消
 * - AI 完善描述（descAi、startAiEnrichDesc、applyAiDesc）
 * - AI 描述提示词构造（按需求/任务/缺陷分类的 structure 模板）
 * - AI 字段补全提示词（buildSupplementPrompt，由 AI 助手按钮 prompt 注入）
 *
 * detailDescEditing / detailDescDraft 仍在主组件创建并通过 props 传入，
 * 这样 defineExpose 与 props.initialDescEditing/Draft 的语义保持不变。
 */
export function useWorkItemDetailDescription(opts: UseWorkItemDetailDescriptionOptions) {
    const descAi = useInlineAi({ sessionName: "描述完善助手" });

    const descAiPhaseLabel = computed(() => {
        switch (descAi.phase.value) {
            case "thinking": return "思考中";
            case "tool_running": return "正在查询项目信息";
            case "generating": return "生成中";
            default: return "处理中";
        }
    });

    const aiEnrichBtnLabel = computed(() => {
        const type = opts.record.value?.type || "需求";
        return `AI 完善${type}描述`;
    });

    const openDetailDescEditor = () => {
        opts.detailDescDraft.value = opts.record.value?.description || "";
        opts.detailDescEditing.value = true;
    };

    const saveDetailDescEditor = () => {
        const rec = opts.record.value;
        if (!rec) return;
        const oldDesc = rec.description || "";
        const newDesc = opts.detailDescDraft.value;
        rec.description = newDesc;
        opts.detailDescEditing.value = false;
        opts.appendDetailLog("updated", { description: { from: oldDesc, to: newDesc } });
        opts.onUpdateDescription(newDesc);
    };

    const cancelDetailDescEditor = () => {
        opts.detailDescEditing.value = false;
        opts.detailDescDraft.value = "";
        descAi.clear();
    };

    const extractImageRefs = (content: string): string[] => {
        const images: string[] = [];
        const mdImg = /!\[[^\]]*\]\([^)]+\)/g;
        let m: RegExpExecArray | null;
        while ((m = mdImg.exec(content)) !== null) images.push(m[0]);
        const htmlImg = /<img[^>]+>/gi;
        while ((m = htmlImg.exec(content)) !== null) images.push(m[0]);
        return images;
    };

    const getStructureByType = (type: string): string => {
        switch (type) {
            case "缺陷":
                return `- **问题描述**：清晰描述缺陷的具体现象
- **复现步骤**：列出重现该缺陷的详细操作步骤
- **实际结果**：当前实际出现的错误现象
- **预期结果**：正常情况下应该出现的结果
- **影响范围**：该缺陷影响的功能模块和严重程度`;
            case "任务":
                return `- **任务目标**：明确说明本任务要达成的目标
- **实现方案**：列出具体的实施步骤或技术方案
- **完成标准**：明确可验证的交付标准
- **依赖与注意事项**：前置依赖、风险点或需要注意的事项`;
            default:
                return `- **需求背景**：为什么需要做这个需求
- **用户故事**：作为___，我希望___，以便___
- **验收标准**：列出具体可验证的验收条件
- **技术要点**：关键的技术实现方向（如果能判断）`;
        }
    };

    const buildDescEnrichPrompt = (): string => {
        const rec = opts.record.value;
        if (!rec) return "";
        const title = rec.title || "";
        const desc = opts.detailDescDraft.value || rec.description || "";
        const project = rec.projectName || "";
        const type = rec.type || "需求";

        const images = extractImageRefs(desc);
        const imagePart = images.length > 0
            ? `\n\n重要：原描述中包含 ${images.length} 张图片，你必须在输出中原样保留所有图片引用（不要修改图片语法或 URL），将它们放在最相关的段落位置：\n${images.map((img, i) => `${i + 1}. ${img}`).join("\n")}`
            : "";

        const descPart = desc.trim()
            ? `当前已有描述：\n${desc}\n\n请在此基础上完善和补充。`
            : "（暂无描述内容）";

        const structure = getStructureByType(type);

        return `请帮我完善以下${type}的描述内容。

${type}标题：${title}
所属项目：${project || "未设置"}
${descPart}

请生成一份结构清晰的${type}描述，可以包含以下结构（按需裁剪）：
${structure}

如果需要了解项目的业务背景，你可以查询项目信息或关联的代码仓库来获取更多上下文。${imagePart}
请直接输出 Markdown 格式的描述内容，不要包含${type}标题。`;
    };

    const startAiEnrichDesc = () => {
        if (!opts.detailDescEditing.value) {
            openDetailDescEditor();
        }
        const prompt = buildDescEnrichPrompt();
        if (!prompt) return;
        descAi.run(prompt);
    };

    const applyAiDesc = () => {
        if (!descAi.text.value) return;
        opts.detailDescDraft.value = descAi.text.value;
        descAi.clear();
    };

    const buildSupplementPrompt = (): string => {
        const r = opts.record.value;
        if (!r) return "";
        const fields = [
            `负责人：${r.owner || "未指派"}`,
            `计划时间：${r.planTime?.[0] && r.planTime?.[1] ? `${r.planTime[0]} ~ ${r.planTime[1]}` : "未设置"}`,
            `迭代：${r.iteration || "未设置"}`,
            `版本：${r.version || "未设置"}`,
            `预估工时：${r.estimateHours != null ? r.estimateHours + " 小时" : "未设置"}`,
        ].join("\n");

        const entityType = opts.getEntityType();
        return `请帮我补充${r.type}「${r.title}」(${r.workNo}) 的详细信息。
实体类型：${entityType}，实体 ID：${r.backendId}

所属项目：${r.projectName || "未设置"}
当前字段：
${fields}

请根据${r.type}标题、描述和项目上下文，帮我合理补充以上尚未设置的字段。你可以：
1. 先查询项目信息了解团队成员、迭代计划、版本规划
2. 查看关联的代码仓库了解技术背景
3. 参考同项目其他${r.type}的设置

然后使用工具逐个更新这些字段。每个字段请先简要说明理由再操作。`;
    };

    return {
        descAi,
        descAiPhaseLabel,
        aiEnrichBtnLabel,
        openDetailDescEditor,
        saveDetailDescEditor,
        cancelDetailDescEditor,
        startAiEnrichDesc,
        applyAiDesc,
        buildSupplementPrompt,
    };
}
