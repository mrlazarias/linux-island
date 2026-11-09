#!/usr/bin/env python3
"""linux-island: "dynamic island" para Wayland (layer-shell) no lugar do relógio do painel.

Mostra hora, data, clima e o Spotify; expande ao passar o mouse.
"""
import argparse
import os
import sys
import time
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except (ValueError, ImportError):
    sys.exit("gtk-layer-shell não encontrado. Rode pelo run.sh ou instale "
             "gir1.2-gtklayershell-0.1")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from spotify import Spotify  # noqa: E402
from views import Compact, Expanded  # noqa: E402
from weather import Weather  # noqa: E402
from widgets import accent_from_pixbuf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEBUG = bool(os.environ.get("ISLAND_DEBUG"))


def log(*a):
    if DEBUG:
        print(f"[island {time.monotonic():.2f}]", *a, flush=True)
TRANSITION_MS = 320
HOVER_DELAY_MS = 120   # evita abrir só de passar o mouse pelo painel
COLLAPSE_DELAY_MS = 700  # tolera leaves espúrios do compositor
PEEK_MS = 3000         # quanto tempo abre sozinha quando a faixa muda


class Island(Gtk.Window):
    def __init__(self, args):
        super().__init__(title="linux-island")
        self._setup_surface(args)
        self.expanded = False
        self.hovered = False
        self._timers = {}
        self._resize_tick = None
        self._last_click = None
        self._closed_by_click = False
        self._sync_counter = 0
        self._minute = None

        self.player = Spotify(self._on_presence, self._on_track,
                              self._on_status, self._on_art)
        self._build()
        self._tick_clock()
        self.show_all()
        self.weather = Weather(self._on_weather, args.city)
        GLib.timeout_add(250, self._tick_music)
        GLib.timeout_add(1000, self._tick_clock)

    # --- superfície layer-shell ----------------------------------------
    def _setup_surface(self, args):
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "linux-island")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, args.margin)
        # -1: ignora a zona exclusiva do painel e fica por cima dele, no lugar do relógio
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # --- layout ---------------------------------------------------------
    def _build(self):
        # Eventos na própria janela: o Gtk.Stack tem GdkWindow própria, então
        # cliques sobem direto para a janela e um EventBox no meio não os vê.
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("enter-notify-event", self._enter)
        self.connect("leave-notify-event", self._leave)
        self.connect("button-press-event", self._click)

        # Sem margem transparente em volta: no Wayland/GTK3 a região de input
        # não funciona aqui, e qualquer área transparente bloquearia cliques.
        self.shell = Gtk.Box()
        self.shell.get_style_context().add_class("island")
        self.add(self.shell)

        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(False)
        self.stack.set_interpolate_size(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(TRANSITION_MS)
        self.shell.pack_start(self.stack, True, True, 0)

        self.compact = Compact()
        self.full = Expanded(self.player)
        self.stack.add_named(self.compact, "compact")
        self.stack.add_named(self.full, "expanded")
        self.stack.set_visible_child_name("compact")

    # --- tamanho --------------------------------------------------------
    def _follow_size(self):
        """Janelas GTK3 não encolhem sozinhas: acompanha as animações de tamanho."""
        if self._resize_tick is not None:
            self.remove_tick_callback(self._resize_tick)
        start = GLib.get_monotonic_time()

        def step(_w, _clock):
            self.resize(1, 1)
            if GLib.get_monotonic_time() - start > (TRANSITION_MS + 120) * 1000:
                self._resize_tick = None
                return False
            return True

        self._resize_tick = self.add_tick_callback(step)

    def set_expanded(self, value):
        if value == self.expanded:
            return
        self.expanded = value
        log("expanded", value)
        ctx = self.shell.get_style_context()
        (ctx.add_class if value else ctx.remove_class)("expanded")
        self.stack.set_visible_child_name("expanded" if value else "compact")
        self._follow_size()
        if value:
            self._tick_music()

    # --- mouse ----------------------------------------------------------
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
        self.hovered = self._pointer_inside()
        log("hover?", self.hovered)
        if not self.hovered:
            self._closed_by_click = False
        if self.hovered:
            self._cancel("peek")
            self._cancel("collapse")
            if not self.expanded and not self._closed_by_click:
                self._later("expand", HOVER_DELAY_MS,
                            lambda: self._pointer_inside() and self.set_expanded(True))
        else:
            self._cancel("expand")
            if self.expanded and "peek" not in self._timers:
                self._later("collapse", COLLAPSE_DELAY_MS,
                            lambda: self._pointer_inside() or self.set_expanded(False))

    def _enter(self, _w, ev):
        log("enter", ev.detail.value_nick)
        # adia para o próximo ciclo: o GDK atualiza o foco do ponteiro depois do evento
        self._later("hover", 30, self._recheck_hover)

    def _leave(self, _w, ev):
        log("leave", ev.detail.value_nick)
        self._later("hover", 30, self._recheck_hover)

    def _click(self, _w, ev):
        if ev.time == self._last_click:  # o mesmo clique chega duas vezes
            return False
        self._last_click = ev.time
        log("click", ev.button)
        if ev.button == 1:  # clique numa área livre alterna aberta/fechada
            for t in ("expand", "collapse", "peek"):
                self._cancel(t)
            self._closed_by_click = self.expanded
            self.set_expanded(not self.expanded)
        elif ev.button == 3:  # botão direito: traz o Spotify para frente
            self.player.raise_window()
        elif ev.button == 2:
            self.player.play_pause()
        return False

    def _peek(self):
        if self.hovered:
            return
        self.set_expanded(True)
        self._later("peek", PEEK_MS, lambda: self.hovered or self.set_expanded(False))

    # --- relógio e clima ------------------------------------------------
    def _tick_clock(self):
        now = datetime.now()
        if now.minute != self._minute:
            self._minute = now.minute
            self.compact.set_clock(now)
            self.full.set_clock(now)
            self._follow_size()
        return True

    def _on_weather(self, fc):
        self.compact.set_weather(fc)
        self.full.set_weather(fc)
        self._follow_size()

    # --- Spotify --------------------------------------------------------
    def _on_presence(self, present):
        if not present:
            self._on_track(None)
            self._on_status(False)

    def _on_track(self, track):
        prev = self.full.title.get_text() if self.full.music_rev.get_reveal_child() else ""
        self.full.set_track(track)
        self.compact.set_music(track is not None, self.player.playing)
        self._follow_size()
        if track and prev and prev != track.title:
            self._peek()

    def _on_status(self, playing):
        self.compact.set_music(self.player.track is not None, playing)
        self.full.set_playing(playing)
        self._follow_size()

    def _on_art(self, path):
        pb = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
            except GLib.Error as e:
                print(f"[island] capa inválida: {e.message}")
        self.compact.art.set_source(pb)
        self.full.art.set_source(pb)
        accent = accent_from_pixbuf(pb)
        for w in (self.compact.eq, self.full.eq, self.full.progress):
            w.accent = accent
            w.queue_draw()

    def _tick_music(self):
        p = self.player
        if p.track:
            if p.playing:
                self._sync_counter += 1
                if self._sync_counter % 12 == 0:  # ressincroniza a cada ~3s
                    p.sync_position()
            if self.expanded:
                self.full.set_position(p.position(), p.track.length)
        return True


def main():
    ap = argparse.ArgumentParser(description="Dynamic island para Linux")
    ap.add_argument("--margin", type=int, default=2, help="distância do topo em px")
    ap.add_argument("--city", help="cidade para o clima (padrão: detecta pelo IP)")
    args = ap.parse_args()
    win = Island(args)
    win.connect("destroy", Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, lambda: Gtk.main_quit() or False)   # INT
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, lambda: Gtk.main_quit() or False)  # TERM
    Gtk.main()


if __name__ == "__main__":
    main()
