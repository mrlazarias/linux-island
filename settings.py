"""Janela de configurações. Tudo é aplicado ao vivo e salvo automaticamente."""
import os

from gi.repository import GLib, Gtk

from config import rgba

AUTOSTART = os.path.join(GLib.get_user_config_dir(), "autostart", "linux-island.desktop")
RUN_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.sh")

PRESETS = [  # nome, fundo, texto, destaque automático, destaque fixo
    ("Clássico", "rgba(0,0,0,1)", "rgb(255,255,255)", True, "rgb(30,215,96)"),
    ("Vidro", "rgba(20,20,28,0.72)", "rgb(255,255,255)", True, "rgb(30,215,96)"),
    ("Claro", "rgba(246,246,248,1)", "rgb(20,20,24)", False, "rgb(0,122,255)"),
    ("Spotify", "rgba(18,18,18,1)", "rgb(255,255,255)", False, "rgb(30,215,96)"),
    ("Grafite", "rgba(43,46,52,1)", "rgb(230,232,236)", False, "rgb(255,159,67)"),
]


def autostart_enabled():
    return os.path.exists(AUTOSTART)


def set_autostart(enabled):
    if enabled:
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=linux-island\n"
                    "Comment=Dynamic island no painel\n"
                    f"Exec={RUN_SH}\nX-GNOME-Autostart-Delay=2\nNoDisplay=true\n")
    elif os.path.exists(AUTOSTART):
        os.remove(AUTOSTART)


class Settings(Gtk.Window):
    def __init__(self, cfg, app=None):
        super().__init__(title="linux-island — Configurações")
        if app:
            self.set_application(app)
        self.cfg = cfg
        self._sync = {}  # chave -> função que atualiza o widget a partir da config
        self.set_default_size(520, 560)
        self.set_icon_name("preferences-system")

        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Configurações")
        reset = Gtk.Button(label="Restaurar padrões")
        reset.connect("clicked", lambda *_: self.cfg.reset())
        header.pack_end(reset)
        self.set_titlebar(header)

        stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        switcher = Gtk.StackSwitcher(stack=stack)
        header.set_custom_title(switcher)
        stack.add_titled(self._page_appearance(), "look", "Aparência")
        stack.add_titled(self._page_clock_weather(), "info", "Relógio e clima")
        stack.add_titled(self._page_behavior(), "behavior", "Comportamento")
        self.add(stack)

        cfg.connect(self._on_config)
        self.connect("destroy", lambda *_: cfg.disconnect(self._on_config))
        self.show_all()

    def _on_config(self, key):
        fn = self._sync.get(key)
        if fn:
            fn()

    # --- construção de linhas ------------------------------------------
    @staticmethod
    def _page():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(20)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add(box)
        return scroll, box

    @staticmethod
    def _group(parent, title):
        lb = Gtk.Label(xalign=0)
        lb.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame = Gtk.Frame()
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        frame.add(listbox)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(lb, False, False, 0)
        box.pack_start(frame, False, False, 0)
        parent.pack_start(box, False, False, 0)
        return listbox

    @staticmethod
    def _row(listbox, title, widget, subtitle=None):
        row = Gtk.Box(spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(row, f"set_margin_{side}")(10 if side in ("top", "bottom") else 12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_valign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0)
        texts.pack_start(t, False, False, 0)
        if subtitle:
            s = Gtk.Label(label=subtitle, xalign=0)
            s.set_line_wrap(True)
            s.get_style_context().add_class("dim-label")
            texts.pack_start(s, False, False, 0)
        widget.set_valign(Gtk.Align.CENTER)
        row.pack_start(texts, True, True, 0)
        row.pack_end(widget, False, False, 0)
        listbox.add(row)
        return row

    # --- controles ligados à config ------------------------------------
    def _switch(self, key):
        sw = Gtk.Switch(active=self.cfg[key])
        sw.connect("notify::active", lambda w, _p: self.cfg.set(key, w.get_active()))
        self._sync[key] = lambda: sw.set_active(self.cfg[key])
        return sw

    def _color(self, key, alpha=False):
        btn = Gtk.ColorButton(use_alpha=alpha)
        btn.set_rgba(rgba(self.cfg[key]))
        btn.connect("color-set", lambda b: self.cfg.set(key, b.get_rgba().to_string()))
        self._sync[key] = lambda: btn.set_rgba(rgba(self.cfg[key]))
        return btn

    def _spin(self, key, lo, hi, step=1):
        sp = Gtk.SpinButton.new_with_range(lo, hi, step)
        sp.set_value(self.cfg[key])
        sp.connect("value-changed", lambda w: self.cfg.set(key, int(w.get_value())))
        self._sync[key] = lambda: sp.set_value(self.cfg[key])
        return sp

    def _choice(self, key, options):
        combo = Gtk.ComboBoxText()
        for value, label in options:
            combo.append(value, label)
        combo.set_active_id(self.cfg[key])
        combo.connect("changed", lambda c: c.get_active_id() and self.cfg.set(key, c.get_active_id()))
        self._sync[key] = lambda: combo.set_active_id(self.cfg[key])
        return combo

    # --- páginas --------------------------------------------------------
    def _page_appearance(self):
        scroll, page = self._page()

        themes = self._group(page, "Temas")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5,
                           column_spacing=8, row_spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(flow, f"set_margin_{side}")(10)
        for name, bg, fg, auto, accent in PRESETS:
            flow.add(self._preset_button(name, bg, fg, auto, accent))
        themes.add(flow)

        colors = self._group(page, "Cores")
        self._row(colors, "Fundo", self._color("bg_color", alpha=True),
                  "Use a transparência para um efeito de vidro")
        self._row(colors, "Texto e ícones", self._color("text_color"))
        self._row(colors, "Destaque automático", self._switch("accent_auto"),
                  "Equalizador e barra de progresso na cor da capa do álbum")
        accent_row = self._row(colors, "Cor de destaque", self._color("accent_color"))
        accent_row.set_sensitive(not self.cfg["accent_auto"])
        prev = self._sync["accent_auto"]
        self._sync["accent_auto"] = lambda: (prev(), accent_row.set_sensitive(
            not self.cfg["accent_auto"]))

        shape = self._group(page, "Forma")
        self._row(shape, "Arredondamento expandida", self._spin("radius_expanded", 8, 48),
                  "Raio dos cantos, em px")
        self._row(shape, "Borda sutil", self._switch("border"))
        return scroll

    def _preset_button(self, name, bg, fg, auto, accent):
        area = Gtk.DrawingArea()
        area.set_size_request(64, 26)

        def draw(_w, cr):
            c = rgba(bg)
            cr.set_source_rgba(c.red, c.green, c.blue, max(c.alpha, 0.35))
            w, h = area.get_allocated_width(), area.get_allocated_height()
            r = h / 2
            cr.arc(r, r, r, 1.5708, 4.7124)
            cr.arc(w - r, r, r, -1.5708, 1.5708)
            cr.close_path()
            cr.fill()
            a = rgba(accent)
            cr.set_source_rgb(a.red, a.green, a.blue)
            cr.arc(w - r, r, 4, 0, 6.2832)
            cr.fill()
            t = rgba(fg)
            cr.set_source_rgb(t.red, t.green, t.blue)
            cr.rectangle(r - 2, r - 1.5, w / 2 - r, 3)
            cr.fill()

        area.connect("draw", draw)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(area, False, False, 0)
        box.pack_start(Gtk.Label(label=name), False, False, 0)
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.add(box)

        def apply(*_):
            self.cfg.set("bg_color", bg)
            self.cfg.set("text_color", fg)
            self.cfg.set("accent_auto", auto)
            self.cfg.set("accent_color", accent)

        btn.connect("clicked", apply)
        return btn

    def _page_clock_weather(self):
        scroll, page = self._page()
        clock = self._group(page, "Relógio")
        self._row(clock, "Formato 24 horas", self._switch("clock_24h"))
        self._row(clock, "Mostrar data na pílula", self._switch("show_date"))

        weather = self._group(page, "Clima")
        entry = Gtk.Entry(text=self.cfg["city"], placeholder_text="Detectar pelo IP")
        entry.set_width_chars(18)
        entry.set_max_length(100)
        pending = {"id": None}

        def commit(*_):
            if pending["id"]:
                GLib.source_remove(pending["id"])
                pending["id"] = None
            self.cfg.set("city", entry.get_text().strip())
            return False

        def changed(*_):
            if pending["id"]:
                GLib.source_remove(pending["id"])
            pending["id"] = GLib.timeout_add(900, commit)

        entry.connect("changed", changed)
        entry.connect("activate", commit)
        self._sync["city"] = lambda: (entry.get_text().strip() != self.cfg["city"]
                                      and entry.set_text(self.cfg["city"]))
        self._row(weather, "Cidade", entry, "Deixe vazio para detectar pela sua conexão")
        self._row(weather, "Unidade", self._choice(
            "units", [("celsius", "Celsius (°C)"), ("fahrenheit", "Fahrenheit (°F)")]))
        self._row(weather, "Mostrar clima na pílula", self._switch("show_weather"))
        return scroll

    def _page_behavior(self):
        scroll, page = self._page()
        hover = self._group(page, "Expansão")
        self._row(hover, "Expandir ao passar o mouse", self._switch("hover_expand"),
                  "Desligado: só abre com clique")
        self._row(hover, "Atraso do hover (ms)", self._spin("hover_delay_ms", 0, 2000, 20))
        self._row(hover, "Abrir quando a música mudar", self._switch("peek_on_track"))

        pos = self._group(page, "Posição")
        self._row(pos, "Distância do topo (px)", self._spin("margin_top", 0, 200))

        system = self._group(page, "Sistema")
        sw = Gtk.Switch(active=autostart_enabled())
        sw.connect("notify::active", lambda w, _p: set_autostart(w.get_active()))
        self._row(system, "Iniciar com a sessão", sw)
        return scroll
