"""Conteúdo da ilha: modo compacto (no painel) e expandido (relógio, clima, música)."""
from datetime import date, timedelta

from gi.repository import Gtk, Pango

from widgets import Art, Equalizer, Progress

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def fmt_time(us):
    s = max(0, int(us // 1_000_000))
    return f"{s // 60}:{s % 60:02d}"


def label(cls, xalign=0.0, ellipsize=False):
    lb = Gtk.Label(xalign=xalign)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
        lb.set_max_width_chars(1)
    for c in cls.split():
        lb.get_style_context().add_class(c)
    return lb


def icon(name, size):
    img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    img.set_pixel_size(size)
    return img


def control(icon_name, size, cb, main=False):
    btn = Gtk.Button()
    img = icon(icon_name, size)
    btn.add(img)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_can_focus(False)
    btn.get_style_context().add_class("control")
    if main:
        btn.get_style_context().add_class("main")
    btn.connect("clicked", lambda *_: cb())
    return btn, img


def clock_text(now, h24):
    if h24:
        return now.strftime("%H:%M")
    return f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


def volume_icon(v):
    if v <= 0.001:
        return "audio-volume-muted-symbolic"
    return ("audio-volume-low-symbolic" if v < 0.34 else
            "audio-volume-medium-symbolic" if v < 0.67 else "audio-volume-high-symbolic")


def revealer(child, transition):
    r = Gtk.Revealer()
    r.set_transition_type(transition)
    r.set_transition_duration(260)
    r.add(child)
    return r


def clip(text, n):
    """Corta no Python: a janela segue o tamanho mínimo, então ellipsize não serve aqui."""
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


class Compact(Gtk.Box):
    """Pílula no painel: [capa] hora · data · clima [equalizador].

    Na troca de faixa, o miolo vira "título · artista" por alguns segundos.
    """

    HEIGHT = 28

    def __init__(self):
        super().__init__(spacing=0)
        self.get_style_context().add_class("compact")
        self.set_size_request(-1, self.HEIGHT)
        self.set_margin_start(10)
        self.set_margin_end(12)

        self.art = Art(20, 10)
        art_box = Gtk.Box()
        art_box.set_margin_end(9)
        art_box.add(self.art)
        self.art_rev = revealer(art_box, Gtk.RevealerTransitionType.SLIDE_RIGHT)

        self.clock = label("clock")
        self.date = label("dim")
        self.date.set_margin_start(7)
        self.date_rev = revealer(self.date, Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.date_rev.set_reveal_child(True)
        self.show_weather = True
        self._has_weather = False

        wbox = Gtk.Box(spacing=4)
        wbox.set_margin_start(12)
        self.w_icon = icon("weather-clear-symbolic", 14)
        self.w_temp = label("temp")
        wbox.pack_start(self.w_icon, False, False, 0)
        wbox.pack_start(self.w_temp, False, False, 0)
        self.w_rev = revealer(wbox, Gtk.RevealerTransitionType.SLIDE_LEFT)

        self.eq = Equalizer(14, 12)
        eq_box = Gtk.Box()
        eq_box.set_margin_start(11)
        eq_box.add(self.eq)
        self.eq_rev = revealer(eq_box, Gtk.RevealerTransitionType.SLIDE_LEFT)

        vol = Gtk.Box(spacing=4)
        vol.set_margin_start(10)
        self.vol_icon = icon("audio-volume-high-symbolic", 13)
        self.vol_label = label("temp")
        vol.pack_start(self.vol_icon, False, False, 0)
        vol.pack_start(self.vol_label, False, False, 0)
        self.vol_rev = revealer(vol, Gtk.RevealerTransitionType.SLIDE_LEFT)

        self.dev_icon = icon("phone-symbolic", 13)
        dev_box = Gtk.Box()
        dev_box.set_margin_start(10)
        dev_box.add(self.dev_icon)
        self.dev_rev = revealer(dev_box, Gtk.RevealerTransitionType.SLIDE_LEFT)

        info = Gtk.Box()
        for w in (self.clock, self.date_rev, self.w_rev, self.vol_rev, self.dev_rev):
            info.pack_start(w, False, False, 0)

        track = Gtk.Box(spacing=6)
        self.t_title = label("clock")
        self.t_sep = label("dim")
        self.t_sep.set_text("·")
        self.t_artist = label("dim")
        for w in (self.t_title, self.t_sep, self.t_artist):
            track.pack_start(w, False, False, 0)

        self.middle = Gtk.Stack()
        self.middle.set_homogeneous(False)
        self.middle.set_interpolate_size(True)
        self.middle.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.middle.set_transition_duration(320)
        self.middle.add_named(info, "info")
        self.middle.add_named(track, "track")

        for w in (self.art_rev, self.middle, self.eq_rev):
            self.pack_start(w, False, False, 0)

    def set_track_text(self, title, artist):
        self.t_title.set_text(clip(title, 32))
        self.t_artist.set_text(clip(artist, 22))
        self.t_sep.set_visible(bool(artist))
        self.t_artist.set_visible(bool(artist))

    def show_track(self, visible):
        self.middle.set_visible_child_name("track" if visible else "info")

    def set_clock(self, now, h24=True):
        self.clock.set_text(clock_text(now, h24))
        self.date.set_text(f"{DIAS_CURTOS[now.weekday()]} {now.day} {MESES[now.month - 1][:3]}")

    def set_weather(self, fc):
        self.w_icon.set_from_icon_name(fc.icon, Gtk.IconSize.BUTTON)
        self.w_temp.set_text(f"{fc.temp}°")
        self._has_weather = True
        self.w_rev.set_reveal_child(self.show_weather)

    def set_visibility(self, show_date, show_weather):
        self.date_rev.set_reveal_child(show_date)
        self.show_weather = show_weather
        self.w_rev.set_reveal_child(show_weather and self._has_weather)

    def show_volume(self, v, visible):
        self.vol_icon.set_from_icon_name(volume_icon(v), Gtk.IconSize.BUTTON)
        self.vol_label.set_text(f"{round(v * 100)}%")
        self.vol_rev.set_reveal_child(visible)

    def set_remote_device(self, icon_name):
        """icon_name=None esconde (tocando neste computador ou sem informação)."""
        if icon_name:
            self.dev_icon.set_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        self.dev_rev.set_reveal_child(bool(icon_name))

    def set_music(self, has_track, playing):
        self.art_rev.set_reveal_child(has_track)
        self.eq_rev.set_reveal_child(has_track and playing)
        self.eq.set_playing(playing)


class Expanded(Gtk.Box):
    WIDTH = 420

    def __init__(self, player):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.player = player
        self.set_size_request(self.WIDTH, -1)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(18 if side in ("start", "end") else 14)
        self.pack_start(self._build_header(), False, False, 0)
        self.days_box = Gtk.Box(homogeneous=True)
        self.days_box.set_margin_top(12)
        self.days_rev = revealer(self.days_box, Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.pack_start(self.days_rev, False, False, 0)
        self.music_rev = revealer(self._build_music(), Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.pack_start(self.music_rev, False, False, 0)

    # --- relógio + clima atual -----------------------------------------
    def _build_header(self):
        head = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_valign(Gtk.Align.CENTER)
        self.clock = label("big-clock")
        self.date = label("dim")
        left.pack_start(self.clock, False, False, 0)
        left.pack_start(self.date, False, False, 0)

        right = Gtk.Box(spacing=10)
        right.set_valign(Gtk.Align.CENTER)
        self.w_icon = icon("weather-clear-symbolic", 34)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        info.set_valign(Gtk.Align.CENTER)
        self.w_temp = label("big-temp", 1.0)
        self.w_desc = label("dim small", 1.0)
        self.w_place = label("dim small", 1.0)
        for w in (self.w_temp, self.w_desc, self.w_place):
            info.pack_start(w, False, False, 0)
        right.pack_start(self.w_icon, False, False, 0)
        right.pack_start(info, False, False, 0)
        self.w_rev = revealer(right, Gtk.RevealerTransitionType.CROSSFADE)

        head.pack_start(left, True, True, 0)
        head.pack_end(self.w_rev, False, False, 0)
        return head

    def set_clock(self, now, h24=True):
        self.clock.set_text(clock_text(now, h24))
        self.date.set_text(f"{DIAS[now.weekday()]}, {now.day} de {MESES[now.month - 1]}")

    def set_weather(self, fc):
        self.w_icon.set_from_icon_name(fc.icon, Gtk.IconSize.BUTTON)
        self.w_temp.set_text(f"{fc.temp}°")
        self.w_desc.set_text(f"{fc.desc} · ↑{fc.today_max}° ↓{fc.today_min}°")
        self.w_place.set_text(f"{fc.place} · sensação {fc.feels}°" if fc.place
                              else f"sensação {fc.feels}°")
        self.w_rev.set_reveal_child(True)
        for c in self.days_box.get_children():
            self.days_box.remove(c)
        today = date.today()
        for iso, ic, mx, mn, rain in fc.days:
            d = date.fromisoformat(iso)
            name = "Hoje" if d == today else (
                "Amanhã" if d == today + timedelta(days=1) else DIAS_CURTOS[d.weekday()])
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            col.get_style_context().add_class("day")
            col.pack_start(label("dim small", 0.5), False, False, 0)
            col.get_children()[0].set_text(name)
            col.pack_start(icon(ic, 18), False, False, 0)
            temps = label("small", 0.5)
            temps.set_text(f"{mx}° {mn}°")
            col.pack_start(temps, False, False, 0)
            r = label("rain small", 0.5)
            r.set_text(f"{rain}%" if rain else " ")
            col.pack_start(r, False, False, 0)
            self.days_box.pack_start(col, True, True, 0)
        self.days_box.show_all()
        self.days_rev.set_reveal_child(True)

    # --- Spotify --------------------------------------------------------
    def _build_music(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sep = Gtk.Separator()
        sep.set_margin_top(14)
        sep.set_margin_bottom(6)
        box.pack_start(sep, False, False, 0)

        head = Gtk.Box(spacing=12)
        self.art = Art(52, 12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_valign(Gtk.Align.CENTER)
        self.title = label("title", ellipsize=True)
        self.artist = label("dim", ellipsize=True)
        texts.pack_start(self.title, False, False, 0)
        texts.pack_start(self.artist, False, False, 0)
        texts.pack_start(self._build_playback_row(), False, False, 0)
        self.eq = Equalizer(20, 18)
        head.pack_start(self.art, False, False, 0)
        head.pack_start(texts, True, True, 0)
        head.pack_end(self.eq, False, False, 0)

        bar = Gtk.Box(spacing=8)
        self.t_cur = label("time", 1.0)
        self.t_cur.set_width_chars(5)
        self.t_len = label("time")
        self.t_len.set_width_chars(5)
        self.progress = Progress(lambda f: self.player.seek_to(f))
        bar.pack_start(self.t_cur, False, False, 0)
        bar.pack_start(self.progress, True, True, 0)
        bar.pack_start(self.t_len, False, False, 0)

        ctrls = Gtk.Box(spacing=18)
        ctrls.set_halign(Gtk.Align.CENTER)
        prev, _ = control("media-skip-backward-symbolic", 20, lambda: self.player.previous())
        play, self.play_img = control("media-playback-start-symbolic", 26,
                                      lambda: self.player.play_pause(), main=True)
        nxt, _ = control("media-skip-forward-symbolic", 20, lambda: self.player.next())
        for b in (prev, play, nxt):
            ctrls.pack_start(b, False, False, 0)

        vol = Gtk.Box(spacing=8)
        vol.set_margin_start(4)
        mute, self.vol_img = control("audio-volume-high-symbolic", 15,
                                     lambda: self.player.toggle_mute())
        self.vol_bar = Progress(lambda f: self.player.set_volume(f), height=14, live=True)
        self.vol_pct = label("time")
        self.vol_pct.set_width_chars(5)
        vol.pack_start(mute, False, False, 0)
        vol.pack_start(self.vol_bar, True, True, 0)
        vol.pack_start(self.vol_pct, False, False, 0)

        for w in (head, bar, ctrls, vol):
            box.pack_start(w, False, False, 0)
        return box

    def set_volume(self, v):
        self.vol_img.set_from_icon_name(volume_icon(v), Gtk.IconSize.BUTTON)
        self.vol_bar.set_fraction(v)
        self.vol_pct.set_text(f"{round(v * 100)}%")

    def _build_playback_row(self):
        row = Gtk.Box(spacing=5)
        row.set_margin_top(3)
        self.ctx_box = Gtk.Box(spacing=5)
        self.ctx_icon = icon("view-list-symbolic", 11)
        self.ctx_label = label("dim small", ellipsize=True)
        self.ctx_label.set_max_width_chars(26)
        self.ctx_box.pack_start(self.ctx_icon, False, False, 0)
        self.ctx_box.pack_start(self.ctx_label, True, True, 0)
        self.pb_sep = label("dim small")
        self.pb_sep.set_text("·")
        dev = Gtk.Box(spacing=5)
        self.pb_dev_icon = icon("computer-symbolic", 11)
        self.pb_dev_label = label("dim small", ellipsize=True)
        self.pb_dev_label.set_max_width_chars(18)
        dev.pack_start(self.pb_dev_icon, False, False, 0)
        dev.pack_start(self.pb_dev_label, True, True, 0)
        row.pack_start(self.ctx_box, False, False, 0)
        row.pack_start(self.pb_sep, False, False, 0)
        row.pack_start(dev, False, False, 0)
        self.pb_rev = revealer(row, Gtk.RevealerTransitionType.SLIDE_DOWN)
        return self.pb_rev

    def set_playback(self, pb):
        """pb: spotify_web.Playback ou None (sem Web API ou nada tocando)."""
        if pb is None:
            self.pb_rev.set_reveal_child(False)
            return
        has_ctx = bool(pb.context_name)
        self.ctx_box.set_visible(has_ctx)
        self.pb_sep.set_visible(has_ctx)
        if has_ctx:
            self.ctx_icon.set_from_icon_name(pb.context_icon, Gtk.IconSize.BUTTON)
            self.ctx_label.set_text(pb.context_name)
        self.pb_dev_icon.set_from_icon_name(pb.device_icon, Gtk.IconSize.BUTTON)
        self.pb_dev_label.set_text(pb.device)
        self.pb_rev.set_reveal_child(True)

    def set_track(self, track):
        if track:
            self.title.set_text(track.title)
            self.artist.set_text(track.artist)
            self.t_len.set_text(fmt_time(track.length))
        self.music_rev.set_reveal_child(track is not None)

    def set_playing(self, playing):
        self.eq.set_playing(playing)
        name = "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        self.play_img.set_from_icon_name(name, Gtk.IconSize.BUTTON)

    def set_position(self, pos, length):
        self.t_cur.set_text(fmt_time(pos))
        self.progress.set_fraction(pos / length if length else 0)
