"""Leitor de iCalendar (RFC 5545) para a agenda, só com a biblioteca padrão.

Suporta o que agendas reais usam: datas UTC, com TZID, flutuantes e de dia
inteiro; RRULE (DAILY/WEEKLY/MONTHLY/YEARLY com INTERVAL, COUNT, UNTIL,
BYDAY, BYMONTHDAY), EXDATE, instâncias alteradas (RECURRENCE-ID) e canceladas.
Tudo é função pura: recebe texto e janela de tempo, devolve eventos.
"""
import re
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SUPPORTED = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "WKST"}
MAX_STEPS = 5000  # proteção contra regras que não terminam
VIDEO_RE = re.compile(r"https://(?:meet\.google\.com/[a-z0-9-]+|[\w.-]*zoom\.us/j/[\w?=&.-]+|"
                      r"teams\.microsoft\.com/l/meetup-join/[^\s\"<>]+)", re.I)


# --- linhas e propriedades --------------------------------------------------------
def unfold(text):
    """Junta linhas dobradas (continuação começa com espaço ou tab)."""
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line:
            out.append(line)
    return out


def parse_line(line):
    """'NOME;P=V;Q=W:valor' -> (NOME, {P: V}, valor). Respeita aspas nos parâmetros."""
    head, value, quoted = [], None, False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            head, value = line[:i], line[i + 1:]
            break
    if value is None:
        return None
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return name, params, value


def unescape(v):
    return (v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def parse_dt(value, params, local_tz):
    """(datetime com fuso, dia inteiro?) de um DTSTART/DTEND/EXDATE."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=local_tz), True
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc), False
    tzid = params.get("TZID")
    if tzid:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid)), False
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt.replace(tzinfo=local_tz), False  # flutuante: hora local


def parse_duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v)
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


# --- componentes -------------------------------------------------------------------
def parse_vevents(text, local_tz):
    """Lista de dicts crus de cada VEVENT (sem expandir recorrência)."""
    events, cur, depth = [], None, 0
    for line in unfold(text):
        parsed = parse_line(line)
        if not parsed:
            continue
        name, params, value = parsed
        if name == "BEGIN":
            if value.upper() == "VEVENT" and depth == 0:
                cur = {"exdates": [], "attendees": []}
            elif cur is not None:
                depth += 1  # VALARM etc. dentro do evento
            continue
        if name == "END":
            if cur is not None and depth:
                depth -= 1
            elif cur is not None and value.upper() == "VEVENT":
                events.append(cur)
                cur = None
            continue
        if cur is None or depth:
            continue
        try:
            if name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
                cur[name] = parse_dt(value, params, local_tz)
            elif name == "EXDATE":
                for v in value.split(","):
                    cur["exdates"].append(parse_dt(v, params, local_tz)[0])
            elif name == "ATTENDEE":
                cur["attendees"].append((value.lower().removeprefix("mailto:"),
                                         params.get("PARTSTAT", "").upper()))
            elif name in ("SUMMARY", "DESCRIPTION", "LOCATION"):
                cur[name] = unescape(value)
            else:
                cur[name] = value
        except ValueError:
            continue  # linha malformada: ignora só ela
    return events


def owner_from_url(url):
    """E-mail do dono no link do Google (…/calendar/ical/<email>/private-…/basic.ics)."""
    m = re.search(r"/calendar/ical/([^/]+)/", url or "")
    return urllib.parse.unquote(m.group(1)).lower() if m else None


def meeting_link(ev):
    conf = ev.get("X-GOOGLE-CONFERENCE", "")
    if conf.startswith("https://"):
        return conf
    for field in ("LOCATION", "DESCRIPTION", "URL"):
        m = VIDEO_RE.search(ev.get(field, "") or "")
        if m:
            return m.group(0)
    return None


# --- recorrência -----------------------------------------------------------------------
def parse_rrule(value):
    rule = {}
    for part in value.split(";"):
        k, _, v = part.partition("=")
        if k:
            rule[k.upper()] = v
    return rule


def _nth_weekday(year, month, weekday, n):
    """n-ésimo (n<0: a partir do fim) dia da semana do mês, ou None."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
        return d if d.month == month else None
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    d -= timedelta(days=(d.weekday() - weekday) % 7 + 7 * (-n - 1))
    return d if d.month == month else None


def _month_days(year, month, rule, start_day):
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = (nxt - timedelta(days=1)).day
    days = []
    if "BYMONTHDAY" in rule:
        for x in rule["BYMONTHDAY"].split(","):
            n = int(x)
            n = n if n > 0 else last + 1 + n
            if 1 <= n <= last:
                days.append(date(year, month, n))
    elif "BYDAY" in rule:
        for tok in rule["BYDAY"].split(","):
            m = re.fullmatch(r"([+-]?\d+)?([A-Z]{2})", tok)
            if not m or m.group(2) not in WEEKDAYS:
                continue
            wd = WEEKDAYS[m.group(2)]
            if m.group(1):
                d = _nth_weekday(year, month, wd, int(m.group(1)))
                days += [d] if d else []
            else:
                d = date(year, month, 1) + timedelta(days=(wd - date(year, month, 1).weekday()) % 7)
                while d.month == month:
                    days.append(d)
                    d += timedelta(days=7)
    elif start_day <= last:
        days.append(date(year, month, start_day))
    return sorted(days)


def occurrences(start, rule, win_end, win_start=None):
    """Datas-hora de início (mesma hora local do DTSTART) até win_end/COUNT/UNTIL.

    Sem COUNT, pula direto para perto de win_start (reuniões diárias criadas
    há anos não precisam gerar milhares de datas antigas).
    """
    if set(rule) - SUPPORTED:
        yield start  # regra exótica: mostra só a primeira ocorrência
        return
    freq = rule.get("FREQ")
    step = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = None
    if "UNTIL" in rule:
        until, _ = parse_dt(rule["UNTIL"], {}, start.tzinfo)
    tz, t = start.tzinfo, start.timetz().replace(tzinfo=None)

    def at(d):
        return datetime.combine(d, t).replace(tzinfo=tz)

    gap = 0  # dias entre o início da regra e a janela (só sem COUNT)
    if count is None and win_start is not None:
        gap = max(0, (win_start.astimezone(tz).date() - start.date()).days)

    def dates():
        d0 = start.date()
        if freq == "DAILY":
            k = max(0, gap // step - 1)
            for i in range(k, k + MAX_STEPS):
                yield d0 + timedelta(days=i * step)
        elif freq == "WEEKLY":
            wds = sorted(WEEKDAYS[x[-2:]] for x in rule.get("BYDAY", "").split(",")
                         if x[-2:] in WEEKDAYS) or [d0.weekday()]
            week0 = d0 - timedelta(days=d0.weekday())
            k = max(0, gap // 7 // step - 1)
            for i in range(k, k + MAX_STEPS):
                wk = week0 + timedelta(weeks=i * step)
                for wd in wds:
                    yield wk + timedelta(days=wd)
        elif freq == "MONTHLY":
            y, m = d0.year, d0.month
            jump = max(0, (gap // 31) // step - 1) * step
            y, m = y + (m - 1 + jump) // 12, (m - 1 + jump) % 12 + 1
            for _ in range(MAX_STEPS):
                yield from _month_days(y, m, rule, d0.day)
                m += step
                y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        elif freq == "YEARLY":
            k = max(0, gap // 366 // step - 1)
            for i in range(k, k + MAX_STEPS // 12):
                try:
                    yield d0.replace(year=d0.year + i * step)
                except ValueError:  # 29/02 em ano não bissexto
                    continue
        else:
            yield d0

    n = 0
    for d in dates():
        if d < start.date():
            continue
        dt = at(d)
        if until and dt > until:
            return
        if dt > win_end:
            return
        n += 1
        if count is not None and n > count:
            return
        yield dt


# --- eventos prontos para a agenda --------------------------------------------------------
def events_between(text, win_start, win_end, owner=None):
    """Eventos (dicts no formato da agenda) que cruzam [win_start, win_end]."""
    local_tz = win_start.tzinfo
    raw = parse_vevents(text, local_tz)
    overrides = {}
    for ev in raw:
        if "RECURRENCE-ID" in ev and "UID" in ev:
            overrides[(ev["UID"], ev["RECURRENCE-ID"][0])] = ev

    out = []

    def add(ev, start, all_day, end):
        if ev.get("STATUS", "").upper() == "CANCELLED":
            return
        if owner and any(a == owner and p == "DECLINED" for a, p in ev["attendees"]):
            return
        if end <= win_start or start >= win_end:
            return
        out.append({
            "id": f"{ev.get('UID', '')}@{start.isoformat()}",
            "title": (ev.get("SUMMARY") or "(sem título)").strip(),
            "start": start.astimezone(local_tz), "end": end.astimezone(local_tz),
            "all_day": all_day, "meet": meeting_link(ev), "html": None,
        })

    for ev in raw:
        if "DTSTART" not in ev or "RECURRENCE-ID" in ev:
            continue
        start, all_day = ev["DTSTART"]
        if "DTEND" in ev:
            length = ev["DTEND"][0] - start
        else:
            dur = parse_duration(ev.get("DURATION", ""))
            length = dur if dur is not None else (timedelta(days=1) if all_day else timedelta(0))
        if "RRULE" not in ev:
            add(ev, start, all_day, start + length)
            continue
        excluded = set(ev["exdates"])
        for occ in occurrences(start, parse_rrule(ev["RRULE"]), win_end, win_start):
            if occ in excluded:
                continue
            ov = overrides.get((ev.get("UID"), occ))
            if ov is not None:
                if "DTSTART" in ov:
                    o_start, o_all = ov["DTSTART"]
                    o_end = ov["DTEND"][0] if "DTEND" in ov else o_start + length
                    merged = {**ev, **{k: v for k, v in ov.items() if k != "RRULE"}}
                    add(merged, o_start, o_all, o_end)
                continue
            add(ev, occ, all_day, occ + length)
    out.sort(key=lambda e: (e["start"], not e["all_day"]))
    return out


def normalize_url(url):
    """Aceita https:// e webcal://; devolve a URL https ou None."""
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url.lower().startswith("https://") or len(url) > 2000 or any(c.isspace() for c in url):
        return None
    return url
