import { ref, type Ref } from "vue";
import { message } from "@openvort/vort-ui";
import { uploadVortflowFile } from "@/api";
import type { AttachmentItem, RowItem } from "@/components/vort-biz/work-item/WorkItemTable.types";

export interface UseWorkItemDetailAttachmentsOptions {
    /** 当前打开的工作项 */
    record: Ref<RowItem | null>;
    /** 附件变化时通过 emit 通知父级（保持原 emit 形态） */
    onUpdateAttachments: (attachments: AttachmentItem[]) => void;
    /** 附件变化同步追加日志 */
    appendDetailLog: (action: string, detail?: any) => void;
}

/**
 * 工作项详情面板「附件上传 / 删除」相关状态与操作。
 *
 * 抽离自 WorkItemDetail.vue 阶段 D3a：
 * - <input type="file"> 引用与上传中标志
 * - 多文件循环上传（>20MB 警告，单文件失败不中断其它）
 * - 移除某条附件
 *
 * 单条附件 ≤20MB 限制硬编码于此；后续若调整需要更新文档。
 */
export function useWorkItemDetailAttachments(opts: UseWorkItemDetailAttachmentsOptions) {
    const detailAttachmentInputRef = ref<HTMLInputElement | null>(null);
    const detailAttachmentUploading = ref(false);

    const triggerDetailAttachmentInput = () => detailAttachmentInputRef.value?.click();

    const handleDetailAttachmentFiles = async (e: Event) => {
        const files = (e.target as HTMLInputElement).files;
        if (!files || files.length === 0 || !opts.record.value) return;
        detailAttachmentUploading.value = true;
        const oldAttachments: AttachmentItem[] = [...(opts.record.value.attachments || [])];
        const newAttachments: AttachmentItem[] = [...oldAttachments];
        try {
            for (const file of Array.from(files)) {
                if (file.size > 20 * 1024 * 1024) {
                    message.warning(`文件 ${file.name} 超过 20MB 限制`);
                    continue;
                }
                try {
                    const res: any = await uploadVortflowFile(file);
                    if (res?.error) {
                        message.error(res.error);
                        continue;
                    }
                    newAttachments.push({
                        name: res.name || file.name,
                        url: res.url,
                        size: res.size || file.size,
                    });
                } catch {
                    message.error(`上传 ${file.name} 失败`);
                }
            }
            opts.record.value.attachments = newAttachments;
            opts.onUpdateAttachments(newAttachments);
            opts.appendDetailLog("updated", { attachments: { from: oldAttachments, to: newAttachments } });
        } finally {
            detailAttachmentUploading.value = false;
            if (detailAttachmentInputRef.value) detailAttachmentInputRef.value.value = "";
        }
    };

    const removeDetailAttachment = (index: number) => {
        if (!opts.record.value) return;
        const oldAttachments: AttachmentItem[] = [...(opts.record.value.attachments || [])];
        const newAttachments = [...oldAttachments];
        newAttachments.splice(index, 1);
        opts.record.value.attachments = newAttachments;
        opts.onUpdateAttachments(newAttachments);
        opts.appendDetailLog("updated", { attachments: { from: oldAttachments, to: newAttachments } });
    };

    return {
        detailAttachmentInputRef,
        detailAttachmentUploading,
        triggerDetailAttachmentInput,
        handleDetailAttachmentFiles,
        removeDetailAttachment,
    };
}
