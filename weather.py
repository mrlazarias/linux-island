"""Clima via Open-Meteo (sem chave). Localização: --city, ou pelo IP (ipwho.is)."""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from gi.repository import GLib

CACHE = os.path.join(GLib.get_user_cache_dir(), "linux-island", "location.json")
LOCATION_TTL = 6 * 3600
REFRESH_S = 15 * 60

# código WMO -> (descrição, ícone de dia, ícone de noite)
WMO = {
    0: ("Céu limpo", "weather-clear", "weather-clear-night"),
    1: ("Quase limpo", "weather-few-clouds", "weather-few-clouds-night"),
    2: ("Parcialmente nublado", "weather-few-clouds", "weather-few-clouds-night"),
    3: ("Nublado", "weather-overcast", "weather-overcast"),
    45: ("Neblina", "weather-fog", "weather-fog"),
    48: ("Neblina", "weather-fog", "weather-fog"),
    51: ("Garoa fraca", "weather-showers-scattered", None),
    53: ("Garoa", "weather-showers-scattered", None),
    55: ("Garoa forte", "weather-showers", None),
    56: ("Garoa congelante", "weather-showers", None),
    57: ("Garoa congelante", "weather-showers", None),
    61: ("Chuva fraca", "weather-showers-scattered", None),
    63: ("Chuva", "weather-showers", None),
    65: ("Chuva forte", "weather-showers", None),
    66: ("Chuva congelante", "weather-showers", None),
    67: ("Chuva congelante", "weather-showers", None),
    71: ("Neve fraca", "weather-snow", None),
    73: ("Neve", "weather-snow", None),
    75: ("Neve forte", "weather-snow", None),
    77: ("Granizo fino", "weather-snow", None),
    80: ("Pancadas fracas", "weather-showers-scattered", None),
    81: ("Pancadas de chuva", "weather-showers", None),
    82: ("Pancadas fortes", "weather-showers", None),
    85: ("Pancadas de neve", "weather-snow", None),
    86: ("Pancadas de neve", "weather-snow", None),
    95: ("Tempestade", "weather-storm", None),
    96: ("Tempestade com granizo", "weather-storm", None),
    99: ("Tempestade com granizo", "weather-storm", None),
}


def describe(code, is_day=True):
    desc, day, night = WMO.get(code, ("—", "weather-severe-alert", None))
    return desc, (day if is_day or not night else night) + "-symbolic"


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "linux-island"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read(1024 * 1024))


class Forecast:
    def __init__(self, data, place):
        cur = data["current"]
        self.place = place
        self.temp = round(cur["temperature_2m"])
        self.feels = round(cur["apparent_temperature"])
        self.humidity = cur.get("relative_humidity_2m")
        self.wind = round(cur.get("wind_speed_10m") or 0)
        self.desc, self.icon = describe(cur["weather_code"], cur.get("is_day", 1))
        d = data["daily"]
        self.days = [  # (data ISO, ícone, máx, mín, % chuva)
            (d["time"][i], describe(d["weather_code"][i])[1],
             round(d["temperature_2m_max"][i]), round(d["temperature_2m_min"][i]),
             (d.get("precipitation_probability_max") or [None] * 9)[i])
            for i in range(len(d["time"]))
        ]
        self.today_max, self.today_min = self.days[0][2], self.days[0][3]


class Weather:
    """Busca em thread e entrega Forecast na thread da UI via on_update."""

    def __init__(self, on_update, city=None):
        self.on_update = on_update
        self.city = city
        self.location = None  # (lat, lon, nome)
        self._busy = False
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_S, lambda: self.refresh() or True)

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        result = None
        try:
            if self.location is None:
                self.location = self._locate()
            lat, lon, name = self.location
            q = urllib.parse.urlencode({
                "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 5,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                           "weather_code,is_day,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max",
            })
            result = Forecast(_get_json("https://api.open-meteo.com/v1/forecast?" + q), name)
        except Exception as e:  # sem rede, API fora etc.: tenta de novo no próximo ciclo
            print(f"[island] clima indisponível: {e}")
        self._busy = False
        if result:
            GLib.idle_add(lambda: self.on_update(result) and False)

    def _locate(self):
        if self.city:
            q = urllib.parse.urlencode({"name": self.city, "count": 1, "language": "pt"})
            res = _get_json("https://geocoding-api.open-meteo.com/v1/search?" + q).get("results")
            if not res:
                raise ValueError(f"cidade não encontrada: {self.city}")
            r = res[0]
            return r["latitude"], r["longitude"], r["name"]
        try:
            with open(CACHE) as f:
                c = json.load(f)
            if time.time() - c["at"] < LOCATION_TTL:
                return c["lat"], c["lon"], c["name"]
        except (OSError, ValueError, KeyError):
            pass
        d = _get_json("https://ipwho.is/")
        if not d.get("success"):
            raise ValueError(d.get("message", "ipwho.is falhou"))
        loc = {"lat": d["latitude"], "lon": d["longitude"], "name": d.get("city", ""),
               "at": time.time()}
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump(loc, f)
        return loc["lat"], loc["lon"], loc["name"]
