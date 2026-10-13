/**
 * Redirect helpers for the login flow.
 *
 * Centralizes the post-login redirect handling so router guard, the login
 * page and the axios interceptor all share the same parsing/sanitization
 * rules. This avoids drift and consolidates the open-redirect guards in a
 * single place.
 */

const LOGIN_PATH = "/login";
const FALLBACK_TARGET = "/";

/**
 * Validate and normalize a `redirect` value into a safe in-app path.
 *
 * Rules:
 *  - Must be a string.
 *  - Must start with a single "/" (rejects "//evil.com" protocol-relative
 *    URLs and "/\\evil.com" backslash variants).
 *  - Must resolve to the same origin as the current window.
 *  - Must not point back to the login page (avoids redirect loops).
 *
 * Returns the fallback "/" when any check fails.
 */
export function sanitizeRedirect(raw: unknown): string {
    const value = Array.isArray(raw) ? raw[0] : raw;
    if (typeof value !== "string" || value.length === 0) return FALLBACK_TARGET;
    if (!value.startsWith("/")) return FALLBACK_TARGET;
    if (value.startsWith("//") || value.startsWith("/\\")) return FALLBACK_TARGET;

    let url: URL;
    try {
        url = new URL(value, window.location.origin);
    } catch {
        return FALLBACK_TARGET;
    }
    if (url.origin !== window.location.origin) return FALLBACK_TARGET;

    const path = url.pathname + url.search + url.hash;
    if (path === LOGIN_PATH || path.startsWith(`${LOGIN_PATH}/`) || path.startsWith(`${LOGIN_PATH}?`)) {
        return FALLBACK_TARGET;
    }
    return path;
}

/**
 * Build a `vue-router` location for navigating to the login page while
 * preserving the user's intended destination as `?redirect=`.
 *
 * Pass an empty/undefined `currentPath` (or the login path itself) to
 * skip the `redirect` query — useful for explicit logout flows.
 */
export function buildLoginLocation(currentPath?: string): { path: string; query?: Record<string, string> } {
    if (!currentPath || currentPath === LOGIN_PATH || currentPath.startsWith(`${LOGIN_PATH}?`) || currentPath.startsWith(`${LOGIN_PATH}/`)) {
        return { path: LOGIN_PATH };
    }
    return { path: LOGIN_PATH, query: { redirect: currentPath } };
}

/**
 * Same as `buildLoginLocation` but returns a fully-encoded URL string,
 * for callers that have to use `window.location.href` (e.g. when the
 * router instance isn't available in the current execution context).
 */
export function buildLoginHref(currentPath?: string): string {
    const loc = buildLoginLocation(currentPath);
    if (!loc.query?.redirect) return loc.path;
    return `${loc.path}?redirect=${encodeURIComponent(loc.query.redirect)}`;
}
