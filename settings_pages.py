"""Abas extras da janela de configurações (Spotify; Água).

Mixin de settings.Settings: usa self.cfg, self.web, self._page, self._group,
self._row, self._switch, self._spin e self._sync de lá.
"""
from gi.repository import GLib, Gtk


class SettingsPagesMixin:
    def _page_notifications(self):
        scroll, page = self._page()
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup("Quando um app manda uma notificação, a pílula se estica por alguns "
                         "segundos mostrando quem notificou e o que disse. Clique nela para "
                         "abrir o app.")
        intro.get_style_context().add_class("dim-label")
        page.pack_start(intro, False, False, 0)

        main = self._group(page, "Notificações")
        self._row(main, "Mostrar notificações na pílula", self._switch("notif_enabled"))
        self._row(main, "Não perturbe", self._switch("notif_dnd"),
                  "Pausa as notificações na ilha (as do sistema continuam normais)")
        self._row(main, "Duração (s)", self._spin("notif_duration_s", 2, 15))
        self._row(main, "Mostrar o texto", self._switch("notif_show_body"),
                  "Desligado: só o título aparece, para mais privacidade")

        ignore = self._group(page, "Apps ignorados")
        entry = Gtk.Entry(text=self.cfg["notif_ignore"], placeholder_text="Ex.: Spotify, Slack")
        entry.set_width_chars(26)
        entry.set_max_length(500)
        pending = {"id": None}

        def commit(*_):
            if pending["id"]:
                GLib.source_remove(pending["id"])
                pending["id"] = None
            self.cfg.set("notif_ignore", entry.get_text().strip())
            return False

        def changed(*_):
            if pending["id"]:
                GLib.source_remove(pending["id"])
            pending["id"] = GLib.timeout_add(800, commit)

        entry.connect("changed", changed)
        entry.connect("activate", commit)
        self._sync["notif_ignore"] = lambda: (
            entry.get_text().strip() != self.cfg["notif_ignore"]
            and entry.set_text(self.cfg["notif_ignore"]))
        self._row(ignore, "Não mostrar de", entry, "Nomes dos apps, separados por vírgula")
        return scroll

    def _page_agenda(self):
        from google_calendar import find_client_secret
        from water import SOUNDS, play_sound

        scroll, page = self._page()
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup("Mostra os eventos da sua agenda principal do <b>Google</b> e avisa "
                         "antes das reuniões. Funciona com contas pessoais e corporativas; "
                         "o acesso é <b>somente leitura</b>.")
        intro.get_style_context().add_class("dim-label")
        page.pack_start(intro, False, False, 0)

        account = self._group(page, "Conta Google")
        has_app = find_client_secret() is not None
        if not has_app:
            warn = Gtk.Label(xalign=0, wrap=True)
            warn.set_markup("As credenciais do app do Google não estão configuradas nesta "
                            "instalação — veja a seção <b>Agenda</b> do README.")
            warn.get_style_context().add_class("dim-label")
            box = Gtk.Box()
            for side in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{side}")(10 if side in ("top", "bottom") else 12)
            box.pack_start(warn, True, True, 0)
            account.add(box)
        self.ag_status = Gtk.Label(xalign=0)
        self.ag_button = Gtk.Button()
        self.ag_button.set_sensitive(has_app)
        self.ag_button.connect("clicked", lambda *_: (
            self.agenda.disconnect() if self.agenda.connected else self.agenda.login()))
        self._row(account, "Status", self.ag_button).get_children()[0].pack_start(
            self.ag_status, False, False, 0)

        show = self._group(page, "Exibição")
        self._row(show, "Mostrar agenda", self._switch("agenda_enabled"))
        self._row(show, "Dias à frente", self._spin("agenda_days", 1, 7))

        alert = self._group(page, "Aviso de reunião")
        self._row(alert, "Avisar na pílula", self._switch("agenda_alert"),
                  "A pílula mostra a reunião com contagem regressiva")
        self._row(alert, "Quanto antes (min)", self._spin("agenda_lead_min", 0, 60, 5))
        self._row(alert, "Tocar som", self._switch("agenda_sound"))
        self._row(alert, "Som", self._choice("agenda_sound_name", SOUNDS))
        test = Gtk.Button(label="Testar")
        test.connect("clicked", lambda *_: play_sound(self.cfg["agenda_sound_name"],
                                                      self.cfg["agenda_sound_volume"]))
        vol = Gtk.Box(spacing=8)
        vol.pack_start(self._spin("agenda_sound_volume", 0, 100, 10), False, False, 0)
        vol.pack_start(test, False, False, 0)
        self._row(alert, "Volume (%)", vol)
        return scroll

    def set_agenda_status(self, text, ok):
        if not hasattr(self, "ag_status"):
            return
        self.ag_status.set_text(text)
        ctx = self.ag_status.get_style_context()
        (ctx.add_class if ok else ctx.remove_class)("ok")
        (ctx.remove_class if ok else ctx.add_class)("dim-label")
        connected = self.agenda.connected
        self.ag_button.set_label("Sair da conta" if connected else "Entrar com Google")
        bctx = self.ag_button.get_style_context()
        (bctx.remove_class if connected else bctx.add_class)("suggested")

    def _page_water(self):
        scroll, page = self._page()
        main = self._group(page, "Lembrete")
        self._row(main, "Lembrar de beber água", self._switch("water_enabled"))
        self._row(main, "Intervalo (min)", self._spin("water_interval_min", 5, 360, 5),
                  "Tempo desde o último copo até o próximo lembrete")
        self._row(main, "Adiar por (min)", self._spin("water_snooze_min", 1, 120, 1))
        self._row(main, "Notificação do sistema", self._switch("water_notify"),
                  "Além do aviso na ilha, mostra uma notificação com Bebi e Adiar")

        from water import SOUNDS, play_sound  # import local: só a aba usa

        sound = self._group(page, "Aviso sonoro")
        self._row(sound, "Tocar som no lembrete", self._switch("water_sound"))
        self._row(sound, "Som", self._choice("water_sound_name", SOUNDS))
        test = Gtk.Button(label="Testar")
        test.connect("clicked", lambda *_: play_sound(self.cfg["water_sound_name"],
                                                      self.cfg["water_sound_volume"]))
        vol = Gtk.Box(spacing=8)
        vol.pack_start(self._spin("water_sound_volume", 0, 100, 10), False, False, 0)
        vol.pack_start(test, False, False, 0)
        self._row(sound, "Volume (%)", vol)

        goal = self._group(page, "Meta")
        self._row(goal, "Meta diária (ml)", self._spin("water_goal_ml", 250, 8000, 250))
        self._row(goal, "Tamanho do copo (ml)", self._spin("water_cup_ml", 50, 1500, 50),
                  "Quanto soma cada clique em + na ilha")

        hours = self._group(page, "Horário")
        self._row(hours, "Começa às (h)", self._spin("water_start_h", 0, 23))
        self._row(hours, "Termina às (h)", self._spin("water_end_h", 1, 24),
                  "Se o fim não for depois do início, lembra o dia todo")

        today = self._group(page, "Hoje")
        self.water_today = Gtk.Label(xalign=0)
        reset = Gtk.Button(label="Zerar hoje")
        reset.connect("clicked", lambda *_: (self.water.reset_day(), self._water_refresh()))
        self._row(today, "Consumido", reset).get_children()[0].pack_start(
            self.water_today, False, False, 0)
        self._water_refresh()
        return scroll

    def _water_refresh(self):
        if hasattr(self, "water_today"):
            self.water_today.set_text(
                f"{self.water.consumed} de {self.cfg['water_goal_ml']} ml · {self.water.status()}")
            self.water_today.get_style_context().add_class("dim-label")

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
