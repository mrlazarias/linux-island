"""Página "Hidratação" da ilha expandida."""
import math

from gi.repository import Gtk

from views import control, label

WATER_BLUE = (0.16, 0.62, 0.96)


def drop_path(cr, x, y, w, h):
    """Gota com a ponta para cima, dentro do retângulo (x, y, w, h)."""
    r = w / 2
    cx, cy = x + r, y + h - r
    cr.move_to(cx, y)
    cr.curve_to(cx + r * 0.2, y + h * 0.25, cx + r, cy - r * 0.55, cx + r, cy)
    cr.arc(cx, cy, r, 0, math.pi)
    cr.curve_to(cx - r, cy - r * 0.55, cx - r * 0.2, y + h * 0.25, cx, y)
    cr.close_path()


class Drops(Gtk.DrawingArea):
    """Uma gota por copo da meta; as tomadas ficam cheias."""

    W, H, GAP, PER_ROW = 11, 15, 6, 8

    def __init__(self):
        super().__init__()
        self.total, self.filled = 8, 0
        self.fg = (1, 1, 1)
        self.connect("draw", self._draw)
        self._resize()

    def _resize(self):
        rows = math.ceil(self.total / self.PER_ROW)
        cols = min(self.total, self.PER_ROW)
        self.set_size_request(cols * (self.W + self.GAP) - self.GAP,
                              rows * (self.H + self.GAP) - self.GAP)

    def set(self, total, filled):
        if total != self.total:
            self.total = total
            self._resize()
        self.filled = filled
        self.queue_draw()

    def _draw(self, _w, cr):
        for i in range(self.total):
            x = (i % self.PER_ROW) * (self.W + self.GAP)
            y = (i // self.PER_ROW) * (self.H + self.GAP)
            drop_path(cr, x + 0.5, y + 0.5, self.W - 1, self.H - 1)
            if i < self.filled:
                cr.set_source_rgb(*WATER_BLUE)
                cr.fill()
            else:
                cr.set_source_rgba(*self.fg, 0.25)
                cr.set_line_width(1.2)
                cr.stroke()


class DropIcon(Gtk.DrawingArea):
    def __init__(self, size=16):
        super().__init__()
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", lambda _w, cr: (
            drop_path(cr, size * 0.18, 0, size * 0.64, size), cr.set_source_rgb(*WATER_BLUE),
            cr.fill()))


class Ring(Gtk.DrawingArea):
    """Anel de progresso da meta do dia."""

    def __init__(self, size=112, width=9):
        super().__init__()
        self.size, self.width = size, width
        self.fraction = 0.0
        self.fg = (1, 1, 1)
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def set_fraction(self, f):
        self.fraction = max(0.0, min(1.0, f))
        self.queue_draw()

    def _draw(self, _w, cr):
        c = self.size / 2
        r = c - self.width / 2 - 1
        cr.set_line_width(self.width)
        cr.set_source_rgba(*self.fg, 0.12)
        cr.arc(c, c, r, 0, 2 * math.pi)
        cr.stroke()
        if self.fraction > 0:
            cr.set_line_cap(1)  # ROUND
            cr.set_source_rgb(*WATER_BLUE)
            start = -math.pi / 2
            cr.arc(c, c, r, start, start + 2 * math.pi * self.fraction)
            cr.stroke()


class WaterPage(Gtk.Box):
    WIDTH = 420

    def __init__(self, water):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.water = water
        self.set_size_request(self.WIDTH, -1)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(18 if side in ("start", "end") else 14)

        head = Gtk.Box(spacing=8)
        head.pack_start(DropIcon(18), False, False, 0)
        title = label("title")
        title.set_text("Hidratação")
        head.pack_start(title, False, False, 0)
        self.status = label("dim small", 1.0)
        head.pack_end(self.status, True, True, 0)
        self.pack_start(head, False, False, 0)

        body = Gtk.Box(spacing=18)
        overlay = Gtk.Overlay()
        self.ring = Ring()
        overlay.add(self.ring)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        self.amount = label("big-temp", 0.5)
        self.goal = label("dim small", 0.5)
        center.pack_start(self.amount, False, False, 0)
        center.pack_start(self.goal, False, False, 0)
        overlay.add_overlay(center)
        body.pack_start(overlay, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_valign(Gtk.Align.CENTER)
        self.drops = Drops()
        self.drops.set_halign(Gtk.Align.START)
        right.pack_start(self.drops, False, False, 0)

        actions = Gtk.Box(spacing=8)
        self.drink_btn = Gtk.Button()
        self.drink_btn.get_style_context().add_class("water-main")
        self.drink_btn.set_can_focus(False)
        self.drink_btn.connect("clicked", lambda *_: self.water.drink())
        undo, _ = control("edit-undo-symbolic", 16, lambda: self.water.undo())
        undo.set_tooltip_text("Desfazer um copo")
        actions.pack_start(self.drink_btn, False, False, 0)
        actions.pack_start(undo, False, False, 0)
        right.pack_start(actions, False, False, 0)

        self.snooze_btn = Gtk.Button()
        self.snooze_btn.get_style_context().add_class("water-snooze")
        self.snooze_btn.set_can_focus(False)
        self.snooze_btn.set_halign(Gtk.Align.START)
        self.snooze_btn.connect("clicked", lambda *_: self.water.snooze())
        self.snooze_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.snooze_rev.add(self.snooze_btn)
        right.pack_start(self.snooze_rev, False, False, 0)

        body.pack_start(right, True, True, 0)
        self.pack_start(body, False, False, 0)

    def update(self, cfg):
        w = self.water
        goal, cup = cfg["water_goal_ml"], cfg["water_cup_ml"]
        consumed = w.consumed
        self.ring.set_fraction(consumed / goal if goal else 0)
        self.amount.set_text(f"{consumed}")
        self.goal.set_text(f"de {goal} ml")
        self.status.set_text(w.status())
        self.drink_btn.set_label(f"+{cup} ml")
        self.snooze_btn.set_label(f"Adiar {cfg['water_snooze_min']} min")
        self.snooze_rev.set_reveal_child(w.alerting)

        cups = max(1, min(16, round(goal / cup)))
        self.drops.set(cups, min(cups, round(consumed / goal * cups) if goal else 0))

    def set_fg(self, fg):
        self.ring.fg = self.drops.fg = fg
        self.ring.queue_draw()
        self.drops.queue_draw()
