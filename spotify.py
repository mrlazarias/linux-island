"""Cliente MPRIS do Spotify via Gio D-Bus (sem polling de metadados)."""
import hashlib
import os
import threading
import time
import urllib.request

from gi.repository import Gio, GLib

BUS_NAME = "org.mpris.MediaPlayer2.spotify"
PATH = "/org/mpris/MediaPlayer2"
IFACE = "org.mpris.MediaPlayer2.Player"
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "linux-island", "art")


class Track:
    def __init__(self, md):
        self.trackid = md.get("mpris:trackid", "")
        self.title = md.get("xesam:title", "") or ""
        artists = md.get("xesam:artist") or []
        self.artist = ", ".join(artists) if isinstance(artists, list) else str(artists)
        self.album = md.get("xesam:album", "") or ""
        self.length = int(md.get("mpris:length", 0) or 0)  # microssegundos
        self.art_url = md.get("mpris:artUrl", "") or ""

    def __eq__(self, other):
        return isinstance(other, Track) and self.trackid == other.trackid


class Spotify:
    """Observa o Spotify no barramento de sessão e avisa a UI por callbacks.

    on_presence(bool), on_track(Track|None), on_status(bool playing),
    on_art(path|None)
    """

    def __init__(self, on_presence, on_track, on_status, on_art):
        self.on_presence = on_presence
        self.on_track = on_track
        self.on_status = on_status
        self.on_art = on_art
        self.proxy = None
        self.track = None
        self.playing = False
        self._pos_base = 0
        self._pos_time = time.monotonic()
        os.makedirs(CACHE_DIR, exist_ok=True)
        Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            self._appeared, self._vanished,
        )

    # --- presença -------------------------------------------------------
    def _appeared(self, conn, name, owner):
        Gio.DBusProxy.new(
            conn, Gio.DBusProxyFlags.GET_INVALIDATED_PROPERTIES, None,
            BUS_NAME, PATH, IFACE, None, self._proxy_ready,
        )

    def _proxy_ready(self, _src, res):
        try:
            self.proxy = Gio.DBusProxy.new_finish(res)
        except GLib.Error as e:
            print(f"[island] falha ao conectar no Spotify: {e.message}")
            return
        self.proxy.connect("g-properties-changed", self._props_changed)
        self.proxy.connect("g-signal", self._signal)
        self.on_presence(True)
        self._read_all()
        self.sync_position()

    def _vanished(self, conn, name):
        self.proxy = None
        self.track = None
        self.playing = False
        self.on_presence(False)

    # --- propriedades ---------------------------------------------------
    def _prop(self, name):
        v = self.proxy.get_cached_property(name) if self.proxy else None
        return v.unpack() if v is not None else None

    def _read_all(self):
        self._update_status(self._prop("PlaybackStatus"))
        self._update_metadata(self._prop("Metadata"))

    def _props_changed(self, _proxy, changed, _invalidated):
        changed = changed.unpack()
        if "PlaybackStatus" in changed:
            self._update_status(changed["PlaybackStatus"])
        if "Metadata" in changed:
            self._update_metadata(changed["Metadata"])

    def _signal(self, _proxy, _sender, name, params):
        if name == "Seeked":
            self._set_pos(params.unpack()[0])

    def _update_status(self, status):
        playing = status == "Playing"
        # congela a posição interpolada no instante da mudança
        self._set_pos(self.position())
        self.playing = playing
        self.on_status(playing)
        self.sync_position()

    def _update_metadata(self, md):
        if not md or not md.get("xesam:title"):
            self.track = None
            self.on_track(None)
            return
        track = Track(md)
        changed = track != self.track
        self.track = track
        self.on_track(track)
        if changed:
            self._set_pos(0)
            self.sync_position()
            self._fetch_art(track)

    # --- posição (Spotify não emite mudanças de Position) ---------------
    def _set_pos(self, us):
        self._pos_base = us
        self._pos_time = time.monotonic()

    def position(self):
        """Posição atual em µs, interpolada entre leituras."""
        pos = self._pos_base
        if self.playing:
            pos += int((time.monotonic() - self._pos_time) * 1_000_000)
        if self.track and self.track.length:
            pos = min(pos, self.track.length)
        return max(pos, 0)

    def sync_position(self):
        if not self.proxy:
            return
        self.proxy.call(
            "org.freedesktop.DBus.Properties.Get",
            GLib.Variant("(ss)", (IFACE, "Position")),
            Gio.DBusCallFlags.NONE, 1000, None, self._pos_ready,
        )

    def _pos_ready(self, proxy, res):
        try:
            self._set_pos(proxy.call_finish(res).unpack()[0])
        except GLib.Error:
            pass

    # --- capa -----------------------------------------------------------
    def _fetch_art(self, track):
        url = track.art_url
        if not url.startswith(("https://", "http://", "file://")):
            self.on_art(None)
            return
        if url.startswith("file://"):
            self.on_art(url[len("file://"):])
            return
        path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".jpg")
        if os.path.exists(path):
            self.on_art(path)
            return

        def work():
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
                result = None
            # só entrega se ainda for a mesma faixa
            GLib.idle_add(lambda: (self.track and self.track.art_url == url
                                   and self.on_art(result)) and False)

        threading.Thread(target=work, daemon=True).start()

    # --- controles ------------------------------------------------------
    def _call(self, method, args=None):
        if self.proxy:
            self.proxy.call(method, args, Gio.DBusCallFlags.NONE, 1000, None, None)

    def play_pause(self):
        self._call("PlayPause")

    def next(self):
        self._call("Next")

    def previous(self):
        self._call("Previous")

    def seek_to(self, fraction):
        if not self.track or not self.track.length or not self.track.trackid:
            return
        us = int(self.track.length * max(0.0, min(1.0, fraction)))
        self._call("SetPosition", GLib.Variant("(ox)", (self.track.trackid, us)))
        self._set_pos(us)

    def raise_window(self):
        if self.proxy:
            Gio.DBusProxy.new(
                self.proxy.get_connection(), Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None, BUS_NAME, PATH, "org.mpris.MediaPlayer2", None,
                lambda _s, r: Gio.DBusProxy.new_finish(r).call(
                    "Raise", None, Gio.DBusCallFlags.NONE, 1000, None, None),
            )
