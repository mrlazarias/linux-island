#!/usr/bin/env python3
"""linux-island: "dynamic island" para Wayland (layer-shell) no lugar do relógio do painel.

Mostra hora, data, clima e o Spotify; expande ao passar o mouse.
"""
import os
import socket
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

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from config import Config, accent_tuple, build_css, rgba  # noqa: E402
from settings import Settings  # noqa: E402
from spotify import Spotify  # noqa: E402
from spotify_web import SpotifyWeb  # noqa: E402
from views import Compact, Expanded  # noqa: E402
from weather import Weather  # noqa: E402
from widgets import accent_from_pixbuf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEBUG = bool(os.environ.get("ISLAND_DEBUG"))


def log(*a):
    if DEBUG:
        print(f"[island {time.monotonic():.2f}]", *a, flush=True)


APP_ID = "io.github.mrlazarias.LinuxIsland"
TRANSITION_MS = 320
COLLAPSE_DELAY_MS = 700  # tolera leaves espúrios do compositor
VOLUME_STEP = 0.05     # 5% por "clique" da roda do mouse
PEEK_MS = 4000         # quanto tempo a pílula mostra a faixa nova


class Island(Gtk.Window):
    def __init__(self, app, cfg):
        super().__init__(title="linux-island")
        self.app = app
        self.cfg = cfg
        self._art_accent = None
        self._setup_surface()
        self.expanded = False
        self.hovered = False
        self._timers = {}
        self._resize_tick = None
        self._last_click = None
        self._closed_by_click = False
        self._sync_counter = 0
        self._minute = None

        self.player = Spotify(self._on_presence, self._on_track,
                              self._on_status, self._on_art, self._on_volume)
        self._last_scroll = None
        self._scroll_acc = 0.0
        self._last_discrete = None
        self._build()
        self.weather = Weather(self._on_weather, cfg["city"], cfg["units"])
        self.web_status = ("Conectado", True)
        self.web = SpotifyWeb(cfg["spotify_client_id"], self._on_playback, self._on_web_status)
        if not self.web.connected:
            self.web_status = ("Não conectado", False)
        self._apply()
        cfg.connect(self._apply)
        self.show_all()
        GLib.timeout_add(250, self._tick_music)
        GLib.timeout_add(1000, self._tick_clock)

    # --- superfície layer-shell ----------------------------------------
    def _setup_surface(self):
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "linux-island")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        # -1: ignora a zona exclusiva do painel e fica por cima dele, no lugar do relógio
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.get_style_context().add_class("island-window")

        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # cores e cantos vindos da configuração, por cima do style.css
        self.dyn_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.dyn_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    # --- configuração ---------------------------------------------------
    def _apply(self, key=None):
        """Aplica a configuração inteira (key=None) ou só o que mudou."""
        cfg = self.cfg
        look = ("bg_color", "text_color", "border", "radius_expanded")
        if key is None or key in look:
            self.dyn_css.load_from_data(build_css(cfg).encode())
            fg = rgba(cfg["text_color"])
            for bar in (self.full.progress, self.full.vol_bar):
                bar.fg = (fg.red, fg.green, fg.blue)
                bar.queue_draw()
        if key is None or key in ("accent_auto", "accent_color"):
            self._apply_accent()
        if key is None or key == "clock_24h":
            self._minute = None
            self._tick_clock()
        if key is None or key in ("show_date", "show_weather"):
            self.compact.set_visibility(cfg["show_date"], cfg["show_weather"])
        if key in ("city", "units"):
            self.weather.configure(cfg["city"], cfg["units"])
        if key == "spotify_client_id":
            self.web.set_client_id(cfg["spotify_client_id"])
        if key is None or key == "margin_top":
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, cfg["margin_top"])
        self._follow_size()

    def _apply_accent(self):
        if self.cfg["accent_auto"] and self._art_accent:
            accent = self._art_accent
        elif self.cfg["accent_auto"]:
            accent = accent_from_pixbuf(None)
        else:
            accent = accent_tuple(self.cfg["accent_color"])
        for w in (self.compact.eq, self.full.eq, self.full.progress, self.full.vol_bar):
            w.accent = accent
            w.queue_draw()

    # --- layout ---------------------------------------------------------
    def _build(self):
        # Eventos na própria janela: o Gtk.Stack tem GdkWindow própria, então
        # cliques sobem direto para a janela e um EventBox no meio não os vê.
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                        | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("scroll-event", self._scroll)
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
        if value:  # ao expandir, a pílula volta ao relógio para quando fechar
            self._cancel("track_peek")
            self.compact.show_track(False)
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
            self._cancel("collapse")
            if not self.expanded and not self._closed_by_click and self.cfg["hover_expand"]:
                self._later("expand", self.cfg["hover_delay_ms"],
                            lambda: self._pointer_inside() and self.set_expanded(True))
        else:
            self._cancel("expand")
            if self.expanded:
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
            for t in ("expand", "collapse"):
                self._cancel(t)
            self._closed_by_click = self.expanded
            self.set_expanded(not self.expanded)
        elif ev.button == 3:
            self._menu(ev)
        elif ev.button == 2:
            self.player.play_pause()
        return False

    def _scroll(self, _w, ev):
        """Rolagem em qualquer ponto da ilha muda o volume do Spotify."""
        if not self.cfg["scroll_volume"] or not self.player.proxy:
            return False
        ok, dx, dy = ev.get_scroll_deltas()
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
        items = [("Configurações…", self.app.open_settings)]
        if self.player.proxy:
            items.append(("Abrir o Spotify", self.player.raise_window))
        items += [(None, None), ("Sair", self.app.quit)]
        for text, cb in items:
            item = Gtk.SeparatorMenuItem() if text is None else Gtk.MenuItem(label=text)
            if cb:
                item.connect("activate", lambda _i, f=cb: f())
            menu.append(item)
        menu.attach_to_widget(self)
        menu.show_all()
        menu.popup_at_pointer(ev)
        self._menu_ref = menu  # mantém vivo enquanto aberto

    def _peek(self):
        """Faixa nova: a pílula se estica na horizontal com título · artista e volta."""
        if self.expanded or not self.cfg["peek_on_track"]:
            return
        self.compact.show_track(True)
        self._follow_size()
        self._later("track_peek", PEEK_MS, self._end_peek)

    def _end_peek(self):
        self.compact.show_track(False)
        self._follow_size()

    # --- relógio e clima ------------------------------------------------
    def _tick_clock(self):
        now = datetime.now()
        if now.minute != self._minute:
            self._minute = now.minute
            self.compact.set_clock(now, self.cfg["clock_24h"])
            self.full.set_clock(now, self.cfg["clock_24h"])
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
        if track:
            self.compact.set_track_text(track.title, track.artist)
        self.compact.set_music(track is not None, self.player.playing)
        self._follow_size()
        self.web.kick()
        if track and prev and prev != track.title:
            self._peek()

    def _on_status(self, playing):
        self.compact.set_music(self.player.track is not None, playing)
        self.full.set_playing(playing)
        self._follow_size()
        self.web.kick()

    # --- Spotify Web API (playlist e dispositivo) -----------------------
    def _on_playback(self, pb):
        self.full.set_playback(pb)
        remote = pb is not None and pb.is_playing and not self._is_this_computer(pb)
        self.compact.set_remote_device(pb.device_icon if remote else None)
        self._follow_size()

    @staticmethod
    def _is_this_computer(pb):
        # o app de desktop se registra com o hostname como nome do dispositivo
        return pb.device_type == "computer" and pb.device.lower() == socket.gethostname().lower()

    def _on_web_status(self, text, ok):
        self.web_status = (text, ok)
        if self.app.settings:
            self.app.settings.set_spotify_status(text, ok)

    def _on_art(self, path):
        pb = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
            except GLib.Error as e:
                print(f"[island] capa inválida: {e.message}")
        self.compact.art.set_source(pb)
        self.full.art.set_source(pb)
        self._art_accent = accent_from_pixbuf(pb) if pb else None
        self._apply_accent()

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


class App(Gtk.Application):
    """Instância única: rodar de novo (ex.: --settings) fala com a que já existe."""

    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.island = None
        self.settings = None
        self.add_main_option("settings", ord("s"), GLib.OptionFlags.NONE,
                             GLib.OptionArg.NONE, "Abre as configurações", None)
        self.add_main_option("city", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Cidade do clima só nesta execução", "CIDADE")
        self.add_main_option("margin", 0, GLib.OptionFlags.NONE, GLib.OptionArg.INT,
                             "Distância do topo só nesta execução", "PX")

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        log("command line", opts, "remota" if cmdline.get_is_remote() else "local")
        if self.island is None:
            margin = opts.get("margin")
            cfg = Config({"city": opts.get("city"),
                          "margin_top": margin if margin is not None and 0 <= margin <= 200
                          else None})
            self.island = Island(self, cfg)
            self.add_window(self.island)
        if opts.get("settings"):
            self.open_settings()
        return 0

    def open_settings(self):
        log("open_settings", self.settings)
        if self.settings is None:
            self.settings = Settings(self.island.cfg, self, self.island.web)
            self.settings.set_spotify_status(*self.island.web_status)
            self.settings.connect("destroy", lambda *_: setattr(self, "settings", None))
        self.settings.present()


def main():
    app = App()
    for sig in (2, 15):  # SIGINT, SIGTERM
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: app.quit() or False)
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
