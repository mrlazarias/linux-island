"""Página "Agenda" da ilha expandida e o aviso de reunião na pílula."""
from datetime import datetime

from gi.repository import Gio, Gtk

from agenda import countdown, upcoming
from i18n import _
from views import clip, icon, label

MAX_ROWS = 7
CAL_ICON = "x-office-calendar-symbolic"
VIDEO_ICON = "camera-video-symbolic"


def open_url(url):
    if url and url.startswith("https://"):
        Gio.AppInfo.launch_default_for_uri(url, None)


def pill_button(text, icon_name, cb, cls="water-main"):
    btn = Gtk.Button()
    box = Gtk.Box(spacing=6)
    if icon_name:
        box.pack_start(icon(icon_name, 14), False, False, 0)
    lb = Gtk.Label(label=text)
    box.pack_start(lb, False, False, 0)
    btn.add(box)
    btn.set_can_focus(False)
    btn.get_style_context().add_class(cls)
    btn.connect("clicked", lambda *_a: cb())
    return btn


class MeetingPill(Gtk.Box):
    """Miolo da pílula quando uma reunião está chegando."""

    def __init__(self):
        super().__init__(spacing=8)
        self.pack_start(icon(CAL_ICON, 14), False, False, 0)
        self.title = label("clock")
        self.when = label("dim")
        self.video = icon(VIDEO_ICON, 14)
        for w in (self.title, self.when, self.video):
            self.pack_start(w, False, False, 0)

    def update(self, ev, now):
        self.title.set_text(clip(ev["title"], 28))
        self.when.set_text(countdown(now, ev))
        self.video.set_visible(bool(ev["meet"]))


class AgendaPage(Gtk.Box):
    WIDTH = 420

    def __init__(self, agenda, open_settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.agenda = agenda
        self.open_settings = open_settings
        self.set_size_request(self.WIDTH, -1)
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(18 if side in ("start", "end") else 14)

        head = Gtk.Box(spacing=8)
        head.pack_start(icon(CAL_ICON, 16), False, False, 0)
        title = label("title")
        title.set_text(_("Agenda"))
        head.pack_start(title, False, False, 0)
        self.status = label("dim small", 1.0)
        head.pack_end(self.status, True, True, 0)
        self.pack_start(head, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.pack_start(self.body, False, False, 0)

    # --- conteúdo ---------------------------------------------------------
    def update(self, cfg):
        for c in self.body.get_children():
            self.body.remove(c)
        now = datetime.now().astimezone()
        a = self.agenda
        if not a.connected:
            self.status.set_text("")
            self._empty(_("Entre com sua conta do Google para ver seus eventos."),
                        pill_button(_("Configurar"), "preferences-system-symbolic",
                                    self.open_settings, "water-snooze"))
        else:
            self.status.set_text(_("atualizado {hora}").format(hora=f"{datetime.now():%H:%M}")
                                 if a.status[1] else _("sem conexão"))
            groups = upcoming(now, a.events, cfg["agenda_days"])
            if a.alert:
                self.body.pack_start(self._next_card(a.alert, now), False, False, 4)
            if not groups:
                self._empty(_("Nada na agenda nos próximos dias."), None)
            rows = 0
            for day, events in groups:
                if rows >= MAX_ROWS:
                    break
                d = label("dim small")
                d.set_text(day.upper())
                d.set_margin_top(6)
                self.body.pack_start(d, False, False, 0)
                for ev in events:
                    if rows >= MAX_ROWS:
                        break
                    self.body.pack_start(self._row(ev, now), False, False, 0)
                    rows += 1
        self.body.show_all()

    def _empty(self, text, button):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(6)
        lb = label("dim", 0.5)
        lb.set_text(text)
        box.pack_start(lb, False, False, 0)
        if button:
            button.set_halign(Gtk.Align.CENTER)
            box.pack_start(button, False, False, 0)
        self.body.pack_start(box, False, False, 0)

    def _next_card(self, ev, now):
        card = Gtk.Box(spacing=12)
        card.get_style_context().add_class("day")
        for side in ("start", "end"):
            getattr(card, f"set_margin_{side}")(0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_margin_start(12)
        t = label("title")
        t.set_text(clip(ev["title"], 30))
        w = label("dim small")
        w.set_text(f"{ev['start']:%H:%M}–{ev['end']:%H:%M} · {countdown(now, ev)}")
        texts.pack_start(t, False, False, 0)
        texts.pack_start(w, False, False, 0)
        card.pack_start(texts, True, True, 0)
        actions = Gtk.Box(spacing=6)
        actions.set_margin_end(10)
        actions.set_valign(Gtk.Align.CENTER)
        if ev["meet"]:
            actions.pack_start(pill_button(_("Entrar"), VIDEO_ICON, lambda: (
                open_url(ev["meet"]), self.agenda.dismiss())), False, False, 0)
        actions.pack_start(pill_button(_("Dispensar"), None, self.agenda.dismiss, "water-snooze"),
                           False, False, 0)
        card.pack_start(actions, False, False, 0)
        return card

    def _row(self, ev, now):
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_can_focus(False)
        btn.get_style_context().add_class("agenda-row")
        row = Gtk.Box(spacing=10)
        when = label("time")
        when.set_width_chars(6)
        when.set_text(_("dia todo") if ev["all_day"] else f"{ev['start']:%H:%M}")
        title = label("small")
        title.set_text(clip(ev["title"], 34))
        row.pack_start(when, False, False, 0)
        row.pack_start(title, True, True, 0)
        if not ev["all_day"] and ev["start"].date() == now.date() and now < ev["end"]:
            c = label("dim small", 1.0)
            c.set_text(countdown(now, ev))
            row.pack_start(c, False, False, 0)
        if ev["meet"]:
            row.pack_start(icon(VIDEO_ICON, 13), False, False, 0)
        btn.add(row)
        btn.connect("clicked", lambda *_a: open_url(ev["meet"] or ev["html"]))
        return btn
