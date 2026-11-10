"""Páginas da ilha expandida e prioridade do miolo da pílula (inclui o lembrete de água).

Mixin da janela Island; usa self.full, self.water, self.water_page, self.compact,
self.shell, self.cfg, self.app, self._timers e self._follow_size dela.
"""
from gi.repository import Gtk

from pointer import log
from water import play_sound

TRANSITION_MS = 320
PAGES = ("home", "water")  # páginas da ilha expandida, na ordem do arrasto


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
        log("page", name)
        self.pages.set_visible_child_name(name)
        self._mark_dot(name)
        self._follow_size()

    def turn_page(self, step):
        """step=+1 próxima página (arrastar para a esquerda), -1 anterior."""
        i = PAGES.index(self.pages.get_visible_child_name()) + step
        if 0 <= i < len(PAGES):
            self.set_page(PAGES[i])

    def _refresh_middle(self):
        """O que aparece no miolo da pílula: faixa nova > alerta de água > relógio."""
        if "track_peek" in self._timers:
            name = "track"
        elif self.water.alerting:
            name = "water"
        else:
            name = "info"
        self.compact.middle.set_visible_child_name(name)
        self._follow_size()

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

