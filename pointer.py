"""Mouse na ilha: hover, cliques, rolagem (volume) e menu do botão direito.

Mixin da janela Island; usa self.cfg, self.player, self.compact, self.full,
self.app, self.expanded e os métodos set_expanded/_follow_size dela.
"""
import os
import time

from gi.repository import Gdk, GLib, Gtk

from i18n import _

DEBUG = bool(os.environ.get("ISLAND_DEBUG"))
CLICK_SLOP_PX = 8        # até isso de movimento, ainda é clique
SWIPE_PX = 50            # a partir disso, arrastar para o lado troca de página
HSCROLL_STEP = 3.0       # deltas horizontais do touchpad para trocar de página
COLLAPSE_DELAY_MS = 700  # tolera leaves espúrios do compositor
VOLUME_STEP = 0.05       # 5% por "clique" da roda do mouse


def log(*a):
    if DEBUG:
        print(f"[island {time.monotonic():.2f}]", *a, flush=True)


class InputMixin:
    def _later(self, key, ms, fn):
        self._cancel(key)

        def run():
            self._timers.pop(key, None)
            fn()
            return False

        self._timers[key] = GLib.timeout_add(ms, run)

    def _cancel(self, key):
        sid = self._timers.pop(key, None)
        if sid:
            GLib.source_remove(sid)

    def _pointer_inside(self):
        """Pergunta ao GDK se o ponteiro está sobre a nossa superfície.

        Os detalhes de enter/leave não servem: o GTK3 no Wayland gera pares
        enter/leave "fantasmas" ao cruzar as GdkWindows internas do Stack.
        """
        seat = self.get_display().get_default_seat()
        win = seat.get_pointer().get_window_at_position()[0] if seat else None
        return win is not None and win.get_toplevel() == self.get_window()

    def _recheck_hover(self):
        if self._press is not None:
            # botão segurado: arrastar para o lado sai da superfície, mas não fecha
            return
        self.hovered = self._pointer_inside()
        log("hover?", self.hovered)
        if not self.hovered:
            self._closed_by_click = False
        if self.hovered:
            self._cancel("collapse")
            if not self.expanded and not self._closed_by_click and self.cfg["hover_expand"]:
                self._later("expand", self.cfg["hover_delay_ms"],
                            lambda: self._pointer_inside() and self.set_expanded(True))
        else:
            self._cancel("expand")
            if self.expanded:
                self._later("collapse", COLLAPSE_DELAY_MS,
                            lambda: self._pointer_inside() or self.set_expanded(False))

    def _drop_stale_press(self, ev):
        """Se a soltura do botão se perdeu, não deixa a ilha presa aberta."""
        if self._press is None:
            return
        held = ev.get_state()[1] & Gdk.ModifierType.BUTTON1_MASK
        if not held or time.monotonic() - self._press[2] > 3:
            log("press perdido, descartando")
            self._press = None

    def _enter(self, _w, ev):
        log("enter", ev.detail.value_nick)
        self._drop_stale_press(ev)
        # adia para o próximo ciclo: o GDK atualiza o foco do ponteiro depois do evento
        self._later("hover", 30, self._recheck_hover)

    def _leave(self, _w, ev):
        log("leave", ev.detail.value_nick)
        self._drop_stale_press(ev)
        self._later("hover", 30, self._recheck_hover)

    def _click(self, _w, ev):
        if ev.time == self._last_click:  # o mesmo clique chega duas vezes
            return False
        self._last_click = ev.time
        log("press", ev.button)
        if ev.button == 1:
            # decide na soltura: clique (alterna) ou arrasto (troca de página)
            self._press = (ev.x_root, ev.y_root, time.monotonic())
        elif ev.button == 3:
            self._menu(ev)
        elif ev.button == 2:
            self.player.play_pause()
        return False

    def _release(self, _w, ev):
        if ev.button != 1 or self._press is None:
            return False
        x0, y0, _t = self._press
        self._press = None
        dx, dy = ev.x_root - x0, ev.y_root - y0
        log("release", round(dx), round(dy))
        if self.expanded and abs(dx) >= SWIPE_PX and abs(dx) > abs(dy):
            self.turn_page(1 if dx < 0 else -1)  # arrastar para a esquerda = próxima
        elif abs(dx) <= CLICK_SLOP_PX and abs(dy) <= CLICK_SLOP_PX:
            if not self.expanded and self.open_notification_app():
                return False  # clique numa notificação abre o app que notificou
            for t in ("expand", "collapse"):
                self._cancel(t)
            self._closed_by_click = self.expanded
            self.set_expanded(not self.expanded)
        self._later("hover", 30, self._recheck_hover)
        return False

    def _scroll(self, _w, ev):
        """Rolagem vertical muda o volume; horizontal (touchpad) troca de página."""
        ok, dx, dy = ev.get_scroll_deltas()
        if self.expanded and self._hscroll_page(ev, ok, dx, dy):
            return True
        if not self.cfg["scroll_volume"] or not self.player.proxy:
            return False
        log("scroll", ev.time, ev.direction.value_nick, ok, dy, ev.get_source_device().get_name())
        key = (ev.time, ev.direction, round(dy, 3))
        if key == self._last_scroll:  # o mesmo evento chega duas vezes
            return True
        self._last_scroll = key
        if ev.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            # roda do mouse: o Wayland manda um evento discreto + um suave por clique
            self._last_discrete = ev.time
            step = 1 if ev.direction == Gdk.ScrollDirection.UP else -1
        elif ev.direction == Gdk.ScrollDirection.SMOOTH and ok:
            if ev.time == self._last_discrete:  # par suave do clique já contado
                return True
            # touchpad: acumula deltas pequenos até virar um passo
            self._scroll_acc -= dy / 1.5
            step = int(self._scroll_acc)
            self._scroll_acc -= step
        else:
            return False
        if step:
            v = round(self.player.volume + step * VOLUME_STEP, 2)
            self.player.set_volume(v)
            self._on_volume(self.player.volume, from_user=True)
        return True

    def _hscroll_page(self, ev, ok, dx, dy):
        if ev.direction in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.RIGHT):
            self.turn_page(1 if ev.direction == Gdk.ScrollDirection.RIGHT else -1)
            return True
        if ev.direction != Gdk.ScrollDirection.SMOOTH or not ok or abs(dx) <= abs(dy):
            return False
        self._hscroll += dx
        if abs(self._hscroll) >= HSCROLL_STEP:
            self.turn_page(1 if self._hscroll > 0 else -1)
            self._hscroll = 0.0
        return True

    def _on_volume(self, v, from_user=False):
        self.full.set_volume(v)
        if from_user and not self.expanded:
            self.compact.show_volume(v, True)
            self._follow_size()
            self._later("hide_volume", 1500, self._hide_volume)
        elif "hide_volume" in self._timers:
            self.compact.show_volume(v, True)

    def _hide_volume(self):
        self.compact.show_volume(self.player.volume, False)
        self._follow_size()

    def _menu(self, ev):
        menu = Gtk.Menu()
        items = [(_("Configurações…"), self.app.open_settings)]
        if self.player.proxy:
            items.append((_("Abrir o {app}").format(app=self.player.name),
                          self.player.raise_window))
        items += [(None, None), (_("Sair"), self.app.quit)]
        for text, cb in items:
            item = Gtk.SeparatorMenuItem() if text is None else Gtk.MenuItem(label=text)
            if cb:
                item.connect("activate", lambda _i, f=cb: f())
            menu.append(item)
        menu.attach_to_widget(self)
        menu.show_all()
        menu.popup_at_pointer(ev)
        self._menu_ref = menu  # mantém vivo enquanto aberto

