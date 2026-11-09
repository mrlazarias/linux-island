"""Abas extras da janela de configurações (Spotify; Água).

Mixin de settings.Settings: usa self.cfg, self.web, self._page, self._group,
self._row, self._switch, self._spin e self._sync de lá.
"""
from gi.repository import Gtk


class SettingsPagesMixin:
    def _page_spotify(self):
        from spotify_web import REDIRECT_URI  # import local: módulo opcional da UI

        scroll, page = self._page()
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup(
            "Mostra a <b>playlist</b> que está tocando e o <b>dispositivo</b> (celular, "
            "caixa de som, TV…). O Spotify não expõe isso localmente, então é preciso "
            "conectar sua conta pela Web API com um app seu.")
        intro.get_style_context().add_class("dim-label")
        page.pack_start(intro, False, False, 0)

        steps = self._group(page, "Como configurar")
        for n, text in enumerate([
            'Abra <a href="https://developer.spotify.com/dashboard">developer.spotify.com/'
            'dashboard</a> e crie um app (a conta dona precisa ser Premium).',
            "Em <b>Redirect URIs</b> adicione o endereço abaixo e marque <b>Web API</b>.",
            "Salve, copie o <b>Client ID</b> do app e cole aqui embaixo.",
        ], 1):
            lb = Gtk.Label(xalign=0, wrap=True)
            lb.set_markup(f"{n}. {text}")
            row = Gtk.Box()
            for side in ("top", "bottom", "start", "end"):
                getattr(row, f"set_margin_{side}")(10 if side in ("top", "bottom") else 12)
            row.pack_start(lb, True, True, 0)
            steps.add(row)
        uri = Gtk.Label(label=REDIRECT_URI, selectable=True)
        uri.get_style_context().add_class("code")
        copy = Gtk.Button(label="Copiar")
        copy.connect("clicked", lambda *_: Gtk.Clipboard.get_default(
            self.get_display()).set_text(REDIRECT_URI, -1))
        box = Gtk.Box(spacing=8)
        box.pack_start(uri, False, False, 0)
        box.pack_start(copy, False, False, 0)
        self._row(steps, "Redirect URI", box)

        account = self._group(page, "Conta")
        entry = Gtk.Entry(text=self.cfg["spotify_client_id"], placeholder_text="32 caracteres")
        entry.set_width_chars(34)
        entry.set_max_length(32)

        def changed(*_):
            text = entry.get_text().strip()
            valid = text == "" or (len(text) == 32 and all(c in "0123456789abcdefABCDEF"
                                                          for c in text))
            ctx = entry.get_style_context()
            (ctx.remove_class if valid else ctx.add_class)("error")
            if valid:
                self.cfg.set("spotify_client_id", text)

        entry.connect("changed", changed)
        self._sync["spotify_client_id"] = lambda: (
            entry.get_text().strip() != self.cfg["spotify_client_id"]
            and entry.set_text(self.cfg["spotify_client_id"]))
        self._row(account, "Client ID", entry)

        self.sp_status = Gtk.Label(xalign=0)
        self.sp_button = Gtk.Button()
        self.sp_button.connect("clicked", self._spotify_clicked)
        self._row(account, "Status", self.sp_button).get_children()[0].pack_start(
            self.sp_status, False, False, 0)
        return scroll

    def _spotify_clicked(self, *_):
        if self.web.connected:
            self.web.disconnect()
        else:
            self.web.login()

    def set_spotify_status(self, text, ok):
        if not hasattr(self, "sp_status"):
            return
        self.sp_status.set_text(text)
        ctx = self.sp_status.get_style_context()
        (ctx.add_class if ok else ctx.remove_class)("ok")
        if not ok:
            ctx.add_class("dim-label")
        else:
            ctx.remove_class("dim-label")
        connected = self.web.connected
        self.sp_button.set_label("Desconectar" if connected else "Conectar")
        bctx = self.sp_button.get_style_context()
        (bctx.remove_class if connected else bctx.add_class)("suggested")
