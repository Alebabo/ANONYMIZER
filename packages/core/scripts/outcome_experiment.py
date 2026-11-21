"""Machbarkeitsexperiment: Ausgang deutscher Kündigungsschutzklagen aus dem Sachverhalt vorhersagen.

    python packages/core/scripts/outcome_experiment.py download [--dir local/outcome]
    python packages/core/scripts/outcome_experiment.py build    [--dir local/outcome]
    python packages/core/scripts/outcome_experiment.py train    [--dir local/outcome]
    python packages/core/scripts/outcome_experiment.py eval     [--dir local/outcome] [--out datasets/outcome]

Quelle: Open Legal Data (https://de.openlegaldata.io, Datenbank unter ODbL 1.0). Das Hugging-Face-Dataset
openlegaldata/court-decisions-germany ist gated (401 ohne Token); daher die öffentliche API. Die Suche liefert
höchstens 10 Seiten je Anfrage, deshalb wird je Gericht und Suchbegriff abgefragt.

download  Urteile der Arbeitsgerichtsbarkeit mit Kündigungsbezug -> local/outcome/raw/<id>.json
build     Tenor -> Label (stattgegeben / teilweise / abgewiesen, unklar verworfen), Tatbestand -> Eingabetext
          -> local/outcome/cases.jsonl.gz, Stichprobe zur Handprüfung -> local/outcome/label_check.jsonl
train     TF-IDF + LogReg / LinearSVC, Splits zufällig / zeitlich / nach Gericht -> local/outcome/results.json
eval      Ergebnisse + Leakage-Probe + Label-Prüfung -> datasets/outcome/results.json (+ Labeldatei)

Kein Produktfeature: Ziel ist eine belastbare Zahl, ob sich eine Ausgangsprognose lohnt.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from anonymizer.courts import clean_html

API = "https://de.openlegaldata.io/api/"
UA = "OpenAnonymizer-research/0.1 (feasibility study; low rate)"
QUERIES = ["Kündigungsschutzklage", "Kündigung nicht aufgelöst", "Kündigungsschutzantrag",
           "Kündigung unwirksam Arbeitsverhältnis", "Kündigungsschutzgesetz Kündigung"]
LABELS = ["abgewiesen", "teilweise", "stattgegeben"]


# --------------------------------------------------------------------------------------------- download

class Throttled(RuntimeError):
    pass


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed public API
                data = json.load(r)
            if isinstance(data, dict) and data.get("code") == "throttled":
                raise Throttled(data.get("message", "gedrosselt"))
            return data
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404) or attempt == 5:
                raise
            wait = int(exc.headers.get("Retry-After") or 0) or (60 * (attempt + 1) if exc.code == 429 else 2 ** attempt * 2)
            if wait > 600:  # Tageslimit: abbrechen statt stundenlang warten; Fortsetzen ist idempotent
                raise Throttled(f"gedrosselt, Retry-After {wait}s") from exc
            time.sleep(wait)
        except Exception:  # noqa: BLE001 - retry network errors with backoff
            if attempt == 5:
                raise
            time.sleep(2 ** attempt * 2)
    raise RuntimeError("unreachable")


def cmd_download(base: Path, workers: int, delay: float) -> None:
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    raw = base / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    index_path = base / "index.json"
    done_path = base / "index_done.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    if not done_path.exists() or len(done) < 127:
        courts, url = [], f"{API}courts/?jurisdiction=Arbeitsgerichtsbarkeit&page_size=50&format=json"
        while url:
            res = get(url)
            courts += res["results"]
            url = res.get("next")
        courts = [c for c in courts if not c["name"].startswith("Bundes")]  # BAG optional: weggelassen
        print(f"{len(courts)} Gerichte der Arbeitsgerichtsbarkeit", flush=True)
        for court in courts:
            if court["code"] in done:
                continue
            for q in QUERIES[:1]:
                for page in range(1, 11):
                    params = {"court_jurisdiction": "Arbeitsgerichtsbarkeit", "court": court["code"], "text": q,
                              "decision_type": "Urteil", "page_size": 100, "page": page, "format": "json"}
                    try:
                        res = get(f"{API}cases/search/?{urllib.parse.urlencode(params)}")
                    except urllib.error.HTTPError:
                        break
                    except Throttled as exc:
                        index_path.write_text(json.dumps(index))
                        done_path.write_text(json.dumps(sorted(done)))
                        sys.exit(f"{exc} - Index gespeichert ({len(index)}), später fortsetzen")
                    for h in res["results"]:
                        index[str(h["id"])] = {"court": court["name"], "court_code": court["code"],
                                               "date": h.get("date"), "type": h.get("decision_type")}
                    if not res.get("next"):
                        break
            done.add(court["code"])
            index_path.write_text(json.dumps(index))
            done_path.write_text(json.dumps(sorted(done)))
            print(f"  {court['code']}: {len(index)} gesamt", flush=True)
        done_path.write_text(json.dumps(sorted(set(done) | {c["code"] for c in courts})))
    print(f"{len(index)} Urteile im Index", flush=True)

    def fetch(case_id: str) -> None:
        path = raw / f"{case_id}.json"
        if path.exists():
            return
        if stop:
            return
        try:
            case = get(f"{API}cases/{case_id}/?format=json")
        except Throttled as exc:
            stop.append(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - skip one case, keep the run going
            print(f"skip {case_id}: {exc}", flush=True)
            return
        court = case.get("court") or {}
        path.write_text(json.dumps({
            "id": case.get("id"), "court": court.get("name"), "court_slug": court.get("slug"),
            "file_number": case.get("file_number"), "date": case.get("date"), "type": case.get("type"),
            "content": case.get("content")}, ensure_ascii=False), encoding="utf-8")
        time.sleep(delay)

    stop: list[str] = []
    # Nur Arbeitsgerichte (LAG/BAG werden im build ohnehin weggelassen) -> spart Abrufe
    todo = [i for i, m in index.items() if not (raw / f"{i}.json").exists()
            and not re.search(r"Landesarbeits|Bundesarbeits", m["court"])]
    print(f"{len(todo)} zu laden", flush=True)
    with ThreadPoolExecutor(workers) as pool:
        for n, _ in enumerate(pool.map(fetch, todo), 1):
            if n % 200 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
    if stop:
        sys.exit(f"{stop[0]} - bisher {len(list(raw.glob('*.json')))} Urteile geladen, später fortsetzen")


# ------------------------------------------------------------------------------------------------ build

HEAD = r"(?:Tenor|Tatbestand|Entscheidungsgründe|Gründe|Rechtsmittelbelehrung|Leitsatz|Leitsätze|Orientierungssatz)"
_HEAD_LINE = re.compile(rf"^\s*(?:[IVX]+\.\s*)?{HEAD}\s*:?\s*$", re.M)

# Antrag einer Kündigungsschutzklage: "festzustellen, dass das Arbeitsverhältnis ... durch die Kündigung ... nicht
# aufgelöst ..." (auch "nicht beendet"). Nur Urteile mit so einem Antrag oder dem Wort Kündigungsschutzklage zählen.
KSCH = re.compile(r"(?:festzustellen|festgestellt),? dass das Arbeitsverhältnis[^.]{0,400}?Kündigung[^.]{0,300}?"
                  r"nicht[^.]{0,120}?(?:aufgelöst|beendet)|Kündigungsschutzklage|Kündigungsschutzantrag"
                  r"|streiten[^.]{0,80}?(?:Wirksamkeit|Rechtswirksamkeit|Rechtmäßigkeit)[^.]{0,120}?Kündigung"
                  r"|streiten[^.]{0,80}?ob das Arbeitsverhältnis[^.]{0,250}?Kündigung[^.]{0,200}?(?:aufgelöst|beendet)", re.S)
# Kläger gewinnt (Kündigung unwirksam / Arbeitsverhältnis nicht aufgelöst):
_END = r"(?:aufgelöst|beendet|geendet|endete|endet|sein Ende gefunden)"
WIN = re.compile(rf"Arbeitsverhältnis[^.]{{0,300}}?(?:nicht|weder)[^.]{{0,400}}?(?:Kündigung|gekündigt)[^.]{{0,300}}?{_END}"
                 r"|Arbeitsverhältnis[^.]{0,400}?(?:Kündigung|gekündigt)[^.]{0,300}?(?:nicht|weder)[^.]{0,120}?(?:aufgelöst|beendet)"
                 r"|(?:Kündigung|Änderungskündigung)[^.]{0,200}?(?:rechts)?unwirksam(?! ist, soweit)"
                 r"|Arbeitsverhältnis[^.]{0,200}?nicht[^.]{0,100}?(?:aufgelöst|beendet)[^.]{0,200}?Kündigung"
                 r"|Änderung der Arbeitsbedingungen[^.]{0,200}?sozial ungerechtfertigt", re.S)
DISMISS_ALL = re.compile(r"(?:Die|die) Klage wird(?: insgesamt)? abgewiesen|(?:Die|die) Klagen? werden abgewiesen")
DISMISS_REST = re.compile(r"(?:Im|im) Übrigen wird die Klage abgewiesen|(?:wird|werden) die Klagen? im Übrigen abgewiesen"
                          r"|Im Übrigen werden die Klagen abgewiesen")
# Teilerfolg innerhalb des Bestandsschutzes: fristlose unwirksam, aber Ende zum Kündigungstermin; Auflösung gegen Abfindung.
PARTIAL = re.compile(r"(?:nicht|erst)[^.]{0,80}?(?:fristlos|außerordentlich)[^.]{0,200}?sondern[^.]{0,120}?"
                     r"(?:erst )?(?:mit Ablauf|zum|am)|sondern (?:erst )?(?:mit Ablauf|zum \d|mit dem \d|am \d)"
                     r"|wird (?:gegen Zahlung einer|zum [^.]{0,40} gegen Zahlung einer) Abfindung[^.]{0,200}?aufgelöst"
                     r"|wird zum [^.]{0,60}?aufgelöst", re.S)
# Kein Sachurteil zum Bestand: Prozessvergleich, Erledigung, Unzulässigkeit, Verwerfung.
OTHER = re.compile(r"als unzulässig verworfen|Rechtsstreit[^.]{0,40}erledigt|Klage[^.]{0,30}unzulässig"
                   r"|Versäumnisurteil[^.]{0,120}aufrechterhalten|nachträgliche Zulassung")


def sections(text: str) -> dict[str, str]:
    """Abschnitte nach Überschriftenzeilen (Tenor, Tatbestand, Entscheidungsgründe ...)."""
    marks = [(m.start(), m.end(), re.sub(r"[^A-Za-zäöüÄÖÜß]", "", m.group()).replace("III", "").replace("II", "")
              .replace("IV", "").lstrip("IVX")) for m in _HEAD_LINE.finditer(text)]
    out: dict[str, str] = {}
    for i, (_, end, name) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        name = "Gründe" if name == "Entscheidungsgründe" else name
        out.setdefault(name, text[end:nxt].strip())
    return out


_MONTHS = r"(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)"


def _unspace_heading(m: re.Match) -> str:
    return "\n" + re.sub(r"\s+", "", m.group(1)).capitalize() + "\n"


def nodots(text: str) -> str:
    """Punkte, die keine Satzgrenze sind (Daten, Beträge, Abkürzungen, Initialen), entfernen; Zeilen bleiben.

    Außerdem gesperrte Überschriften ("T a t b e s t a n d", "1 T A T B E S T A N D :") vereinheitlichen.
    """
    text = re.sub(r"(?m)^[ \t]*(?:\d{1,3}[ \t]+)?((?:[A-Za-zÄÖÜäöü][ \t]+){4,}[A-Za-zÄÖÜäöü])[ \t]*:?[ \t]*$",
                  _unspace_heading, text)
    text = re.sub(r"(?m)^[ \t]*(?:\d{1,3}[ \t]+)?(TENOR|TATBESTAND|ENTSCHEIDUNGSGRÜNDE|GRÜNDE)[ \t]*:?[ \t]*$",
                  lambda m: m.group(1).capitalize(), text)
    t = re.sub(rf"\b\d{{1,2}}\.[ \t]?(?:\d{{1,2}}\.|{_MONTHS}|Jan|Feb|Sept?|Okt|Nov|Dez)\.?[ \t]?(?:\d{{2,4}})?", "DATUM", text)
    t = re.sub(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", "BETRAG", t)
    t = re.sub(r"(?m)^[ \t]*(?:[IVX]+|\d{1,3}|[a-z])\.(?=[ \t])", " ", t)
    t = re.sub(r"\b(?:Nr|Abs|bzw|ggf|z\. ?B|Ziff|Bl|S|vgl|gem|i\. ?V\. ?m|d\. ?h|u\. ?a|v|d\. ?A|f|ff|Az|Rn|Rdnr|"
               r"Dr|Prof|Hr|Fr|ca|insb|evtl|sog|usw|etc|lt|inkl|zzgl|abzgl|zit|aaO|a\. ?a\. ?O|BAG|LAG)\.", lambda m: m.group()[:-1], t)
    t = re.sub(r"\b([A-ZÄÖÜ])\.(?=\s?[A-ZÄÖÜa-zäöü(,)-])", r"\1", t)  # Initialen "M." / "Berlin-T."
    return re.sub(r"(?<=\d)\.(?=\s?(?:Monat|Woche|Jahr|Kammer|Senat|Instanz))", "", t)


def norm_tenor(tenor: str) -> str:
    """Punkte in Daten, Beträgen, Nummerierungen und Abkürzungen entfernen, damit [^.] Satzgrenzen bedeutet."""
    t = re.sub(r"\s+", " ", tenor)
    t = re.sub(rf"\b\d{{1,2}}\.\s?(?:\d{{1,2}}\.|{_MONTHS})\s?\d{{2,4}}", "DATUM", t)
    t = re.sub(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", "BETRAG", t)
    t = re.sub(r"(?:^|(?<=\s))(?:[IVX]+|\d{1,2}|[a-z])\.(?=\s)", " ", t)
    t = re.sub(r"\b(?:Nr|Abs|bzw|ggf|z\.B|Ziff|S|vgl|gem|i\.V\.m|d\.h|u\.a|v)\.", "", t)
    return re.sub(r"\s+", " ", t).strip()


def label_tenor(tenor: str) -> str | None:
    """Label aus dem Tenor oder None (unklar -> verwerfen)."""
    t = norm_tenor(tenor)
    # Kosten-, Streitwert- und Zulassungssätze tragen nichts zum Ausgang bei.
    t = re.sub(r"[^.]*(?:Kosten|Streitwert|Berufung wird|Revision wird|vorläufig vollstreckbar)[^.]*\.", " ", t)
    if OTHER.search(t):
        return None
    win, partial = bool(WIN.search(t)), bool(PARTIAL.search(t))
    dismiss_all, dismiss_rest = bool(DISMISS_ALL.search(t)), bool(DISMISS_REST.search(t))
    if dismiss_all and not (win or partial or dismiss_rest):
        return "abgewiesen"
    if partial and (win or dismiss_rest or not dismiss_all):
        return "teilweise"
    if win and dismiss_rest:
        return "teilweise"
    if win and not dismiss_all:
        return "stattgegeben"
    return None


# Sätze, die den Ausgang oder das Verfahren verraten (auch im Tatbestand vorkommend).
LEAK = re.compile(r"stattgegeben|abgewiesen|Versäumnisurteil|Teilurteil|Urteil|Kammer|Berufung|Revision"
                  r"|Arbeitsgericht|Landesarbeitsgericht|Gericht|Beweis(?:aufnahme| erhoben)|Zeug(?:e|in|en)\b[^.]*vernommen"
                  r"|Sitzungsniederschrift|Protokoll|Güteverhandlung|Gütetermin|Kammertermin|Vergleich", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ\"„(])")
_DATE = re.compile(r"\b\d{1,2}\.\s?(?:\d{1,2}\.|(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober"
                   r"|November|Dezember))\s?(?:\d{2,4})?|\b(?:19|20)\d{2}\b")
_AZ = re.compile(r"\b\d{1,3}\s?(?:Ca|Sa|AZR|Ta|Ga|SaGa|BV|TaBV|Sa\s?\w?)\s?\d+/\d{2,4}\b")


def clean_input(tatbestand: str) -> str:
    """Tatbestand ohne Ausgangs-/Verfahrenssätze, Daten, Aktenzeichen und Gerichtsnamen."""
    keep = [s for s in _SENT.split(tatbestand) if not LEAK.search(s)]
    t = " ".join(keep)
    t = _AZ.sub(" AZ ", t)
    t = _DATE.sub(" DATUM ", t)
    return re.sub(r"\s+", " ", t).strip()


# LAG: Satz, mit dem der Tatbestand das erstinstanzliche Urteil wiedergibt ("Das Arbeitsgericht hat ... abgewiesen").
_ARBG_SENT = re.compile(r"(?:hat|stellte|wies) das Arbeitsgericht[^.]{0,600}?(?:stattgegeben|abgewiesen|festgestellt|"
                        r"erkannt|aufgelöst|verurteilt|zurückgewiesen|entsprochen|fest|ab)\b"
                        r"|(?:Das|das) Arbeitsgericht(?: [A-ZÄÖÜ][\w.-]*(?: (?:am|an der|in der|im) [A-ZÄÖÜ][\w.-]*)?)?"
                        r"(?:,[^.]{0,120},)? hat (?![^.]{0,200}Beweis)[^.]{0,600}?"
                        r"(?:stattgegeben|abgewiesen|festgestellt|erkannt|aufgelöst|verurteilt|zurückgewiesen|entsprochen)")
_ARBG_END = re.compile(r"(?:Zur Begründung|Zu den Gründen|Wegen der (?:weiteren )?(?:Einzelheiten|Begründung)|Gegen (?:dieses|das)"
                       r"|Das Urteil ist|Mit (?:der|ihrer|seiner) Berufung|Hinsichtlich der Begründung|Die Kammer hat)")


def label_first_instance(text: str) -> str | None:
    """Label aus der Wiedergabe des ArbG-Urteils im LAG-Tatbestand."""
    sents = _SENT.split(norm_tenor(text))
    # erster Satz + Folgesätze im Indikativ, die weitere Aussprüche enthalten (keine Begründung im Konjunktiv)
    keep = sents[:1] + [x for x in sents[1:4] if re.search(r"abgewiesen|stattgegeben|festgestellt|verurteilt|entsprochen"
                                                            r"|aufgelöst|erkannt", x)
                        and not re.search(r"\b(?:sei|seien|habe|hätten?|wäre|ausgeführt|begründet)\b", x)]
    t = " ".join(keep)
    if "erkannt" in sents[0] and len(sents) > 1:  # "hat wie folgt erkannt:" -> folgender Tenor
        t = " ".join(sents[:6])
    t = t.replace("entsprochen", "stattgegeben")
    t = re.sub(r"[^.]*(?:Kosten|Streitwert|Revision|vorläufig vollstreckbar)(?![^.]*Kündigung)[^.]*\.", " ", t)
    if re.search(r"Teil-?[Uu]rteil|Versäumnisurteil|unzulässig|verworfen|mittlerweile|[Rr]echtskr|Vorprozess|"
                 r"Parallelverfahren|Vorverfahren|in (?:diesem|jenem|einem anderen) Verfahren|Vergleich[^.]{0,60}(?:geendet|beendet|erledigt)", t):
        return None  # anderes Verfahren oder kein Sachurteil
    if re.search(r"Abfindung", t) and not WIN.search(t) and not re.search(r"Kündigungsschutz", t):
        return None  # Abfindungs-/Zahlungsklage statt Bestandsschutz
    t = re.sub(r"(?:überwiegend|weitgehend|größtenteils|im Wesentlichen|zum großen Teil) stattgegeben", "teilweise stattgegeben", t)
    win = bool(WIN.search(t)) or bool(re.search(r"(?<!teilweise )(?<!insoweit )(?:der|den) (?:Kündigungsschutz|Änderungsschutz)?[Kk]lagen? "
                                                 r"(?:[^.]{0,250} )?stattgegeben", t))
    part = bool(re.search(r"teilweise stattgegeben|[Ii]m Übrigen[^.]{0,80}?abgewiesen|"
                          r"Klage im Übrigen abgewiesen|insoweit stattgegeben|zum Teil stattgegeben|weitergehende Klage abgewiesen", t)) or bool(PARTIAL.search(t))
    dismiss = bool(re.search(r"(?:die|der) (?:Kündigungsschutz)?[Kk]lagen?\b[^.]{0,250}?abgewiesen", t))
    if win and not part and not dismiss:
        return "stattgegeben"
    if (win or "stattgegeben" in t) and part:
        return "teilweise"
    if dismiss and not win and not part and "stattgegeben" not in t:
        return "abgewiesen"
    return None


def iter_raw(base: Path):
    for p in sorted((base / "raw").glob("*.json")):
        try:
            yield json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:  # gerade im Schreiben
            continue


def cmd_build(base: Path) -> None:
    stats: Counter = Counter()
    rows = []
    for case in iter_raw(base):
        stats["urteile"] += 1
        court = case.get("court") or ""
        if court.startswith("Bundes"):
            stats["bag_ausgelassen"] += 1
            continue
        level = "LAG" if "Landesarbeits" in court else "ArbG"
        text = nodots(clean_html(case.get("content") or ""))
        if not KSCH.search(text):
            stats["kein_kschg_antrag"] += 1
            continue
        sec = sections(text)
        tenor, tb = sec.get("Tenor", ""), sec.get("Tatbestand", "")
        if not tenor or not tb:
            stats["ohne_tenor_oder_tatbestand"] += 1
            continue
        if level == "LAG":
            # Nur erstinstanzlicher Sachverhalt: Tatbestand bis zur Wiedergabe des ArbG-Urteils; Label = dessen Ausgang.
            m = _ARBG_SENT.search(tb)
            if not m:
                stats["lag_ohne_arbg_satz"] += 1
                continue
            start = tb.rfind(".", 0, m.start()) + 1
            rest = tb[start:start + 2500]
            e = _ARBG_END.search(rest, m.end() - start)
            label = label_first_instance(rest[:e.start()] if e else rest[:1200])
            tenor, tb = rest[:e.start() if e else 1200], tb[:start]
        else:
            label = label_tenor(tenor)
        if label is None:
            stats["label_unklar"] += 1
            continue
        x = clean_input(tb)
        if len(x) < 400:
            stats["eingabe_zu_kurz"] += 1
            continue
        stats[f"label_{level}_{label}"] += 1
        rows.append({"id": case["id"], "court": court, "level": level, "date": case.get("date"), "file_number": case.get("file_number"),
                     "label": label, "tenor": re.sub(r"\s+", " ", tenor)[:3000], "x": x})
    # Dubletten (gleiches Gericht + Aktenzeichen) entfernen
    seen, uniq = set(), []
    for r in rows:
        key = (r["court"], r["file_number"])
        near = re.sub(r"\W+", "", r["x"][:400].lower())
        if key in seen or near in seen:
            stats["dublette"] += 1
            continue
        seen.update([key, near])
        uniq.append(r)
    with gzip.open(base / "cases.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in uniq:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rnd = random.Random(int(__import__("os").environ.get("LABEL_SEED", "7")))
    sample = rnd.sample(uniq, min(30, len(uniq)))
    with open(base / "label_check.jsonl", "w", encoding="utf-8") as fh:
        for r in sample:
            fh.write(json.dumps({"id": r["id"], "auto": r["label"], "manual": None, "tenor": r["tenor"][:1500]},
                                ensure_ascii=False) + "\n")
    (base / "build_stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    print(f"{len(uniq)} Fälle -> {base / 'cases.jsonl.gz'}")


# ------------------------------------------------------------------------------------------------ train

PACK = Path("datasets/outcome/raw/decisions.jsonl.gz")


def load_cases(base: Path) -> list[dict]:
    """Gebaute Fälle aus local/outcome/cases.jsonl.gz, sonst das committete Paket (ohne HF-Download nutzbar)."""
    path = base / "cases.jsonl.gz"
    if not path.exists():
        path = PACK
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    rows.sort(key=lambda r: r["id"])  # Reihenfolge fest -> Splits reproduzierbar
    return [{k: r[k] for k in ("id", "court", "level", "date", "file_number", "label", "tenor", "x")} for r in rows]


# Offensichtliche Ausgangsphrasen für die Leakage-Probe.
PROBE_PHRASES = ["stattgegeben", "abgewiesen", "nicht aufgelöst", "aufgelöst worden", "unwirksam", "rechtsunwirksam",
                 "wirksam", "sozial gerechtfertigt", "sozial ungerechtfertigt", "zu Recht", "zu Unrecht", "obsiegt",
                 "unterlegen", "Erfolg", "begründet", "unbegründet", "Urteil", "Berufung", "Abfindung", "fortbesteht",
                 "beendet", "Weiterbeschäftigung"]


def splits(cases: list[dict]) -> dict[str, tuple[list[int], list[int]]]:
    import numpy as np  # noqa: PLC0415
    from sklearn.model_selection import GroupShuffleSplit, train_test_split  # noqa: PLC0415

    idx = list(range(len(cases)))
    y = [c["label"] for c in cases]
    tr, te = train_test_split(idx, test_size=0.2, random_state=0, stratify=y)
    out = {"zufaellig": (tr, te)}
    order = sorted(idx, key=lambda i: (cases[i]["date"] or "", cases[i]["id"]))
    cut = int(len(order) * 0.8)
    out["zeitlich"] = (order[:cut], order[cut:])
    groups = np.array([c["court"] for c in cases])
    best = None
    for seed in range(20):  # Gerichts-Split mit ~20 % Testanteil
        g_tr, g_te = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed).split(idx, groups=groups))
        share = len(g_te) / len(idx)
        if best is None or abs(share - 0.2) < abs(best[2] - 0.2):
            best = (list(g_tr), list(g_te), share)
    out["gericht"] = (best[0], best[1])
    # zeitlich + gerichtsgetrennt: Test = neueste 20 % aus den Testgerichten, Train = ältere Fälle der übrigen Gerichte
    te_courts = {cases[i]["court"] for i in best[1]}
    cutoff = cases[order[cut]]["date"] or ""
    tr2 = [i for i in idx if cases[i]["court"] not in te_courts and (cases[i]["date"] or "") < cutoff]
    te2 = [i for i in idx if cases[i]["court"] in te_courts and (cases[i]["date"] or "") >= cutoff]
    if len(te2) >= 50:
        out["zeitlich+gericht"] = (tr2, te2)
    return out


def metrics(y_true, y_pred, proba=None, classes=None) -> dict:
    import numpy as np  # noqa: PLC0415
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score  # noqa: PLC0415

    m = {"n": len(y_true), "macro_f1": round(f1_score(y_true, y_pred, average="macro", labels=LABELS, zero_division=0), 4),
         "accuracy": round(accuracy_score(y_true, y_pred), 4),
         "recall": {lab: round(r, 4) for lab, r in zip(LABELS, recall_score(
             y_true, y_pred, labels=LABELS, average=None, zero_division=0))},
         "confusion": {"labels": LABELS, "matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist()}}
    m["macro_f1_ci95"] = bootstrap_ci(y_true, y_pred)
    bt = ["erfolg" if v != "abgewiesen" else "abgewiesen" for v in y_true]
    bp = ["erfolg" if v != "abgewiesen" else "abgewiesen" for v in y_pred]
    m["binaer_macro_f1"] = round(f1_score(bt, bp, average="macro", zero_division=0), 4)
    if proba is not None:
        onehot = np.array([[1.0 if yt == c else 0.0 for c in classes] for yt in y_true])
        m["brier"] = round(float(np.mean(np.sum((proba - onehot) ** 2, axis=1))), 4)
    return m


def bootstrap_ci(y_true, y_pred, n: int = 1000) -> list[float]:
    """95-%-Konfidenzintervall für Macro-F1 (Bootstrap über Testfälle)."""
    import numpy as np  # noqa: PLC0415
    from sklearn.metrics import f1_score  # noqa: PLC0415

    rng = np.random.default_rng(0)
    yt, yp = np.array(y_true), np.array(y_pred)
    vals = [f1_score(yt[ix], yp[ix], average="macro", labels=LABELS, zero_division=0)
            for ix in (rng.integers(0, len(yt), len(yt)) for _ in range(n))]
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]


def meta_baseline(cases, tr, te, key) -> list[str]:
    """Häufigstes Label je Gericht bzw. Jahr aus dem Training (Fallback: globale Mehrheit)."""
    from collections import Counter as C  # noqa: PLC0415

    glob = C(cases[i]["label"] for i in tr).most_common(1)[0][0]
    by: dict = {}
    for i in tr:
        by.setdefault(key(cases[i]), C())[cases[i]["label"]] += 1
    return [by[key(cases[i])].most_common(1)[0][0] if key(cases[i]) in by else glob for i in te]


def models():
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
    from sklearn.pipeline import FeatureUnion, make_pipeline  # noqa: PLC0415
    from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415
    from sklearn.svm import LinearSVC  # noqa: PLC0415

    def feats():
        return FeatureUnion([
            ("wort", TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_df=0.9, sublinear_tf=True, max_features=200_000)),
            ("zeichen", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=5, sublinear_tf=True,
                                        max_features=200_000))])
    return {
        "tfidf_logreg": make_pipeline(feats(), LogisticRegression(C=4.0, max_iter=3000, class_weight="balanced")),
        "tfidf_linsvm": make_pipeline(feats(), LinearSVC(C=0.5, class_weight="balanced")),
    }


def probe_model():
    from sklearn.feature_extraction.text import CountVectorizer  # noqa: PLC0415
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
    from sklearn.pipeline import make_pipeline  # noqa: PLC0415

    vocab = sorted({p.lower() for p in PROBE_PHRASES})
    return make_pipeline(CountVectorizer(vocabulary=vocab, ngram_range=(1, 3), lowercase=True, binary=True),
                         LogisticRegression(max_iter=2000, class_weight="balanced"))


def top_features(pipe, k: int = 25) -> dict[str, list[str]]:
    union, clf = pipe.steps[0][1], pipe.steps[-1][1]
    names = []
    for name, vec in union.transformer_list:
        names += [f"{name}:{f}" for f in vec.get_feature_names_out()]
    out = {}
    for ci, cls in enumerate(clf.classes_):
        coef = clf.coef_[ci].toarray().ravel() if hasattr(clf.coef_, "toarray") else clf.coef_[ci]
        out[cls] = [names[j] for j in coef.argsort()[::-1][:k]]
    return out


def cmd_train(base: Path) -> None:
    from collections import Counter as C  # noqa: PLC0415

    cases = load_cases(base)
    X = [c["x"] for c in cases]
    y = [c["label"] for c in cases]
    res: dict = {"n": len(cases), "labels": dict(C(y)), "splits": {}}
    for sname, (tr, te) in splits(cases).items():
        t0 = time.time()
        ytr, yte = [y[i] for i in tr], [y[i] for i in te]
        r: dict = {"n_train": len(tr), "n_test": len(te), "test_labels": dict(C(yte)),
                   "train_dates": [min(cases[i]["date"] for i in tr), max(cases[i]["date"] for i in tr)],
                   "test_dates": [min(cases[i]["date"] for i in te), max(cases[i]["date"] for i in te)]}
        maj = C(ytr).most_common(1)[0][0]
        r["mehrheit"] = metrics(yte, [maj] * len(yte))
        r["nur_gericht"] = metrics(yte, meta_baseline(cases, tr, te, lambda c: c["court"]))
        r["nur_jahr"] = metrics(yte, meta_baseline(cases, tr, te, lambda c: (c["date"] or "")[:4]))
        for mname, pipe in models().items():
            pipe.fit([X[i] for i in tr], ytr)
            pred = pipe.predict([X[i] for i in te])
            proba = pipe.predict_proba([X[i] for i in te]) if hasattr(pipe, "predict_proba") else None
            r[mname] = metrics(yte, list(pred), proba, list(pipe.classes_) if proba is not None else None)
            if sname == "zufaellig" and mname == "tfidf_logreg":
                res["top_features"] = top_features(pipe)
        # Leakage-Probe: nur offensichtliche Ausgangsphrasen, einmal auf Eingabe, einmal (Kontrolle) auf Tenor
        for pname, field in (("probe_eingabe", "x"), ("probe_tenor_kontrolle", "tenor")):
            pm = probe_model()
            pm.fit([cases[i][field] for i in tr], ytr)
            r[pname] = metrics(yte, list(pm.predict([cases[i][field] for i in te])))
        r["sekunden"] = round(time.time() - t0, 1)
        res["splits"][sname] = r
        print(sname, json.dumps({k: (v["macro_f1"] if isinstance(v, dict) and "macro_f1" in v else v)
                                 for k, v in r.items() if k not in ("test_labels",)}, ensure_ascii=False), flush=True)
    (base / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))


# ------------------------------------------------------------------------------------------------- eval

def cmd_eval(base: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    res = json.loads((base / "results.json").read_text())
    res["build"] = json.loads((base / "build_stats.json").read_text())
    # Handprüfungen (von Hand ausgefüllt, siehe datasets/outcome/label_check_runde*.json)
    res["label_check"] = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("label_check_runde*.json"))}
    (out / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    # Labels + Split-Zuordnung (klein) und Paket mit Texten (damit build/train ohne HF-Download laufen)
    import csv  # noqa: PLC0415

    cases = load_cases(base)
    member: dict[int, dict[str, str]] = {c["id"]: {} for c in cases}
    for sname, (tr, te) in splits(cases).items():
        for i in tr:
            member[cases[i]["id"]][sname] = "train"
        for i in te:
            member[cases[i]["id"]][sname] = "test"
    names = ["zufaellig", "zeitlich", "gericht", "zeitlich+gericht"]
    src = {"ArbG": "tenor_arbg", "LAG": "lag_tatbestand_wiedergabe_arbg_urteil"}
    with open(out / "labels.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "court", "level", "date", "file_number", "label", "label_quelle"]
                   + [f"split_{n}" for n in names])
        for c in cases:
            w.writerow([c["id"], c["court"], c["level"], c["date"], c["file_number"], c["label"], src[c["level"]]]
                       + [member[c["id"]].get(n, "-") for n in names])
    if (base / "cases.jsonl.gz").exists():
        PACK.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(PACK, "wt", encoding="utf-8", compresslevel=9) as fh:
            for c in cases:
                fh.write(json.dumps({**c, "type": "Urteil", "label_quelle": src[c["level"]],
                                     "splits": member[c["id"]]}, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"-> {out / 'results.json'}, {out / 'labels.csv'}, {PACK}")


HF_REPO = "openlegaldata/court-decisions-germany"


def cmd_download_hf(base: Path, dump: str) -> None:
    """Parquet-Shards einzeln laden, Urteile der Arbeitsgerichtsbarkeit (ArbG/LAG) behalten, Shard löschen.

    Das Dataset ist gated: Zugang auf huggingface.co beantragen, Token als HF_TOKEN setzen.
    """
    import pyarrow.compute as pc  # noqa: PLC0415
    import pyarrow.parquet as pq  # noqa: PLC0415
    from huggingface_hub import HfApi, hf_hub_download  # noqa: PLC0415

    raw = base / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    tmp = base / "hf_tmp"
    done_path = base / f"hf_done_{dump}.json"
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    files = sorted(f for f in HfApi().list_repo_files(HF_REPO, repo_type="dataset")
                   if f.startswith(f"{dump}/") and f.endswith(".parquet"))
    kept = Counter()
    for f in files:
        if f in done:
            continue
        local = Path(hf_hub_download(HF_REPO, f, repo_type="dataset", local_dir=tmp))
        pf = pq.ParquetFile(local)
        cols = ["id", "court", "file_number", "date", "type", "content"]
        for rg in range(pf.num_row_groups):
            t = pf.read_row_group(rg, columns=cols)
            juris = pc.struct_field(t["court"], "jurisdiction")
            mask = pc.and_(pc.equal(juris, "Arbeitsgerichtsbarkeit"), pc.equal(t["type"], "Urteil"))
            for r in t.filter(mask).to_pylist():
                court = r["court"] or {}
                (raw / f"{r['id']}.json").write_text(json.dumps({
                    "id": r["id"], "court": court.get("name"), "court_slug": court.get("slug"),
                    "file_number": r["file_number"], "date": r["date"], "type": r["type"],
                    "content": r["content"]}, ensure_ascii=False), encoding="utf-8")
                kept["LAG" if "Landesarbeits" in (court.get("name") or "") else
                     "BAG" if (court.get("name") or "").startswith("Bundes") else "ArbG"] += 1
        local.unlink()
        done.add(f)
        done_path.write_text(json.dumps(sorted(done)))
        print(f"{f}: {dict(kept)}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "build", "train", "eval"])
    ap.add_argument("--dir", type=Path, default=Path("local/outcome"))
    ap.add_argument("--out", type=Path, default=Path("datasets/outcome"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--source", choices=["hf", "api"], default="hf")
    ap.add_argument("--dump", default="dump-20260520", help="HF-Ordner, z. B. dump-20260520-1k zum Testen")
    a = ap.parse_args()
    if a.cmd == "download" and a.source == "hf":
        cmd_download_hf(a.dir, a.dump)
    elif a.cmd == "download":
        cmd_download(a.dir, a.workers, a.delay)
    elif a.cmd == "build":
        cmd_build(a.dir)
    elif a.cmd == "train":
        cmd_train(a.dir)
    else:
        cmd_eval(a.dir, a.out)


if __name__ == "__main__":
    main()
