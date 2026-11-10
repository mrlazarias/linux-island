"""Guarda segredos no chaveiro do sistema (libsecret); sem chaveiro, num arquivo 0600."""
import os

from gi.repository import GLib

DIR = os.path.join(GLib.get_user_config_dir(), "linux-island")


class SecretStore:
    def __init__(self, key, label):
        self.key, self.label = key, label
        self.file = os.path.join(DIR, f"{key}.secret")
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
            self._s = Secret
            self._schema = Secret.Schema.new("io.github.mrlazarias.LinuxIsland",
                                             Secret.SchemaFlags.NONE,
                                             {"key": Secret.SchemaAttributeType.STRING})
        except (ValueError, ImportError):
            self._s = None
        self._attrs = {"key": key}

    def load(self):
        if self._s:
            try:
                value = self._s.password_lookup_sync(self._schema, self._attrs, None)
                if value is not None:
                    return value
            except GLib.Error:
                pass
        try:
            with open(self.file) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def save(self, value):
        if self._s:
            try:
                if self._s.password_store_sync(self._schema, self._attrs,
                                               self._s.COLLECTION_DEFAULT,
                                               f"linux-island: {self.label}", value, None):
                    return
            except GLib.Error as e:
                print(f"[island] chaveiro indisponível, usando arquivo: {e.message}")
        os.makedirs(DIR, exist_ok=True)
        tmp = self.file + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
        os.replace(tmp, self.file)

    def clear(self):
        if self._s:
            try:
                self._s.password_clear_sync(self._schema, self._attrs, None)
            except GLib.Error:
                pass
        try:
            os.remove(self.file)
        except FileNotFoundError:
            pass
