// Service Worker: recebe Web Push e exibe notificação (mesmo com aba em segundo plano).
self.addEventListener("push", function (event) {
    if (!event.data) return;
    var payload;
    try {
        payload = event.data.json();
    } catch (e) {
        payload = { title: "ZapAction", body: event.data.text() || "Nova mensagem" };
    }
    var title = payload.title || "Nova mensagem - ZapAction";
    var body = payload.body || "Você recebeu uma nova mensagem.";
    var opts = {
        body: body,
        icon: "/static/images/logo.png",
        badge: "/static/images/logo.png",
        tag: "agenteia-msg",
        requireInteraction: false,
    };
    event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
            for (var i = 0; i < clientList.length; i++) {
                var c = clientList[i];
                if (c.url.indexOf("/chat") !== -1 && "focus" in c) {
                    c.focus();
                    return;
                }
            }
            if (self.clients.openWindow) {
                self.clients.openWindow("/chat");
            }
        })
    );
});
