import { ref, computed } from "vue";

/**
 * 桌面通知（系统级通知中心）
 *
 * 行为约定：
 *  - 仅在浏览器支持 + 用户已授权 + 用户开启偏好 + 页面不可见时弹出
 *  - 用户偏好持久化到 localStorage，跨会话保留
 *  - 优先通过 ServiceWorkerRegistration.showNotification 发送（支持 actions / persistent），
 *    fallback 到 window.Notification
 */

const STORAGE_KEY = "openvort.desktop_notification.enabled";

type PermissionState = NotificationPermission | "unsupported";

const supported = typeof window !== "undefined" && "Notification" in window;

const permission = ref<PermissionState>(supported ? Notification.permission : "unsupported");
const enabled = ref<boolean>(loadEnabled());

function loadEnabled(): boolean {
    try {
        return localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
        return false;
    }
}

function saveEnabled(value: boolean) {
    try {
        if (value) localStorage.setItem(STORAGE_KEY, "1");
        else localStorage.removeItem(STORAGE_KEY);
    } catch { /* noop */ }
}

function setEnabled(value: boolean) {
    enabled.value = value;
    saveEnabled(value);
}

async function requestPermission(): Promise<PermissionState> {
    if (!supported) return "unsupported";
    if (Notification.permission === "granted") {
        permission.value = "granted";
        return "granted";
    }
    if (Notification.permission === "denied") {
        permission.value = "denied";
        return "denied";
    }
    try {
        const result = await Notification.requestPermission();
        permission.value = result;
        return result;
    } catch {
        permission.value = "default";
        return "default";
    }
}

async function enable(): Promise<boolean> {
    if (!supported) return false;
    const result = await requestPermission();
    if (result === "granted") {
        setEnabled(true);
        return true;
    }
    return false;
}

function disable() {
    setEnabled(false);
}

export interface DesktopNotifyOptions {
    title: string;
    body?: string;
    icon?: string;
    tag?: string;
    url?: string;
    /** 即使页面可见时也强制弹出（默认 false：可见时不弹，避免打扰） */
    force?: boolean;
}

async function notify(opts: DesktopNotifyOptions): Promise<void> {
    if (!supported) return;
    if (!enabled.value) return;
    if (Notification.permission !== "granted") return;
    if (!opts.force && typeof document !== "undefined" && document.visibilityState === "visible") {
        return;
    }

    const title = opts.title || "OpenVort";
    const options: NotificationOptions & { renotify?: boolean } = {
        body: opts.body || "",
        icon: opts.icon || "/logo.png",
        badge: "/logo.png",
        tag: opts.tag,
        data: { url: opts.url || location.pathname + location.search },
        renotify: !!opts.tag,
    };

    try {
        if ("serviceWorker" in navigator && navigator.serviceWorker.controller) {
            const reg = await navigator.serviceWorker.ready;
            await reg.showNotification(title, options);
            return;
        }
    } catch { /* fallback */ }

    try {
        const n = new Notification(title, options);
        n.onclick = (e) => {
            e.preventDefault();
            window.focus();
            const url = (options.data as any)?.url;
            if (url && url !== location.pathname + location.search) {
                try { window.location.assign(url); } catch { /* noop */ }
            }
            n.close();
        };
    } catch { /* noop */ }
}

export function useDesktopNotification() {
    const canRequest = computed(() => supported && permission.value === "default");
    const isGranted = computed(() => supported && permission.value === "granted");
    const isDenied = computed(() => supported && permission.value === "denied");
    const isActive = computed(() => isGranted.value && enabled.value);

    return {
        supported,
        permission,
        enabled,
        canRequest,
        isGranted,
        isDenied,
        isActive,
        requestPermission,
        enable,
        disable,
        notify,
    };
}

export function desktopNotify(opts: DesktopNotifyOptions) {
    return notify(opts);
}
