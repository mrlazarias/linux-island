"""Configurações persistentes em ~/.config/linux-island/config.json."""
import json
import os
import re

from gi.repository import Gdk, GLib

PATH = os.path.join(GLib.get_user_config_dir(), "linux-island", "config.json")

# chave -> (padrão, validador). Validadores recebem o valor lido do JSON e
# devolvem True se ele for aceitável; senão vale o padrão.
_is_bool = lambda v: isinstance(v, bool)  # noqa: E731


def _is_color(v):
    return isinstance(v, str) and Gdk.RGBA().parse(v)


def _int_range(lo, hi):
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _choice(*opts):
    return lambda v: v in opts


SCHEMA = {
    # aparência
    "bg_color": ("rgba(0,0,0,1)", _is_color),
    "text_color": ("rgb(255,255,255)", _is_color),
    "accent_auto": (True, _is_bool),          # cor de destaque tirada da capa
    "accent_color": ("rgb(30,215,96)", _is_color),
    "border": (True, _is_bool),
    "radius_expanded": (30, _int_range(8, 48)),
    # relógio
    "clock_24h": (True, _is_bool),
    "show_date": (True, _is_bool),
    # clima
    "city": ("", lambda v: isinstance(v, str) and len(v) <= 100),
    "units": ("celsius", _choice("celsius", "fahrenheit")),
    "show_weather": (True, _is_bool),
    # Spotify Web API (playlist e dispositivo); vazio = desligado
    "spotify_client_id": ("", lambda v: isinstance(v, str)
                          and (v == "" or re.fullmatch(r"[0-9a-fA-F]{32}", v) is not None)),
    # lembrete de água
    "water_enabled": (True, _is_bool),
    "water_goal_ml": (2000, _int_range(250, 8000)),
    "water_cup_ml": (250, _int_range(50, 1500)),
    "water_interval_min": (60, _int_range(5, 360)),
    "water_start_h": (8, _int_range(0, 23)),
    "water_end_h": (22, _int_range(1, 24)),
    "water_snooze_min": (10, _int_range(1, 120)),
    "water_notify": (False, _is_bool),
    "water_sound": (True, _is_bool),
    "water_sound_name": ("message-new-instant", _choice(
        "message-new-instant", "complete", "bell", "dialog-information",
        "window-attention", "alarm-clock-elapsed")),
    "water_sound_volume": (70, _int_range(0, 100)),
    # agenda (Google Calendar, agenda principal)
    "agenda_enabled": (True, _is_bool),
    "agenda_alert": (True, _is_bool),
    "agenda_lead_min": (10, _int_range(0, 60)),
    "agenda_days": (3, _int_range(1, 7)),
    "agenda_sound": (True, _is_bool),
    "agenda_sound_name": ("bell", _choice(
        "message-new-instant", "complete", "bell", "dialog-information",
        "window-attention", "alarm-clock-elapsed")),
    "agenda_sound_volume": (70, _int_range(0, 100)),
    # notificações de outros apps na pílula
    "notif_enabled": (True, _is_bool),
    "notif_dnd": (False, _is_bool),
    "notif_duration_s": (5, _int_range(2, 15)),
    "notif_show_body": (True, _is_bool),
    "notif_ignore": ("Spotify", lambda v: isinstance(v, str) and len(v) <= 500),
    # idioma da interface ("auto" segue o sistema)
    "language": ("auto", _choice("auto", "pt", "en", "es")),
    # comportamento
    "hover_expand": (True, _is_bool),
    "peek_on_track": (True, _is_bool),
    "scroll_volume": (True, _is_bool),
    "hover_delay_ms": (120, _int_range(0, 2000)),
    "margin_top": (2, _int_range(0, 200)),
}


class Config:
    def __init__(self, overrides=None):
        self._values = {k: d for k, (d, _) in SCHEMA.items()}
        self._listeners = []
        self._save_id = None
        self._load()
        # overrides da linha de comando valem só para esta execução
        self._overrides = {k: v for k, v in (overrides or {}).items() if v is not None}

    def _load(self):
        try:
            with open(PATH) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            print(f"[island] config inválida, usando padrões: {e}")
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if key in SCHEMA and SCHEMA[key][1](value):
                self._values[key] = value

    def __getitem__(self, key):
        return self._overrides.get(key, self._values[key])

    def set(self, key, value):
        if key not in SCHEMA or not SCHEMA[key][1](value):
            raise ValueError(f"valor inválido para {key}: {value!r}")
        self._overrides.pop(key, None)  # mexeu na UI: vale o que foi escolhido
        if self._values[key] == value:
            return
        self._values[key] = value
        self._schedule_save()
        for fn in self._listeners:
            fn(key)

    def reset(self):
        for key, (default, _) in SCHEMA.items():
            self.set(key, default)

    def connect(self, fn):
        self._listeners.append(fn)

    def disconnect(self, fn):
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _schedule_save(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(400, self._save)

    def _save(self):
        self._save_id = None
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._values, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PATH)
        return False


def rgba(spec):
    c = Gdk.RGBA()
    c.parse(spec)
    return c


def css_color(c, alpha=None):
    a = c.alpha if alpha is None else c.alpha * alpha
    return f"rgba({round(c.red * 255)},{round(c.green * 255)},{round(c.blue * 255)},{a:.3f})"


def build_css(cfg):
    """CSS gerado a partir da configuração (cores e arredondamento)."""
    bg, fg = rgba(cfg["bg_color"]), rgba(cfg["text_color"])
    border = f"1px solid {css_color(fg, 0.07)}" if cfg["border"] else "1px solid transparent"
    return f"""
.island {{ background-color: {css_color(bg)}; color: {css_color(fg)}; border: {border}; }}
.island.expanded {{ border-radius: {cfg['radius_expanded']}px; }}
.island .dim, .island .artist {{ color: {css_color(fg, 0.6)}; }}
.island .time {{ color: {css_color(fg, 0.55)}; }}
.island .control {{ color: {css_color(fg)}; }}
.island .control:hover {{ background-color: {css_color(fg, 0.12)}; }}
.island .control:active {{ background-color: {css_color(fg, 0.22)}; }}
.island .day {{ background-color: {css_color(fg, 0.05)}; }}
.island separator {{ background-color: {css_color(fg, 0.1)}; }}
.island.water-alert {{ border-color: rgb(41,158,245); }}
.island.meeting-alert {{ border-color: rgb(167,139,250); }}
.island button.agenda-row {{
  background: transparent; border: none; box-shadow: none; padding: 6px 8px;
  border-radius: 12px; color: {css_color(fg)};
}}
.island button.agenda-row:hover {{ background: {css_color(fg, 0.07)}; }}
.island button.page-dot {{
  min-width: 6px; min-height: 6px; padding: 0; border: none; box-shadow: none;
  border-radius: 999px; background: {css_color(fg, 0.25)};
}}
.island button.page-dot.active {{ background: {css_color(fg, 0.9)}; min-width: 16px; }}
.island button.water-snooze {{
  background: {css_color(fg, 0.08)}; color: {css_color(fg)}; border: none; box-shadow: none;
  border-radius: 999px; padding: 4px 12px; font-size: 11px;
}}
"""


def accent_tuple(spec):
    c = rgba(spec)
    return (c.red, c.green, c.blue)
