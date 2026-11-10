"""Páginas da ilha expandida e prioridade do miolo da pílula (inclui o lembrete de água).

Mixin da janela Island; usa self.full, self.water, self.water_page, self.compact,
self.shell, self.cfg, self.app, self._timers e self._follow_size dela.
"""
from datetime import datetime

from gi.repository import Gio, Gtk

from notifications import OWN_APP, parse_ignore

from pointer import log
from water import play_sound

TRANSITION_MS = 320
PAGES = ("home", "water", "agenda")  # páginas da ilha expandida, na ordem do arrasto


class PagesMixin:
    def _build_pages(self):
        """Ilha expandida: páginas lado a lado (arrastar para o lado troca) + pontinhos."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pages = Gtk.Stack()
        self.pages.set_homogeneous(False)
        self.pages.set_interpolate_size(True)
        self.pages.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.pages.set_transition_duration(TRANSITION_MS)
        self.pages.add_named(self.full, "home")
        self.pages.add_named(self.water_page, "water")
        self.pages.add_named(self.agenda_page, "agenda")
        box.pack_start(self.pages, False, False, 0)

        dots = Gtk.Box(spacing=6)
        dots.set_halign(Gtk.Align.CENTER)
        dots.set_margin_bottom(10)
        self.dots = {}
        for name in PAGES:
            dot = Gtk.Button()
            dot.set_can_focus(False)
            dot.get_style_context().add_class("page-dot")
            dot.connect("clicked", lambda _b, n=name: self.set_page(n))
            dots.pack_start(dot, False, False, 0)
            self.dots[name] = dot
        box.pack_start(dots, False, False, 0)
        self._mark_dot("home")
        return box

    def _mark_dot(self, name):
        for n, dot in self.dots.items():
            ctx = dot.get_style_context()
            (ctx.add_class if n == name else ctx.remove_class)("active")

    def set_page(self, name):
        if name == self.pages.get_visible_child_name():
            return
        if name == "water":
            self.water_page.update(self.cfg)
        elif name == "agenda":
            self.agenda_page.update(self.cfg)
        log("page", name)
        self.pages.set_visible_child_name(name)
        self._mark_dot(name)
        self._follow_size()

    def turn_page(self, step):
        """step=+1 próxima página (arrastar para a esquerda), -1 anterior."""
        i = PAGES.index(self.pages.get_visible_child_name()) + step
        if 0 <= i < len(PAGES):
            self.set_page(PAGES[i])

    def _alert_page(self):
        """Página do alerta mais importante (reunião > água), ou a inicial."""
        if self.agenda.alert:
            return "agenda"
        return "water" if self.water.alerting else "home"

    def _refresh_middle(self):
        """Miolo da pílula: notificação > faixa nova > reunião > água > relógio."""
        if "notif_peek" in self._timers:
            name = "notif"
        elif "track_peek" in self._timers:
            name = "track"
        elif self.agenda.alert:
            self.meeting_pill.update(self.agenda.alert, datetime.now().astimezone())
            name = "meeting"
        elif self.water.alerting:
            name = "water"
        else:
            name = "info"
        self.compact.middle.set_visible_child_name(name)
        self._follow_size()

    # --- notificações de outros apps ----------------------------------------
    def _on_notification(self, n):
        cfg = self.cfg
        if (not cfg["notif_enabled"] or cfg["notif_dnd"] or self.expanded
                or n.app.lower() == OWN_APP
                or n.app.lower() in parse_ignore(cfg["notif_ignore"])):
            return
        log("notificação", n.app)
        last = self._notif_queue[-1] if self._notif_queue else self._notif_current
        if last and (last.app, last.summary, last.body) == (n.app, n.summary, n.body):
            return  # repetida
        self._notif_queue = (self._notif_queue + [n])[-5:]
        if "notif_peek" not in self._timers:
            self._show_next_notification()

    def _show_next_notification(self):
        if not self._notif_queue or self.expanded:
            self._notif_queue = []
            self._notif_current = None
            self._refresh_middle()
            return
        self._notif_current = self._notif_queue.pop(0)
        self.notif_pill.update(self._notif_current, self.cfg["notif_show_body"])
        self._later("notif_peek", self.cfg["notif_duration_s"] * 1000,
                    self._show_next_notification)
        self._refresh_middle()

    def open_notification_app(self):
        """Clique na pílula durante uma notificação: abre o app, se der para saber qual."""
        n = self._notif_current if "notif_peek" in self._timers else None
        if not n or not n.desktop_entry:
            return False
        try:
            info = Gio.DesktopAppInfo.new(n.desktop_entry + ".desktop")
        except TypeError:
            info = None
        if info is None:
            return False
        info.launch([], None)
        self._cancel("notif_peek")
        self._show_next_notification()
        return True

    # --- agenda ---------------------------------------------------------
    def _on_agenda_change(self):
        if self.pages.get_visible_child_name() == "agenda":
            self.agenda_page.update(self.cfg)
            self._follow_size()

    def _on_agenda_alert(self, ev):
        log("meeting alert", ev and ev["title"])
        ctx = self.shell.get_style_context()
        (ctx.add_class if ev else ctx.remove_class)("meeting-alert")
        self._refresh_middle()
        self._on_agenda_change()
        if self.expanded and not ev and self.pages.get_visible_child_name() == "agenda":
            return  # o usuário está olhando a agenda: não troca de página
        if not self.expanded:
            self.set_page(self._alert_page())

    def _on_agenda_status(self, text, ok):
        self._on_agenda_change()
        if self.app.settings:
            self.app.settings.set_agenda_status(text, ok)

    # --- água -----------------------------------------------------------
    def _on_water_change(self):
        goal = self.cfg["water_goal_ml"]
        self.alert_amount.set_text(f"{self.water.consumed}/{goal} ml")
        self.water_page.update(self.cfg)
        if self.app.settings:
            self.app.settings._water_refresh()
        self._follow_size()

    def _on_water_alert(self, alerting):
        log("water alert", alerting)
        ctx = self.shell.get_style_context()
        (ctx.add_class if alerting else ctx.remove_class)("water-alert")
        self._on_water_change()
        self._refresh_middle()
        if alerting and self.cfg["water_sound"]:
            play_sound(self.cfg["water_sound_name"], self.cfg["water_sound_volume"])
        if alerting and self.cfg["water_notify"]:
            self.app.notify_water(self.water.consumed, self.cfg["water_goal_ml"])
        elif not alerting:
            self.app.withdraw_water()

