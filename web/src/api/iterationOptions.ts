/**
 * 拉取所有分页结果。
 *
 * 需要完整候选集合的展示/导航场景使用该方法；迭代列表接口默认是分页的，
 * 仅请求第一页会让排在后面的迭代（例如没有开始日期的迭代）从列表中消失。
 */
export interface PaginatedItems<T> {
    items?: T[];
    total?: number | string | null;
}

export interface FetchAllPagesOptions {
    /** 单次请求的页大小；实际值不会超过服务端允许的上限。 */
    pageSize?: number;
    /** 服务端允许的最大页大小。 */
    maxPageSize?: number;
    /** 异常响应时的最大页数保护。 */
    maxPages?: number;
}

export async function fetchAllPages<T>(
    fetchPage: (page: number, pageSize: number) => Promise<PaginatedItems<T>>,
    options: FetchAllPagesOptions = {},
): Promise<{ items: T[]; total: number }> {
    const maxPageSize = Math.max(1, Math.floor(options.maxPageSize ?? 200));
    const requestedPageSize = Math.max(1, Math.floor(options.pageSize ?? maxPageSize));
    const pageSize = Math.min(requestedPageSize, maxPageSize);
    const maxPages = Math.max(1, Math.floor(options.maxPages ?? 1000));

    const items: T[] = [];
    let total: number | undefined;

    for (let page = 1; page <= maxPages; page += 1) {
        const response = await fetchPage(page, pageSize);
        const pageItems = Array.isArray(response?.items) ? response.items : [];
        items.push(...pageItems);

        const rawTotal = response?.total;
        const responseTotal = typeof rawTotal === "number"
            ? rawTotal
            : (typeof rawTotal === "string" && rawTotal.trim() ? Number(rawTotal) : NaN);
        if (Number.isFinite(responseTotal) && responseTotal >= 0) {
            total = responseTotal;
        }

        // total 缺失时，短页可作为结束信号；有 total 时必须继续拉到 total，
        // 即使中间某页因服务端临时限流而少返回了几条。
        if (
            pageItems.length === 0
            || (total !== undefined && items.length >= total)
            || (total === undefined && pageItems.length < pageSize)
        ) {
            break;
        }
    }

    return {
        items,
        total: Math.max(total ?? 0, items.length),
    };
}
