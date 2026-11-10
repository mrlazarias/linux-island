"""Idioma da interface. O texto-fonte é o português; inglês e espanhol vêm dos catálogos.

Uso: `_("Texto em português")` e, com variáveis, `_("em {n} min").format(n=5)`.
O idioma é escolhido uma vez, na abertura (setup); trocar pede reiniciar a ilha.
"""
import os

from locale_en import EN
from locale_es import ES

LANGUAGES = [("auto", "Automático"), ("pt", "Português"), ("en", "English"), ("es", "Español")]
CATALOGS = {"en": EN, "es": ES}

WEEKDAYS = {
    "pt": ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
           "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}
WEEKDAYS_SHORT = {
    "pt": ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "es": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
}
MONTHS = {
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
}
MONTHS_SHORT = {
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"],
}

_current = "pt"


def detect():
    """Idioma do sistema (LANGUAGE, LC_ALL, LC_MESSAGES, LANG); fora pt/es, inglês."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        for part in value.split(":"):
            code = part[:2].lower()
            if code in ("pt", "en", "es"):
                return code
    return "en"


def setup(choice):
    global _current
    _current = detect() if choice == "auto" else (choice if choice in WEEKDAYS else "pt")


def lang():
    return _current


def _(text):
    if _current == "pt":
        return text
    return CATALOGS[_current].get(text, text)


def weekday(i, short=False):
    return (WEEKDAYS_SHORT if short else WEEKDAYS)[_current][i]


def month(i, short=False):
    """i: 1–12."""
    return (MONTHS_SHORT if short else MONTHS)[_current][i - 1]


def long_date(d):
    """'segunda-feira, 9 de novembro' / 'Monday, November 9' / 'lunes, 9 de noviembre'."""
    return _("{weekday}, {day} de {month}").format(
        weekday=weekday(d.weekday()), day=d.day, month=month(d.month))


def short_date(d):
    """'seg 9 nov' / 'Mon Nov 9' / 'lun 9 nov'."""
    return _("{weekday} {day} {month}").format(
        weekday=weekday(d.weekday(), True), day=d.day, month=month(d.month, True))
