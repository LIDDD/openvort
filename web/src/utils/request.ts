import axios from "axios";
import { useUserStore } from "@/stores";
import { message } from "@openvort/vort-ui";
import { buildLoginHref } from "@/utils/redirect";

declare module "axios" {
    interface AxiosRequestConfig {
        /** 跳过拦截器的全局错误提示（组件自行处理时使用） */
        skipErrorMessage?: boolean;
    }
}

const request = axios.create({
    baseURL: "/api",
    timeout: 10000
});

// One-shot lock so concurrent 401 responses do not trigger multiple
// logout/redirect cycles (which would also corrupt the redirect query
// when the second 401 reads a location already mutated by the first).
let unauthorizedRedirectInFlight = false;

async function redirectToLogin(): Promise<void> {
    if (unauthorizedRedirectInFlight) return;
    unauthorizedRedirectInFlight = true;

    // Prefer vue-router's resolved fullPath: during in-app navigation the
    // browser URL may still reflect the previous page, while currentRoute
    // matches the destination the user was trying to reach.
    // Lazy-load the router instance to avoid a circular import between
    // request.ts ↔ @/router (router imports stores → stores import api → api imports request).
    let routerPath: string | undefined;
    try {
        const { default: router } = await import("@/router");
        routerPath = router.currentRoute.value?.fullPath;
    } catch {
        routerPath = undefined;
    }
    const fallback = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    const current = routerPath || fallback;

    window.location.href = buildLoginHref(current);
}

request.interceptors.request.use((config) => {
    const userStore = useUserStore();
    if (userStore.token) {
        config.headers.Authorization = `Bearer ${userStore.token}`;
    }
    return config;
});

request.interceptors.response.use(
    (response) => {
        return response.data;
    },
    (error) => {
        const detail = error.response?.data?.detail || "";
        if (error.response?.status === 401) {
            const isLoginRequest = error.config?.url?.includes("/auth/login");
            if (!isLoginRequest && !unauthorizedRedirectInFlight) {
                const userStore = useUserStore();
                userStore.logout();
                void redirectToLogin();
            }
        } else if (error.response?.status === 403 && detail === "演示账号无操作权限") {
            message.warning("演示账号无操作权限");
        } else if (!error.config?.skipErrorMessage) {
            message.error(detail || error.response?.data?.message || "请求失败");
        }
        return Promise.reject(error);
    }
);

export default request;
