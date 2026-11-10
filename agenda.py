"""Agenda: aviso de reunião e contagem regressiva (lógica pura) e o controlador.

A fonte é o link iCal secreto da agenda (Google, Outlook, iCloud, Nextcloud…),
guardado no chaveiro. Lógica pura recebe `now` (datetime com fuso) para ser
testável com relógio fixo. O controlador baixa a cada 5 min e recalcula o
aviso a cada 30 s pelo relógio de parede (funciona depois de suspender o PC).
"""
import math
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from gi.repository import GLib

import ical
from secret_store import SecretStore

POLL_S = 5 * 60
TICK_S = 30
GRACE = timedelta(minutes=5)  # o alerta continua um pouco depois do início
MAX_BYTES = 8 * 1024 * 1024
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


# --- lógica pura -----------------------------------------------------------------
def is_google_public(url):
    """Endereço público do Google (…/public/basic.ics): só funciona se a agenda for pública."""
    return "calendar.google.com/calendar/ical/" in url and "/public/" in url


def alert_event(now, events, lead_min):
    """Reunião que deve aparecer na pílula agora: start - lead <= now < start + GRACE."""
    lead = timedelta(minutes=lead_min)
    for ev in events:
        if ev["all_day"]:
            continue
        if ev["start"] - lead <= now < min(ev["start"] + GRACE, ev["end"]):
            return ev
    return None


def alert_key(ev):
    """Identifica o alerta: se o evento for remarcado, alerta de novo."""
    return (ev["id"], ev["start"].isoformat())


def countdown(now, ev):
    if ev["all_day"]:
        return "dia todo"
    if now >= ev["start"]:
        return "agora" if now < ev["end"] else "terminou"
    mins = math.ceil((ev["start"] - now).total_seconds() / 60)
    if mins < 60:
        return f"em {mins} min"
    h, m = divmod(mins, 60)
    return f"em {h} h {m:02d}" if m else f"em {h} h"


def day_label(day, today):
    if day == today:
        return "Hoje"
    if day == today + timedelta(days=1):
        return "Amanhã"
    return f"{DIAS[day.weekday()]} {day.day:02d}/{day.month:02d}"


def upcoming(now, events, days):
    """[(rótulo do dia, [eventos ainda não terminados])] dos próximos `days` dias."""
    today = now.date()
    last = today + timedelta(days=days - 1)
    groups = {}
    for ev in events:
        if ev["end"] <= now:
            continue
        day = max(ev["start"].date(), today) if ev["all_day"] else ev["start"].date()
        if day > last:
            continue
        groups.setdefault(day, []).append(ev)
    return [(day_label(d, today), groups[d]) for d in sorted(groups)]


# --- controlador (lado GTK) ---------------------------------------------------------
class Agenda:
    """on_change() quando a lista/estado muda; on_alert(evento|None); on_status(texto, ok)."""

    def __init__(self, cfg, on_change, on_alert, on_status, play_sound):
        self.cfg = cfg
        self.on_change = on_change
        self.on_alert = on_alert
        self.on_status = on_status
        self.play_sound = play_sound
        self.store = SecretStore("ical-url", "link da agenda")
        self.url = self.store.load()
        self.events = []
        self.alert = None
        self._dismissed = set()
        self._sounded = set()
        self._busy = False
        self._poll_id = None
        self.status = ("Carregando…", True) if self.url else ("Nenhuma agenda", False)
        GLib.timeout_add_seconds(TICK_S, lambda: self.tick() or True)
        if self.url:
            self._start_polling()

    @property
    def connected(self):
        return bool(self.url)

    def _set_status(self, text, ok):
        self.status = (text, ok)
        self.on_status(text, ok)

    # link
    def set_url(self, url):
        """Valida, guarda no chaveiro e começa a buscar. Devolve False se o link for inválido."""
        url = ical.normalize_url(url)
        if not url:
            self._set_status("Link inválido: use o endereço https:// (ou webcal://)", False)
            return False
        self.store.save(url)
        self.url = url
        self._set_status("Carregando…", True)
        self._start_polling()
        return True

    def disconnect(self):
        self.store.clear()
        self.url = None
        self._stop_polling()
        self.events = []
        self._set_status("Nenhuma agenda", False)
        self.on_change()
        self.tick()

    # busca
    def _start_polling(self):
        if self._poll_id is None:
            self._poll_id = GLib.timeout_add_seconds(POLL_S, lambda: self.refresh() or True)
        self.refresh()

    def _stop_polling(self):
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = None

    def refresh(self):
        if self._busy or not self.url or not self.cfg["agenda_enabled"]:
            return
        self._busy = True
        url = self.url
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=self.cfg["agenda_days"])

        def work():
            events, err = None, None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "linux-island"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("agenda grande demais")
                text = data.decode("utf-8", errors="replace")
                if "BEGIN:VCALENDAR" not in text[:2000].upper():
                    raise ValueError("o link não devolveu uma agenda iCal")
                events = ical.events_between(text, start, end, ical.owner_from_url(url))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404) and is_google_public(url):
                    err = ("esse é o endereço PÚBLICO, que só funciona com a agenda pública. "
                           "Use o “Endereço secreto no formato iCal” (tem private- no link)")
                else:
                    err = f"o servidor respondeu {e.code}" + (
                        " — o link foi trocado ou removido?" if e.code in (401, 403, 404) else "")
            except (urllib.error.URLError, OSError) as e:
                err = "sem conexão"  # mantém os eventos que já estavam na tela
                print(f"[island] agenda indisponível: {getattr(e, 'reason', e)}")
            except ValueError as e:
                err = str(e)
            GLib.idle_add(self._done, url, events, err)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, url, events, err):
        self._busy = False
        if url != self.url:  # trocaram o link no meio da busca
            self.refresh()
            return False
        if events is not None:
            self.events = events
            n = sum(1 for e in events if e["end"] > datetime.now().astimezone())
            self._set_status(f"Conectada · {n} evento{'s' if n != 1 else ''} pela frente", True)
        elif err:
            self._set_status(f"Não deu para ler a agenda: {err}", False)
        self.on_change()
        self.tick()
        return False

    # alerta
    def tick(self):
        now = datetime.now().astimezone()
        ev = None
        if self.cfg["agenda_enabled"] and self.cfg["agenda_alert"]:
            ev = alert_event(now, self.events, self.cfg["agenda_lead_min"])
            if ev and alert_key(ev) in self._dismissed:
                ev = None
        changed = (ev is None) != (self.alert is None) or (
            ev and self.alert and alert_key(ev) != alert_key(self.alert))
        self.alert = ev
        if ev and self.cfg["agenda_sound"] and alert_key(ev) not in self._sounded:
            self._sounded.add(alert_key(ev))
            self.play_sound(self.cfg["agenda_sound_name"], self.cfg["agenda_sound_volume"])
        if changed:
            self.on_alert(ev)

    def dismiss(self):
        if self.alert:
            self._dismissed.add(alert_key(self.alert))
            self.tick()
