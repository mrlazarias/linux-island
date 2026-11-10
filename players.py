"""Players de música/vídeo via MPRIS (Spotify, Firefox, Chrome, VLC, mpv, Rhythmbox…).

`Players` observa todos os org.mpris.MediaPlayer2.* do barramento e escolhe o
ativo: o que está tocando; se nenhum, o último usado. Para o resto da ilha ele
se comporta como um player só (mesmos atributos e métodos), avisando por
callbacks: on_presence(bool), on_track(Track|None), on_status(bool),
on_art(caminho|None), on_volume(float), on_switch(Player|None).
"""
import hashlib
import os
import threading
import time
import urllib.request

from gi.repository import Gio, GLib

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
IFACE = "org.mpris.MediaPlayer2.Player"
ROOT_IFACE = "org.mpris.MediaPlayer2"
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "linux-island", "art")


class Track:
    def __init__(self, md):
        self.trackid = md.get("mpris:trackid", "") or ""
        self.title = md.get("xesam:title", "") or ""
        artists = md.get("xesam:artist") or []
        self.artist = ", ".join(artists) if isinstance(artists, list) else str(artists)
        self.album = md.get("xesam:album", "") or ""
        self.length = int(md.get("mpris:length", 0) or 0)  # microssegundos
        self.art_url = md.get("mpris:artUrl", "") or ""

    def key(self):
        return (self.trackid, self.title, self.artist)

    def __eq__(self, other):
        return isinstance(other, Track) and self.key() == other.key()


class Player:
    """Um player MPRIS. `events(player, tipo)` avisa o gerenciador de mudanças."""

    def __init__(self, conn, bus_name, events):
        self.bus_name = bus_name
        self.short = bus_name[len(PREFIX):].split(".instance")[0].lower()
        self.events = events
        self.identity = self.short.capitalize()
        self.desktop_entry = None
        self.proxy = None
        self.track = None
        self.playing = False
        self.volume = 1.0
        self.has_volume = False
        self.art_path = None
        self.last_active = 0.0
        self._pos_base = 0
        self._pos_time = time.monotonic()
        Gio.DBusProxy.new(conn, Gio.DBusProxyFlags.GET_INVALIDATED_PROPERTIES, None,
                          bus_name, PATH, IFACE, None, self._ready)
        Gio.DBusProxy.new(conn, Gio.DBusProxyFlags.NONE, None, bus_name, PATH, ROOT_IFACE,
                          None, self._root_ready)

    @property
    def is_spotify(self):
        return self.short == "spotify"

    # --- conexão --------------------------------------------------------
    def _root_ready(self, _src, res):
        try:
            root = Gio.DBusProxy.new_finish(res)
        except GLib.Error:
            return
        ident = root.get_cached_property("Identity")
        if ident is not None and ident.unpack():
            self.identity = ident.unpack()
        entry = root.get_cached_property("DesktopEntry")
        if entry is not None and entry.unpack():
            self.desktop_entry = entry.unpack()
        self._root = root
        self.events(self, "identity")

    def _ready(self, _src, res):
        try:
            self.proxy = Gio.DBusProxy.new_finish(res)
        except GLib.Error as e:
            print(f"[island] player {self.bus_name} indisponível: {e.message}")
            return
        self.proxy.connect("g-properties-changed", self._props_changed)
        self.proxy.connect("g-signal", self._signal)
        self._update_volume(self._prop("Volume"))
        self._update_status(self._prop("PlaybackStatus"), initial=True)
        self._update_metadata(self._prop("Metadata"))
        self.sync_position()
        self.events(self, "ready")

    def close(self):
        self.proxy = None

    # --- propriedades ---------------------------------------------------
    def _prop(self, name):
        v = self.proxy.get_cached_property(name) if self.proxy else None
        return v.unpack() if v is not None else None

    def _props_changed(self, _proxy, changed, _invalidated):
        changed = changed.unpack()
        if "Volume" in changed:
            self._update_volume(changed["Volume"])
        if "PlaybackStatus" in changed:
            self._update_status(changed["PlaybackStatus"])
        if "Metadata" in changed:
            self._update_metadata(changed["Metadata"])

    def _signal(self, _proxy, _sender, name, params):
        if name == "Seeked":
            self._set_pos(params.unpack()[0])

    def _update_volume(self, v):
        if isinstance(v, (int, float)):
            self.has_volume = True
            self.volume = max(0.0, min(1.0, float(v)))
            self.events(self, "volume")

    def _update_status(self, status, initial=False):
        playing = status == "Playing"
        self._set_pos(self.position())  # congela a posição interpolada na mudança
        started = playing and not self.playing
        self.playing = playing
        if playing:
            self.last_active = time.monotonic()
        self.sync_position()
        self.events(self, "started" if started and not initial else "status")

    def _update_metadata(self, md):
        if not md or not md.get("xesam:title"):
            self.track = None
            self.art_path = None
            self.events(self, "track")
            return
        track = Track(md)
        changed = track != self.track
        self.track = track
        if changed:
            self._set_pos(0)
            self.sync_position()
            self.art_path = None
            self._fetch_art(track)
        self.events(self, "track")

    # --- posição (alguns players não emitem mudanças de Position) --------
    def _set_pos(self, us):
        self._pos_base = us
        self._pos_time = time.monotonic()

    def position(self):
        pos = self._pos_base
        if self.playing:
            pos += int((time.monotonic() - self._pos_time) * 1_000_000)
        if self.track and self.track.length:
            pos = min(pos, self.track.length)
        return max(pos, 0)

    def sync_position(self):
        if self.proxy:
            self.proxy.call("org.freedesktop.DBus.Properties.Get",
                            GLib.Variant("(ss)", (IFACE, "Position")),
                            Gio.DBusCallFlags.NONE, 1000, None, self._pos_ready)

    def _pos_ready(self, proxy, res):
        try:
            self._set_pos(proxy.call_finish(res).unpack()[0])
        except GLib.Error:
            pass

    # --- capa -----------------------------------------------------------
    def _deliver_art(self, url, path):
        if self.track and self.track.art_url == url:
            self.art_path = path
            self.events(self, "art")
        return False

    def _fetch_art(self, track):
        url = track.art_url
        if url.startswith("file://"):
            path = GLib.filename_from_uri(url)[0]
            GLib.idle_add(self._deliver_art, url, path if os.path.exists(path) else None)
            return
        if not url.startswith(("https://", "http://")):
            GLib.idle_add(self._deliver_art, url, None)
            return
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".img")
        if os.path.exists(path):
            GLib.idle_add(self._deliver_art, url, path)
            return

        def work():
            result = None
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "linux-island"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = r.read(5 * 1024 * 1024)
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                result = path
            except Exception as e:  # rede fora, 404 etc.
                print(f"[island] capa indisponível: {e}")
            GLib.idle_add(self._deliver_art, url, result)

        threading.Thread(target=work, daemon=True).start()

    # --- controles ------------------------------------------------------
    def call(self, method, args=None):
        if self.proxy:
            self.proxy.call(method, args, Gio.DBusCallFlags.NONE, 1000, None, None)

    def set_volume(self, v):
        self.volume = max(0.0, min(1.0, v))
        self.call("org.freedesktop.DBus.Properties.Set",
                  GLib.Variant("(ssv)", (IFACE, "Volume", GLib.Variant("d", self.volume))))

    def seek_to(self, fraction):
        if not self.track or not self.track.length or not self.track.trackid:
            return
        us = int(self.track.length * max(0.0, min(1.0, fraction)))
        self.call("SetPosition", GLib.Variant("(ox)", (self.track.trackid, us)))
        self._set_pos(us)

    def raise_window(self):
        root = getattr(self, "_root", None)
        if root is not None:
            root.call("Raise", None, Gio.DBusCallFlags.NONE, 1000, None, None)


class Players:
    """Todos os players; expõe o ativo com a interface de um player só."""

    def __init__(self, on_presence, on_track, on_status, on_art, on_volume=None,
                 on_switch=None, ignored=None):
        self.on_presence, self.on_track, self.on_status = on_presence, on_track, on_status
        self.on_art = on_art
        self.on_volume = on_volume or (lambda v: None)
        self.on_switch = on_switch or (lambda p: None)
        self.ignored = ignored or (lambda p: False)
        self.players = {}
        self.active = None
        self._unmute_to = 0.5
        Gio.bus_get(Gio.BusType.SESSION, None, self._bus_ready)

    # --- descoberta -----------------------------------------------------
    def _bus_ready(self, _src, res):
        self.conn = Gio.bus_get_finish(res)
        self.conn.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                   "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                   Gio.DBusSignalFlags.NONE, self._owner_changed)
        self.conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                       "ListNames", None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE,
                       3000, None, self._names_ready)

    def _names_ready(self, conn, res):
        try:
            names = conn.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        for name in names:
            if name.startswith(PREFIX):
                self._add(name)

    def _owner_changed(self, _c, _s, _p, _i, _sig, params):
        name, old, new = params.unpack()
        if not name.startswith(PREFIX):
            return
        if new and not old:
            self._add(name)
        elif old and not new:
            self._remove(name)

    def _add(self, name):
        if name not in self.players:
            self.players[name] = Player(self.conn, name, self._event)

    def _remove(self, name):
        p = self.players.pop(name, None)
        if p:
            p.close()
            if p is self.active:
                self._choose()

    # --- escolha do ativo -----------------------------------------------
    def _candidates(self):
        return [p for p in self.players.values() if p.proxy and not self.ignored(p)]

    def _choose(self, prefer=None):
        cands = self._candidates()
        best = None
        if prefer in cands:
            best = prefer
        else:
            playing = [p for p in cands if p.playing]
            pool = playing or [p for p in cands if p.track] or cands
            if pool:
                best = max(pool, key=lambda p: (p.last_active, p.is_spotify))
        self._set_active(best)

    def refresh_choice(self):
        """Reavalia o ativo (ex.: a lista de players ignorados mudou)."""
        if self.active and self.ignored(self.active):
            self.active = None
        self._choose(self.active)

    def _set_active(self, p):
        if p is self.active:
            return
        self.active = p
        self.on_switch(p)
        self.on_presence(p is not None)
        if p is None:
            self.on_track(None)
            self.on_status(False)
            return
        self.on_volume(p.volume)
        self.on_status(p.playing)
        self.on_track(p.track)
        self.on_art(p.art_path)

    def _event(self, p, kind):
        if kind == "ready":
            # na abertura (ou com o ativo parado), reavalia: tocando > com música > Spotify
            if self.active is None or not self.active.playing:
                self._choose(p if p.playing and not self.ignored(p) else None)
            return
        if kind == "started" and p is not self.active and not self.ignored(p):
            self._set_active(p)  # quem começou a tocar vira o ativo
            return
        if p is not self.active:
            return
        if kind in ("status", "started"):
            self.on_status(p.playing)
        elif kind == "track":
            self.on_track(p.track)
        elif kind == "art":
            self.on_art(p.art_path)
        elif kind == "volume":
            self.on_volume(p.volume)
        elif kind == "identity":
            self.on_switch(p)

    # --- interface de "um player só" (o ativo) --------------------------
    @property
    def proxy(self):
        return self.active.proxy if self.active else None

    @property
    def track(self):
        return self.active.track if self.active else None

    @property
    def playing(self):
        return bool(self.active and self.active.playing)

    @property
    def volume(self):
        return self.active.volume if self.active else 1.0

    @property
    def is_spotify(self):
        return bool(self.active and self.active.is_spotify)

    @property
    def name(self):
        return self.active.identity if self.active else ""

    def position(self):
        return self.active.position() if self.active else 0

    def sync_position(self):
        if self.active:
            self.active.sync_position()

    def play_pause(self):
        if self.active:
            self.active.call("PlayPause")

    def next(self):
        if self.active:
            self.active.call("Next")

    def previous(self):
        if self.active:
            self.active.call("Previous")

    def seek_to(self, fraction):
        if self.active:
            self.active.seek_to(fraction)

    def set_volume(self, v):
        if self.active:
            self.active.set_volume(v)

    def toggle_mute(self):
        if not self.active:
            return
        if self.active.volume > 0.001:
            self._unmute_to = self.active.volume
            self.active.set_volume(0.0)
        else:
            self.active.set_volume(self._unmute_to or 0.5)

    def raise_window(self):
        if self.active:
            self.active.raise_window()
