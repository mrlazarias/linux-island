"""Lembrete de beber água: estado do dia, agenda e lógica pura (testável).

O estado do dia fica em ~/.local/state/linux-island/water.json (separado da
configuração). A agenda é recalculada a cada tick a partir de horários de
relógio de parede: timeouts longos do GLib usam o relógio monotônico, que
para durante a suspensão, e disparariam horas atrasados.
"""
import json
import os
from datetime import datetime, timedelta

from gi.repository import Gio, GLib

from i18n import _

SOUND_DIR = "/usr/share/sounds/freedesktop/stereo"
SOUNDS = [  # id do arquivo .oga -> nome na UI
    ("message-new-instant", "Mensagem"),
    ("complete", "Concluído"),
    ("bell", "Sino"),
    ("dialog-information", "Aviso suave"),
    ("window-attention", "Atenção"),
    ("alarm-clock-elapsed", "Despertador"),
]
STATE_PATH = os.path.join(GLib.get_user_state_dir(), "linux-island", "water.json")
TICK_S = 30


# --- lógica pura ------------------------------------------------------------
def window(now, start_h, end_h):
    """Horário ativo de hoje. Se início >= fim, vale o dia inteiro."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if start_h >= end_h:
        return day, day + timedelta(days=1)
    return day + timedelta(hours=start_h), day + timedelta(hours=end_h)


def fresh_state(now):
    return {"date": now.date().isoformat(), "consumed": 0, "last_drink": None,
            "snooze_until": None, "anchor": now.timestamp()}


def roll_day(state, now):
    """Zera o dia quando a data muda (também cobre PC ligado na virada/suspensão)."""
    if state.get("date") != now.date().isoformat():
        return fresh_state(now)
    return state


def next_reminder(now, state, cfg):
    """Quando é o próximo lembrete, ou None (desligado, meta batida, fim do horário)."""
    if not cfg["water_enabled"] or state["consumed"] >= cfg["water_goal_ml"]:
        return None
    w_start, w_end = window(now, cfg["water_start_h"], cfg["water_end_h"])
    ts = [state.get("anchor"), state.get("last_drink")]
    base = max([w_start] + [datetime.fromtimestamp(t) for t in ts if t])
    due = base + timedelta(minutes=cfg["water_interval_min"])
    if state.get("snooze_until"):
        due = max(due, datetime.fromtimestamp(state["snooze_until"]))
    return due if due < w_end else None


def status_text(now, state, cfg):
    goal = cfg["water_goal_ml"]
    if not cfg["water_enabled"]:
        return _("Lembretes desligados")
    if state["consumed"] >= goal:
        return _("Meta de hoje batida!")
    nxt = next_reminder(now, state, cfg)
    if nxt is None:
        _w_start, w_end = window(now, cfg["water_start_h"], cfg["water_end_h"])
        return (_("Sem lembretes até amanhã") if now >= w_end - timedelta(minutes=1)
                else _("Último lembrete do dia já passou"))
    if nxt <= now:
        return _("Hora de beber água!")
    return _("Próximo lembrete às {hora}").format(hora=nxt.strftime("%H:%M"))


def play_sound(name, volume):
    """Toca um som do tema freedesktop sem travar a UI. volume: 0–100."""
    if name not in dict(SOUNDS):
        return
    path = os.path.join(SOUND_DIR, name + ".oga")
    if not os.path.exists(path):
        print(f"[island] som não encontrado: {path}")
        return
    v = max(0, min(100, volume))
    for cmd in (["paplay", f"--volume={int(65536 * v / 100)}", path],
                ["pw-play", f"--volume={v / 100:.2f}", path]):
        if GLib.find_program_in_path(cmd[0]):
            try:
                Gio.Subprocess.new(cmd, Gio.SubprocessFlags.STDOUT_SILENCE
                                   | Gio.SubprocessFlags.STDERR_SILENCE)
            except GLib.Error as e:
                print(f"[island] não deu para tocar o som: {e.message}")
            return


# --- estado + agenda (lado GTK) --------------------------------------------
class Water:
    """on_change() quando algo muda; on_alert(bool) quando o alerta liga/desliga."""

    def __init__(self, cfg, on_change, on_alert):
        self.cfg = cfg
        self.on_change = on_change
        self.on_alert = on_alert
        self.alerting = False
        self.state = self._load()
        # o primeiro lembrete conta a partir de agora: login não dispara alerta na hora
        self.state["anchor"] = datetime.now().timestamp()
        self._save()
        GLib.timeout_add_seconds(TICK_S, lambda: self.tick() or True)

    def _load(self):
        now = datetime.now()
        try:
            with open(STATE_PATH) as f:
                st = json.load(f)
            ok = (isinstance(st, dict) and isinstance(st.get("consumed"), int)
                  and isinstance(st.get("date"), str))
        except (OSError, ValueError):
            ok = False
        return roll_day(st, now) if ok else fresh_state(now)

    def _save(self):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE_PATH)

    # --- leitura ---------------------------------------------------------
    @property
    def consumed(self):
        return self.state["consumed"]

    def status(self):
        return status_text(datetime.now(), self.state, self.cfg)

    # --- tick ------------------------------------------------------------
    def tick(self):
        now = datetime.now()
        rolled = roll_day(self.state, now)
        if rolled is not self.state:
            self.state = rolled
            self._save()
            self.on_change()
        nxt = next_reminder(now, self.state, self.cfg)
        self._set_alert(nxt is not None and now >= nxt)

    def _set_alert(self, value):
        if value != self.alerting:
            self.alerting = value
            self.on_alert(value)

    # --- ações -----------------------------------------------------------
    def _changed(self):
        self._save()
        self.on_change()
        self.tick()

    def drink(self, ml=None):
        self.state = roll_day(self.state, datetime.now())
        self.state["consumed"] += ml or self.cfg["water_cup_ml"]
        self.state["last_drink"] = datetime.now().timestamp()
        self.state["snooze_until"] = None
        self._changed()

    def undo(self):
        self.state["consumed"] = max(0, self.state["consumed"] - self.cfg["water_cup_ml"])
        self._changed()

    def snooze(self):
        until = datetime.now() + timedelta(minutes=self.cfg["water_snooze_min"])
        self.state["snooze_until"] = until.timestamp()
        self._changed()

    def reset_day(self):
        self.state = fresh_state(datetime.now())
        self._changed()


class Notifier:
    """Notificação "Hora de beber água" com botões Bebi/Adiar.

    Fala direto com org.freedesktop.Notifications: o GNotification escolhe um
    backend que o COSMIC não tem e falha calado. on_action("drink"|"snooze").
    """

    NAME = "org.freedesktop.Notifications"
    PATH = "/org/freedesktop/Notifications"

    def __init__(self, on_action):
        self.on_action = on_action
        self.bus = None
        self.id = 0

    def _bus(self):
        if self.bus is None:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.bus.signal_subscribe(None, self.NAME, "ActionInvoked", self.PATH, None,
                                      Gio.DBusSignalFlags.NONE, self._action)
        return self.bus

    def notify(self, consumed, goal):
        try:
            bus = self._bus()
        except GLib.Error:
            return
        params = GLib.Variant("(susssasa{sv}i)", (
            "linux-island", self.id, "dialog-information-symbolic", _("Hora de beber água"),
            _("Hoje: {feito} de {meta} ml").format(feito=consumed, meta=goal),
            ["drink", _("Bebi"), "snooze", _("Adiar")], {}, 0))

        def done(b, res):
            try:
                self.id = b.call_finish(res).unpack()[0]
            except GLib.Error as e:
                print(f"[island] notificação falhou: {e.message}")

        bus.call(self.NAME, self.PATH, self.NAME, "Notify", params, GLib.VariantType("(u)"),
                 Gio.DBusCallFlags.NONE, 3000, None, done)

    def close(self):
        if self.id and self.bus:
            self.bus.call(self.NAME, self.PATH, self.NAME, "CloseNotification",
                          GLib.Variant("(u)", (self.id,)), None, Gio.DBusCallFlags.NONE,
                          3000, None, None)
            self.id = 0

    def _action(self, _bus, _sender, _path, _iface, _signal, params):
        nid, action = params.unpack()
        if nid == self.id:
            self.on_action(action)
