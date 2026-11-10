"""Spotify Web API: playlist/álbum em reprodução e dispositivo onde está tocando.

O MPRIS do Spotify não expõe nem o contexto (playlist) nem o dispositivo, então
isto usa OAuth PKCE (sem segredo) com um Client ID do próprio usuário.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from gi.repository import Gio, GLib

from i18n import _

PORT = 8974
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "user-read-playback-state playlist-read-private playlist-read-collaborative"
TOKEN_PATH = os.path.join(GLib.get_user_config_dir(), "linux-island", "spotify-token.json")
API = "https://api.spotify.com/v1"
POLL_S = 15
LOGIN_TIMEOUT_S = 300

DEVICE_ICONS = {  # tipo do Spotify -> ícone simbólico
    "computer": "computer-symbolic",
    "smartphone": "phone-symbolic",
    "tablet": "phone-symbolic",
    "speaker": "audio-speakers-symbolic",
    "tv": "video-display-symbolic",
    "castvideo": "video-display-symbolic",
    "castaudio": "audio-speakers-symbolic",
    "automobile": "audio-speakers-symbolic",
    "gameconsole": "input-gaming-symbolic",
}
CONTEXT_ICONS = {
    "playlist": "view-list-symbolic",
    "album": "media-optical-symbolic",
    "artist": "avatar-default-symbolic",
    "collection": "emblem-favorite-symbolic",
    "show": "audio-input-microphone-symbolic",
}


class Playback:
    """O que interessa de GET /me/player."""

    def __init__(self, data, context_name):
        dev = data.get("device") or {}
        self.device = dev.get("name") or ""
        self.device_type = (dev.get("type") or "").lower()
        self.device_icon = DEVICE_ICONS.get(self.device_type, "audio-x-generic-symbolic")
        ctx = data.get("context") or {}
        self.context_type = ctx.get("type") or ""
        self.context_name = context_name
        self.context_icon = CONTEXT_ICONS.get(self.context_type, "view-list-symbolic")
        self.is_playing = bool(data.get("is_playing"))
        item = data.get("item") or {}
        self.title = item.get("name") or ""
        self.track_uri = item.get("uri") or ""


def parse_player(data, lookup_name):
    """data = JSON de /me/player (ou None se 204). lookup_name(tipo, id) -> nome."""
    if not data or not data.get("device"):
        return None
    ctx = data.get("context") or {}
    kind, uri = ctx.get("type"), ctx.get("uri") or ""
    name = None
    if kind == "collection":
        name = _("Músicas Curtidas")
    elif kind == "album":
        name = ((data.get("item") or {}).get("album") or {}).get("name")
    elif kind in ("playlist", "artist", "show") and uri.count(":") >= 2:
        name = lookup_name(kind, uri.rsplit(":", 1)[1])
    return Playback(data, name)


class AuthError(Exception):
    pass


class SpotifyWeb:
    """Login, tokens e polling. Callbacks chegam na thread da UI.

    on_playback(Playback|None), on_status(texto, conectado: bool)
    """

    def __init__(self, client_id, on_playback, on_status):
        self.client_id = client_id
        self.on_playback = on_playback
        self.on_status = on_status
        self.token = self._load_token()
        self._names = {}  # (tipo, id) -> nome
        self._busy = False
        self._poll_id = None
        self._kick_id = None
        self._backoff_until = 0
        if self.connected:
            self._start_polling()

    # --- estado ---------------------------------------------------------
    @property
    def connected(self):
        return bool(self.client_id and self.token and self.token.get("refresh_token"))

    def set_client_id(self, client_id):
        if client_id != self.client_id:
            self.client_id = client_id
            self.disconnect()

    def _emit_status(self, text, ok):
        GLib.idle_add(lambda: self.on_status(text, ok) and False)

    # --- tokens ---------------------------------------------------------
    @staticmethod
    def _load_token():
        try:
            with open(TOKEN_PATH) as f:
                tok = json.load(f)
            return tok if isinstance(tok, dict) else None
        except (OSError, ValueError):
            return None

    def _save_token(self, tok):
        os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
        tmp = TOKEN_PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(tok, f)
        os.replace(tmp, TOKEN_PATH)
        self.token = tok

    def _token_request(self, fields):
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise AuthError(_("login recusado ({codigo})").format(codigo=e.code)) from e
        tok = {"access_token": data["access_token"],
               "expires_at": time.time() + int(data.get("expires_in", 3600)) - 60,
               "refresh_token": data.get("refresh_token") or (self.token or {}).get("refresh_token")}
        self._save_token(tok)

    def _access_token(self, force_refresh=False):
        if not self.connected:
            raise AuthError(_("não conectado"))
        if force_refresh or time.time() >= self.token.get("expires_at", 0):
            self._token_request({"grant_type": "refresh_token", "client_id": self.client_id,
                                 "refresh_token": self.token["refresh_token"]})
        return self.token["access_token"]

    # --- login (PKCE + servidor local de callback) ----------------------
    def login(self):
        if not self.client_id:
            self.on_status(_("Informe o Client ID primeiro"), False)
            return
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256", "code_challenge": challenge,
            "scope": SCOPES, "state": state,
        })
        try:
            server = HTTPServer(("127.0.0.1", PORT), _make_handler(state))
        except OSError as e:
            self.on_status(_("Porta {porta} ocupada: {erro}").format(porta=PORT, erro=e.strerror),
                           False)
            return
        server.timeout = 1
        server.result = None  # preenchido pelo handler do /callback
        self.on_status(_("Aguardando login no navegador…"), False)
        threading.Thread(target=self._wait_login, args=(server, verifier), daemon=True).start()
        Gio.AppInfo.launch_default_for_uri(url, None)

    def _wait_login(self, server, verifier):
        deadline = time.time() + LOGIN_TIMEOUT_S
        try:
            while server.result is None and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        res = server.result
        if res is None:
            self._emit_status(_("Tempo de login esgotado"), False)
        elif "error" in res:
            self._emit_status(_("Login cancelado: {erro}").format(erro=res["error"]), False)
        else:
            try:
                self._token_request({"grant_type": "authorization_code", "code": res["code"],
                                     "redirect_uri": REDIRECT_URI, "client_id": self.client_id,
                                     "code_verifier": verifier})
            except (AuthError, OSError, KeyError, ValueError) as e:
                self._emit_status(_("Falha no login: {erro}").format(erro=e), False)
                return
            self._emit_status(_("Conectado"), True)
            GLib.idle_add(lambda: self._start_polling() and False)

    def disconnect(self):
        self.token = None
        try:
            os.remove(TOKEN_PATH)
        except FileNotFoundError:
            pass
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = None
        self.on_playback(None)
        self.on_status(_("Desconectado"), False)

    # --- API ------------------------------------------------------------
    def _get(self, path, retry=True):
        req = urllib.request.Request(API + path,
                                     headers={"Authorization": f"Bearer {self._access_token()}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 204:
                    return None
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:
                self._access_token(force_refresh=True)
                return self._get(path, retry=False)
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "30") or 30)
                self._backoff_until = time.time() + min(wait, 600)
            raise

    def _lookup_name(self, kind, item_id):
        key = (kind, item_id)
        if key not in self._names:
            try:
                path = {"playlist": f"/playlists/{item_id}?fields=name",
                        "artist": f"/artists/{item_id}",
                        "show": f"/shows/{item_id}"}[kind]
                self._names[key] = (self._get(path) or {}).get("name")
            except urllib.error.HTTPError:
                # playlists do próprio Spotify (Daily Mix, editoriais) dão 404 para apps novos
                self._names[key] = None
        return self._names[key] or {"playlist": _("Playlist"), "artist": _("Artista"),
                                    "show": _("Podcast")}.get(kind)

    # --- polling --------------------------------------------------------
    def _start_polling(self):
        if self._poll_id is None:
            self._poll_id = GLib.timeout_add_seconds(POLL_S, lambda: self.refresh() or True)
        self.refresh()

    def kick(self):
        """Busca logo (debounce) — chamado quando a faixa ou o status muda no MPRIS."""
        if not self.connected:
            return
        if self._kick_id:
            GLib.source_remove(self._kick_id)
        self._kick_id = GLib.timeout_add(1200, self._kicked)

    def _kicked(self):
        self._kick_id = None
        self.refresh()
        return False

    def refresh(self):
        if self._busy or not self.connected or time.time() < self._backoff_until:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        result, ok = None, True
        try:
            data = self._get("/me/player")
            if os.environ.get("ISLAND_DEBUG"):
                dev = (data or {}).get("device") or {}
                print(f"[island] /me/player device={dev.get('name')!r} type={dev.get('type')!r} "
                      f"active={dev.get('is_active')} context={(data or {}).get('context')}",
                      flush=True)
            result = parse_player(data, self._lookup_name)
        except AuthError as e:
            ok = False
            self._emit_status(_("Reconecte: {erro}").format(erro=e), False)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[island] Spotify Web API indisponível: {e}")
            ok = None  # erro transitório: mantém o que já está na tela
        GLib.idle_add(self._done, result, ok)

    def _done(self, result, ok):
        self._busy = False
        if ok is not None:
            self.on_playback(result)
        return False


def _make_handler(expected_state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            if u.path != "/callback":
                self.send_error(404)
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            if q.get("state") != expected_state:
                self.send_error(400, "state inválido")
                return
            self.server.result = ({"error": q["error"]} if "error" in q
                                  else {"code": q.get("code", "")})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = _("Pronto! Pode fechar esta aba.") if "code" in q else _("Login cancelado.")
            self.wfile.write(
                f"<html><body style='background:#000;color:#fff;font-family:sans-serif;"
                f"display:grid;place-items:center;height:100vh;margin:0'>"
                f"<h2>linux-island — {msg}</h2></body></html>".encode())

        def log_message(self, *_):
            pass

    return Handler
