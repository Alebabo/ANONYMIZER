"""vault.db (Datenbank B, vertraulich): Originaldaten, Token-Mapping, Vorschauen, Audit-Log.

Alle Demo-Daten sind frei erfunden.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

TABLE = "mandate"

# Spalte -> (Anzeigename, Art). Art steuert die Anonymisierung:
#   person / organization / case_number / location: ganze Zelle ist ein Wert dieses Typs (fail closed)
#   party:    Person oder Firma, Erkennung entscheidet, sonst Person
#   text:     Freitext, Cato-Erkennung plus bekannte Werte aus den anderen Spalten
#   money:    bleibt lesbar (Streitwert)
COLUMNS: dict[str, tuple[str, str]] = {
    "mandant": ("Mandant", "person"),
    "unternehmen": ("Unternehmen", "organization"),
    "gegner": ("Gegner", "party"),
    "aktenzeichen": ("Aktenzeichen", "case_number"),
    "ort": ("Ort", "location"),
    "streitwert": ("Streitwert", "money"),
    "sachverhalt": ("Sachverhalt", "text"),
    "dokumente": ("Dokumente", "text"),   # OCR-/Dokumenttext aus Tabelle dokumente, je Mandat zusammengefasst
}
STORED = [c for c in COLUMNS if c != "dokumente"]

SEED: list[dict[str, str]] = [
    {
        "mandant": "Max Mustermann", "unternehmen": "Muster GmbH", "gegner": "Erika Schneider",
        "aktenzeichen": "3 O 123/24", "ort": "Hamburg", "streitwert": "500.000 €",
        "sachverhalt": "Max Mustermann, Geschäftsführer der Muster GmbH, verlangt von Erika Schneider "
                       "die Rückzahlung eines Darlehens über 500.000 €. Frau Schneider bestreitet den Erhalt "
                       "des Geldes. Der Vertrag wurde am 12.03.2022 in Hamburg geschlossen.",
    },
    {
        "mandant": "Sabine Keller", "unternehmen": "Keller Logistik AG", "gegner": "Nordbau Projekt GmbH",
        "aktenzeichen": "12 U 45/23", "ort": "Bremen", "streitwert": "1.250.000 €",
        "sachverhalt": "Die Keller Logistik AG, vertreten durch Sabine Keller, macht Schadensersatz wegen "
                       "verspäteter Fertigstellung einer Lagerhalle in Bremen geltend. Die Nordbau Projekt GmbH "
                       "beruft sich auf höhere Gewalt.",
    },
    {
        "mandant": "Thomas Berger", "unternehmen": "Berger & Söhne KG", "gegner": "Jonas Albrecht",
        "aktenzeichen": "5 Ca 778/24", "ort": "München", "streitwert": "48.000 €",
        "sachverhalt": "Herr Albrecht war bei der Berger & Söhne KG als Vertriebsleiter beschäftigt und "
                       "klagt gegen die Kündigung vom 30.06.2024. Thomas Berger wirft ihm vor, Kundendaten "
                       "an einen Wettbewerber in München weitergegeben zu haben.",
    },
    {
        "mandant": "Leonie Hartmann", "unternehmen": "Hartmann Dental GmbH", "gegner": "Medtech Leasing AG",
        "aktenzeichen": "2 O 9/25", "ort": "Köln", "streitwert": "86.500 €",
        "sachverhalt": "Leonie Hartmann hat für die Hartmann Dental GmbH ein Röntgengerät von der Medtech "
                       "Leasing AG geleast. Das Gerät fällt seit Monaten aus, die Leasingraten wurden in Köln "
                       "weiter abgebucht.",
    },
    {
        "mandant": "Ahmet Yilmaz", "unternehmen": "Yilmaz Bau GmbH", "gegner": "Stefan Wagner",
        "aktenzeichen": "7 S 214/24", "ort": "Stuttgart", "streitwert": "23.900 €",
        "sachverhalt": "Stefan Wagner hat die Werklohnrechnung der Yilmaz Bau GmbH für Arbeiten an seinem "
                       "Haus in Stuttgart nicht bezahlt. Ahmet Yilmaz hat zweimal gemahnt.",
    },
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id INTEGER PRIMARY KEY,
    {", ".join(f"{c} TEXT NOT NULL" for c in STORED)}
);
CREATE TABLE IF NOT EXISTS dokumente (
    id INTEGER PRIMARY KEY,
    mandat_id INTEGER NOT NULL REFERENCES mandate(id),
    dateiname TEXT NOT NULL,
    sha256 TEXT NOT NULL,       -- Prüfsumme der Originaldatei; die Datei selbst wird nicht gespeichert
    format TEXT NOT NULL,
    ocr INTEGER NOT NULL,       -- 1 = Text stammt aus OCR
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS token_map (
    token TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS preview (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    columns TEXT NOT NULL,      -- JSON-Liste
    payload TEXT NOT NULL       -- JSON: Zeilen mit anonymisierten Werten und Spans
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    action TEXT NOT NULL,
    columns TEXT NOT NULL,      -- JSON-Liste
    row_count INTEGER NOT NULL,
    preview_id TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # Spätere Erweiterung des Audit-Logs: wer (actor) und Details (JSON, z. B. Vergröberung, Prüfhinweise).
    have = {r["name"] for r in conn.execute("PRAGMA table_info(audit_log)")}
    for col in ("actor", "details"):
        if col not in have:
            conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} TEXT")
    conn.commit()
    return conn


def seed(conn: sqlite3.Connection) -> int:
    """Demo-Mandate einfügen, wenn die Tabelle leer ist. Gibt die Zeilenzahl zurück."""
    if conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] == 0:
        cols = STORED
        conn.executemany(
            f"INSERT INTO {TABLE} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [tuple(row[c] for c in cols) for row in SEED],
        )
        conn.commit()
    return conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]


def rows(conn: sqlite3.Connection) -> list[dict]:
    docs: dict[int, list[str]] = {}
    for d in conn.execute("SELECT mandat_id, text FROM dokumente ORDER BY id"):
        docs.setdefault(d["mandat_id"], []).append(d["text"])
    return [{**dict(r), "dokumente": "\n\n".join(docs.get(r["id"], []))}
            for r in conn.execute(f"SELECT * FROM {TABLE} ORDER BY id")]
