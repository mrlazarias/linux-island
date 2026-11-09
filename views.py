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


def revealer(child, transition):
    r = Gtk.Revealer()
    r.set_transition_type(transition)
    r.set_transition_duration(260)
    r.add(child)
    return r


class Compact(Gtk.Box):
    """Pílula no painel: [capa] hora · data · clima [equalizador]."""

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

        for w in (self.art_rev, self.clock, self.date, self.w_rev, self.eq_rev):
            self.pack_start(w, False, False, 0)

    def set_clock(self, now):
        self.clock.set_text(now.strftime("%H:%M"))
        self.date.set_text(f"{DIAS_CURTOS[now.weekday()]} {now.day} {MESES[now.month - 1][:3]}")

    def set_weather(self, fc):
        self.w_icon.set_from_icon_name(fc.icon, Gtk.IconSize.BUTTON)
        self.w_temp.set_text(f"{fc.temp}°")
        self.w_rev.set_reveal_child(True)

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

    def set_clock(self, now):
        self.clock.set_text(now.strftime("%H:%M"))
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

        for w in (head, bar, ctrls):
            box.pack_start(w, False, False, 0)
        return box

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
