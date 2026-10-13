/* OpenVort Service Worker
 *
 * 目的：
 *   1. 满足 PWA 可安装条件（必须存在 SW 且有 fetch handler）
 *   2. 处理桌面通知的点击事件 —— 点击通知后聚焦到 OpenVort 标签页并跳转
 *   3. 预留 Web Push 入口，后端配 VAPID 后可直接接收离线推送
 *
 * 不做缓存：避免和后端版本号、Vite 动态 chunk 冲突。所有请求一律透传到网络。
 */

const SW_VERSION = "openvort-sw-v1";

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

// 网络透传，不做缓存
self.addEventListener("fetch", (event) => {
    // 仅同源 GET 请求走默认网络，其他类型也透传
    return;
});

// 通知点击：聚焦/打开对应页面
self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const target = (event.notification.data && event.notification.data.url) || "/";

    event.waitUntil(
        (async () => {
            const allClients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
            for (const client of allClients) {
                try {
                    const url = new URL(client.url);
                    if (url.origin === self.location.origin) {
                        await client.focus();
                        if (target && target !== "/") {
                            client.postMessage({ type: "navigate", url: target });
                        }
                        return;
                    }
                } catch (_) { /* noop */ }
            }
            await self.clients.openWindow(target);
        })()
    );
});

// Web Push 入口（预留）。当后端注入 VAPID 配置后，会自动生效
self.addEventListener("push", (event) => {
    let payload = {};
    try {
        payload = event.data ? event.data.json() : {};
    } catch (_) {
        payload = { title: "OpenVort", body: event.data ? event.data.text() : "" };
    }
    const title = payload.title || "OpenVort";
    const options = {
        body: payload.body || "",
        icon: payload.icon || "/logo.png",
        badge: payload.badge || "/logo.png",
        tag: payload.tag,
        data: { url: payload.url || "/" },
        renotify: !!payload.tag,
    };
    event.waitUntil(self.registration.showNotification(title, options));
});
