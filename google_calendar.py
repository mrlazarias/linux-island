"""Google Calendar (somente leitura): login OAuth de app de desktop e leitura de eventos.

- Credenciais do app: google_client.json empacotado com o projeto (o app
  oficial do linux-island) ou ~/.config/linux-island/google_client_secret.json
  (para quem quiser usar um app próprio). Em apps de desktop o "client secret"
  não é segredo de verdade (o Google trata o cliente como público, com PKCE).
- Login: navegador + servidor local em 127.0.0.1 (porta livre), com PKCE.
- Token: no chaveiro do sistema (libsecret); se não houver, arquivo 0600.
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

from secret_store import SecretStore

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
LOGIN_TIMEOUT_S = 300

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "linux-island")
SECRET_PATHS = [
    os.path.join(CONFIG_DIR, "google_client_secret.json"),  # app próprio, se houver
    os.path.join(HERE, "google_client.json"),                # app oficial do projeto
]


class AuthError(Exception):
    """Precisa (re)conectar: sem credenciais, token revogado ou expirado."""


# --- credenciais do app ------------------------------------------------------
def find_client_secret():
    """(caminho, client_id, client_secret) do primeiro arquivo válido, ou None."""
    for path in SECRET_PATHS:
        try:
            with open(path) as f:
                data = json.load(f).get("installed") or {}
        except (OSError, ValueError, AttributeError):
            continue
        if data.get("client_id") and data.get("client_secret"):
            return path, data["client_id"], data["client_secret"]
    return None


# --- onde guardar o token ------------------------------------------------------
class TokenStore:
    """Token do Google em JSON, no chaveiro (via SecretStore)."""

    def __init__(self):
        self._store = SecretStore("google-token", "Google Agenda")

    def load(self):
        raw = self._store.load()
        try:
            tok = json.loads(raw) if raw else None
        except ValueError:
            return None
        return tok if isinstance(tok, dict) and tok.get("refresh_token") else None

    def save(self, tok):
        self._store.save(json.dumps(tok))

    def clear(self):
        self._store.clear()


# --- cliente ----------------------------------------------------------------------
class GoogleCalendar:
    """Login e leitura. Bloqueante: chame os métodos de rede fora da thread da UI."""

    def __init__(self):
        self.store = TokenStore()
        self.token = self.store.load()
        self._lock = threading.Lock()

    @property
    def connected(self):
        return bool(self.token and self.token.get("refresh_token"))

    # tokens
    def _token_request(self, fields):
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, headers={
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", "")
            except ValueError:
                err = ""
            if err in ("invalid_grant", "invalid_client", "unauthorized_client"):
                raise AuthError(err) from e
            raise
        tok = {
            "access_token": data["access_token"],
            "expires_at": time.time() + int(data.get("expires_in", 3600)) - 60,
            "refresh_token": data.get("refresh_token") or (self.token or {}).get("refresh_token"),
        }
        self.store.save(tok)
        self.token = tok

    def _access_token(self, force=False):
        with self._lock:
            if not self.connected:
                raise AuthError("não conectado")
            if force or time.time() >= self.token.get("expires_at", 0):
                cs = find_client_secret()
                if not cs:
                    raise AuthError("credenciais do app não encontradas")
                _, cid, csecret = cs
                try:
                    self._token_request({"grant_type": "refresh_token", "client_id": cid,
                                         "client_secret": csecret,
                                         "refresh_token": self.token["refresh_token"]})
                except AuthError:
                    # revogado ou expirado (apps em "Testing" expiram em 7 dias)
                    self.token = None
                    self.store.clear()
                    raise
            return self.token["access_token"]

    # login
    def login(self):
        """Abre o navegador e espera o retorno. Devolve None ou levanta AuthError."""
        cs = find_client_secret()
        if not cs:
            raise AuthError("credenciais do app não encontradas")
        _, cid, csecret = cs
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        server = HTTPServer(("127.0.0.1", 0), make_handler(state))
        server.timeout = 1
        server.result = None
        redirect = f"http://127.0.0.1:{server.server_address[1]}"
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code",
            "scope": SCOPE, "code_challenge": challenge, "code_challenge_method": "S256",
            "state": state, "access_type": "offline", "prompt": "consent",
        })
        GLib.idle_add(lambda: Gio.AppInfo.launch_default_for_uri(url, None) and False)
        deadline = time.time() + LOGIN_TIMEOUT_S
        try:
            while server.result is None and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        res = server.result
        if res is None:
            raise AuthError("tempo de login esgotado")
        if "error" in res:
            raise AuthError(f"login cancelado: {res['error']}")
        self._token_request({"grant_type": "authorization_code", "code": res["code"],
                             "redirect_uri": redirect, "client_id": cid,
                             "client_secret": csecret, "code_verifier": verifier})

    def disconnect(self):
        tok = (self.token or {}).get("refresh_token")
        self.token = None
        self.store.clear()
        if tok:  # revoga no Google sem travar quem chamou
            def revoke():
                try:
                    urllib.request.urlopen(urllib.request.Request(
                        REVOKE_URL, data=urllib.parse.urlencode({"token": tok}).encode()),
                        timeout=10).close()
                except (urllib.error.URLError, OSError):
                    pass
            threading.Thread(target=revoke, daemon=True).start()

    # leitura
    def fetch_events(self, time_min, time_max, retry=True):
        """Itens crus da API entre time_min e time_max (datetimes com fuso)."""
        q = urllib.parse.urlencode({
            "timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": 100,
        })
        req = urllib.request.Request(f"{EVENTS_URL}?{q}", headers={
            "Authorization": f"Bearer {self._access_token()}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read()).get("items", [])
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:
                self._access_token(force=True)
                return self.fetch_events(time_min, time_max, retry=False)
            raise


def make_handler(expected_state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            if u.path not in ("/", ""):
                self.send_error(404)
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            if q.get("state") != expected_state:
                self.send_error(400, "state inválido")
                return
            self.server.result = ({"error": q["error"]} if "error" in q
                                  else {"code": q.get("code", "")})
            ok = "code" in q
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Agenda conectada! Pode fechar esta aba." if ok else "Login cancelado."
            self.wfile.write(
                ("<html><body style='background:#000;color:#fff;font-family:sans-serif;"
                 "display:grid;place-items:center;height:100vh;margin:0'>"
                 f"<h2>linux-island — {msg}</h2></body></html>").encode())

        def log_message(self, *_):
            pass

    return Handler
