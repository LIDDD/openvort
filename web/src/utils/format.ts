export function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * 把日期格式化为本地时区的 YYYY-MM-DD。
 *
 * 注意：不要用 `new Date().toISOString().slice(0, 10)`——它输出的是 UTC 日期，
 * 北京时间凌晨 0:00–08:00 之间会拿到「昨天」。
 */
export function formatLocalDate(d: Date = new Date()): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}
