"""Widgets desenhados com cairo: capa arredondada, equalizador e barra de progresso."""
import math
import time

from gi.repository import Gdk, GdkPixbuf, Gtk

DEFAULT_ACCENT = (0.12, 0.84, 0.38)  # verde Spotify


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def accent_from_pixbuf(pb):
    """Cor de destaque: média da capa, clareada para ler bem sobre preto."""
    if pb is None:
        return DEFAULT_ACCENT
    tiny = pb.scale_simple(1, 1, GdkPixbuf.InterpType.BILINEAR)
    r, g, b = (c / 255 for c in tiny.get_pixels()[:3])
    mx = max(r, g, b, 1e-3)
    if mx < 0.55:  # capas escuras: puxa o brilho para cima
        k = 0.55 / mx
        r, g, b = min(r * k, 1), min(g * k, 1), min(b * k, 1)
    return (r, g, b)


class Art(Gtk.DrawingArea):
    def __init__(self, size, radius):
        super().__init__()
        self.size, self.radius = size, radius
        self.pixbuf = None
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_source(self, original):
        self.pixbuf = (original.scale_simple(self.size * 2, self.size * 2,
                                             GdkPixbuf.InterpType.BILINEAR)
                       if original else None)
        self.queue_draw()

    def _draw(self, _w, cr):
        s = self.size
        rounded_rect(cr, 0, 0, s, s, self.radius)
        cr.clip()
        if self.pixbuf:
            cr.scale(0.5, 0.5)
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
        else:
            cr.set_source_rgb(0.18, 0.18, 0.18)
            cr.paint()
            cr.set_source_rgb(*DEFAULT_ACCENT)
            cr.arc(s / 2, s / 2, s / 6, 0, 2 * math.pi)
            cr.fill()


class Equalizer(Gtk.DrawingArea):
    """Barrinhas animadas enquanto toca; paradas e baixas em pausa."""

    BARS = 4

    def __init__(self, w=18, h=14):
        super().__init__()
        self.w, self.h = w, h
        self.accent = DEFAULT_ACCENT
        self.playing = False
        self._tick = None
        self.set_size_request(w, h)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_playing(self, playing):
        self.playing = playing
        if playing and self._tick is None:
            self._tick = self.add_tick_callback(lambda *_a: self.queue_draw() or True)
        elif not playing and self._tick is not None:
            self.remove_tick_callback(self._tick)
            self._tick = None
        self.queue_draw()

    def _draw(self, _w, cr):
        t = time.monotonic()
        gap = 2
        bw = (self.w - gap * (self.BARS - 1)) / self.BARS
        cr.set_source_rgb(*self.accent)
        for i in range(self.BARS):
            if self.playing:
                lvl = 0.35 + 0.65 * abs(math.sin(t * (3.1 + i * 1.7) + i * 1.3))
            else:
                lvl = 0.22
            bh = max(bw, self.h * lvl)
            rounded_rect(cr, i * (bw + gap), (self.h - bh) / 2, bw, bh, bw / 2)
            cr.fill()


class Progress(Gtk.DrawingArea):
    """Barra de progresso clicável/arrastável. on_seek(fração)."""

    def __init__(self, on_seek, height=16, live=False):
        super().__init__()
        self.on_seek = on_seek
        self.live = live  # chama on_seek enquanto arrasta (ex.: volume)
        self.fraction = 0.0
        self.accent = DEFAULT_ACCENT
        self.fg = (1, 1, 1)
        self._drag = None
        self._hover = False
        self.set_size_request(-1, height)
        self.set_hexpand(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)
        self.connect("enter-notify-event", lambda *_a: self._set_hover(True))
        self.connect("leave-notify-event", lambda *_a: self._set_hover(False))

    def _set_hover(self, v):
        self._hover = v
        self.queue_draw()

    def set_fraction(self, f):
        if self._drag is None:
            self.fraction = max(0.0, min(1.0, f))
            self.queue_draw()

    def _frac_at(self, x):
        return max(0.0, min(1.0, x / max(1, self.get_allocated_width())))

    def _press(self, _w, ev):
        if ev.button == 1:
            self._drag = self._frac_at(ev.x)
            if self.live:
                self.on_seek(self._drag)
            self.queue_draw()
        return True

    def _motion(self, _w, ev):
        if self._drag is not None:
            self._drag = self._frac_at(ev.x)
            if self.live:
                self.on_seek(self._drag)
            self.queue_draw()
        return True

    def _release(self, _w, ev):
        if self._drag is not None:
            self.fraction = self._drag
            self._drag = None
            self.on_seek(self.fraction)
            self.queue_draw()
        return True

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        active = self._hover or self._drag is not None
        th = 6 if active else 4
        y = (h - th) / 2
        f = self._drag if self._drag is not None else self.fraction
        cr.set_source_rgba(*self.fg, 0.18)
        rounded_rect(cr, 0, y, w, th, th / 2)
        cr.fill()
        if f > 0:
            cr.set_source_rgb(*self.accent)
            rounded_rect(cr, 0, y, max(th, w * f), th, th / 2)
            cr.fill()
        if active:
            cr.set_source_rgb(*self.fg)
            cr.arc(min(max(w * f, 6), w - 6), h / 2, 6, 0, 2 * math.pi)
            cr.fill()
