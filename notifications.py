"""Notificações de outros apps, mostradas na pílula.

O servidor de notificações continua sendo o do sistema (COSMIC, GNOME…). A
ilha só observa as chamadas Notify no barramento de sessão, em modo monitor
(org.freedesktop.DBus.Monitoring), numa conexão separada.
"""
import html
import os
import re

from gi.repository import Gio, GLib

RULE = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
OWN_APP = "linux-island"
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text):
    """Corpo das notificações aceita um pouco de HTML: vira texto simples, numa linha."""
    text = html.unescape(TAG_RE.sub("", text or ""))
    return " ".join(text.split())


def parse_ignore(spec):
    return {s.strip().lower() for s in (spec or "").split(",") if s.strip()}


def resolve_icon(app_icon, hints):
    """Gio.Icon do app: imagem da notificação, ícone informado ou o do .desktop."""
    candidates = []
    image = hints.get("image-path") or hints.get("image_path")
    if isinstance(image, str):
        candidates.append(image)
    if app_icon:
        candidates.append(app_icon)
    for value in candidates:
        if value.startswith("file://"):
            value = GLib.filename_from_uri(value)[0]
        if value.startswith("/"):
            if os.path.exists(value):
                return Gio.FileIcon.new(Gio.File.new_for_path(value))
        else:
            return Gio.ThemedIcon.new(value)
    entry = hints.get("desktop-entry")
    if isinstance(entry, str) and entry:
        try:
            info = Gio.DesktopAppInfo.new(entry + ".desktop")
        except TypeError:
            info = None
        if info and info.get_icon():
            return info.get_icon()
    return None


class Notification:
    def __init__(self, app, summary, body, icon, desktop_entry):
        self.app, self.summary, self.body = app, summary, body
        self.icon, self.desktop_entry = icon, desktop_entry


class NotificationWatcher:
    """Chama on_notify(Notification) na thread da UI para cada notificação nova."""

    def __init__(self, on_notify):
        self.on_notify = on_notify
        self.conn = None
        self.start()

    def start(self):
        try:
            addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            flags = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                     | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
            self.conn = Gio.DBusConnection.new_for_address_sync(addr, flags, None, None)
            self.conn.add_filter(self._filter)
            self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                                GLib.Variant("(asu)", ([RULE], 0)), None,
                                Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error as e:
            print(f"[island] não deu para observar notificações: {e.message}")
            self.conn = None

    def _filter(self, _conn, msg, incoming):
        # roda numa thread do GDBus: só extrai os dados e passa para a UI
        if not incoming or msg.get_message_type() != Gio.DBusMessageType.METHOD_CALL:
            return msg  # o que a ilha envia (BecomeMonitor) e as respostas seguem normais
        if msg.get_member() == "Notify" and msg.get_body() is not None:
            try:
                app, _rid, app_icon, summary, body, _actions, hints, _t = msg.get_body().unpack()
                GLib.idle_add(self._deliver, app, app_icon, summary, body, hints)
            except (ValueError, TypeError):
                pass
        # Chamadas observadas são consumidas aqui: se seguissem, o GDBus
        # responderia "método desconhecido", e monitores não podem enviar
        # nada (o barramento desconectaria a ilha).
        return None

    def _deliver(self, app, app_icon, summary, body, hints):
        summary, body = clean_text(summary), clean_text(body)
        if not summary and not body:
            return False
        entry = hints.get("desktop-entry") if isinstance(hints, dict) else None
        icon = resolve_icon(app_icon, hints if isinstance(hints, dict) else {})
        self.on_notify(Notification(app or "", summary or body, body if summary else "",
                                    icon, entry if isinstance(entry, str) else None))
        return False
