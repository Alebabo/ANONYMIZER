"""Spaltenweise Anonymisierung der Mandate mit Cato und der vorhandenen Engine.

Wiederverwendet aus anonymizer-core:
* ``Detector`` (Regeln + Cato 1.1) für Freitext und Partei-Spalten,
* ``OpenAnonymizer`` für Ersetzung, Sweep (weitere Vorkommen) und strikte Leak-Prüfung,
* ``normalize`` des Vaults für den Abgleich.

Werte aus strukturierten Spalten (Mandant, Firma, Gegner ...) werden auch im Freitext gesucht, auch wenn die
Spalte selbst nicht freigegeben wird. Sie haben Vorrang vor Cato-Treffern ("Berger & Söhne KG" bleibt ein Wert).
Allein stehende Nachnamen ("Herr Albrecht") erhalten das Token des vollen Namens, wenn der Nachname eindeutig ist.

Ergebnis ist eine Vorschau in vault.db. Nach visible.db gelangt nichts ohne :func:`arca.release.release`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid

from anonymizer.anonymize import AnonymizerConfig, LeakError, OpenAnonymizer
from anonymizer.detect import Detector
from anonymizer.models import DEFAULT_CATEGORIES, Category, Detection, make_detection
from anonymizer.vault import normalize

from arca import vault_db
from arca.generalize import generalize, hints, options
from arca.tokens import ArcaVault

NAMESPACE = "arca"
STRUCTURED = {"person", "organization", "case_number", "location", "party"}
WITHHELD = "[ZURÜCKGEHALTEN]"


class PreviewError(ValueError):
    pass


def _whole(value: str, entity_type: str) -> list[Detection]:
    text = value.strip()
    if not text:
        return []
    start = value.index(text)
    return [make_detection(entity_type, DEFAULT_CATEGORIES.get(entity_type, Category.PERSONAL_DATA),
                           start, start + len(text), text, 1.0, "arca-column")]


def _overlaps(d: Detection, others: list[Detection]) -> bool:
    return any(d.start < o.end and o.start < d.end for o in others)


class Known:
    """Bekannte Werte eines Bestands: volle Werte je Typ und eindeutige Nachnamen -> voller Name."""

    def __init__(self, values: dict[str, str], surnames: dict[str, str]) -> None:
        self.values = values        # Wert -> Typ
        self.surnames = surnames    # Nachname -> voller Name
        self._full = self._pattern(values)
        self._parts = self._pattern(surnames)

    @staticmethod
    def _pattern(words) -> re.Pattern | None:
        alts = sorted(words, key=len, reverse=True)
        return re.compile(r"(?<!\w)(" + "|".join(map(re.escape, alts)) + r")(?!\w)") if alts else None

    def full(self, text: str) -> list[tuple[int, int, str]]:
        return [(m.start(), m.end(), self.values[m.group(1)]) for m in self._full.finditer(text)] if self._full else []

    def parts(self, text: str) -> list[tuple[int, int, str]]:
        return [(m.start(), m.end(), "person") for m in self._parts.finditer(text)] if self._parts else []


class ArcaAnonymizer:
    def __init__(self, conn: sqlite3.Connection, secret: bytes, detector: Detector | None = None) -> None:
        self.conn = conn
        self.vault = ArcaVault(conn, secret)
        self.detector = detector or Detector()
        self.engine = OpenAnonymizer(AnonymizerConfig(), vault=self.vault)

    # -- einzelne Zelle --------------------------------------------------
    def _detections(self, value: str, kind: str, known: Known) -> list[Detection]:
        if kind in ("person", "organization", "case_number", "location"):
            return _whole(value, kind)
        if kind == "party":
            text = value.strip()
            for d in self.detector.scan(value, "de").detections:
                if d.entity_type in ("person", "organization") and d.text.strip() == text:
                    return _whole(value, d.entity_type)
            return _whole(value, "person")  # fail closed
        if kind == "text":
            def det(start: int, end: int, entity_type: str, source: str) -> Detection:
                return make_detection(entity_type, DEFAULT_CATEGORIES.get(entity_type, Category.PERSONAL_DATA),
                                      start, end, value[start:end], 0.99, source)
            known_found = [det(s, e, t, "arca-known-value") for s, e, t in known.full(value)]
            cato = list(self.detector.scan(value, "de").detections)
            # Eine Adresse von Cato, die einen bekannten Wert umschließt ("Hafenstraße 41, 28217 Bremen" um
            # "Bremen"), gewinnt; sonst bliebe die Straße stehen.
            wide = [d for d in cato if d.entity_type == "address"
                    and any(d.start <= k.start and k.end <= d.end and d.end - d.start > k.end - k.start
                            for k in known_found)]
            found = wide + [k for k in known_found if not _overlaps(k, wide)]
            found += [d for d in cato if d not in wide and not _overlaps(d, found)]
            for s, e, t in known.parts(value):
                d = det(s, e, t, "arca-known-surname")
                if not _overlaps(d, found):
                    found.append(d)
            return sorted(found, key=lambda d: d.start)
        return []  # money: bleibt lesbar

    def cell(self, value: str, kind: str, known: Known, opts: dict | None = None) -> dict:
        """Eine Zelle anonymisieren, vergröbern (``opts``) und Prüfhinweise anhängen."""
        detections = self._detections(value, kind, known)
        text, spans = value, []
        if detections:
            try:
                result = self.engine.anonymize(value, detections, namespace=NAMESPACE, language="de")
            except LeakError:
                return {"value": WITHHELD, "spans": [{"start": 0, "end": len(WITHHELD), "type": "withheld"}]}
            text = result.text
            spans = [{"start": t.out_start, "end": t.out_end, "type": t.entity_type} for t in result.transformations]
        if opts is not None:
            text, spans = generalize(text, spans, opts)
        if kind == "text":
            spans = sorted(spans + hints(text, spans), key=lambda s: s["start"])
        return {"value": text, "spans": spans}

    def _prepare(self) -> tuple[list[dict], Known]:
        data = vault_db.rows(self.conn)
        known = self.known_values(data)
        self.vault.aliases = {normalize(s): full for s, full in known.surnames.items()}
        return data, known

    def pseudonymize(self, text: str) -> dict:
        """Freitext (z. B. eine Frage an Claude) mit denselben Tokens wie in A. Nicht vergröbert."""
        _, known = self._prepare()
        with self.vault.batch():
            return self.cell(text, "text", known)

    # -- Vorschau ---------------------------------------------------------
    def known_values(self, rows: list[dict]) -> Known:
        empty = Known({}, {})
        values: dict[str, str] = {}
        for row in rows:
            for col, (_, kind) in vault_db.COLUMNS.items():
                if kind in STRUCTURED and row.get(col, "").strip():
                    for d in self._detections(row[col], kind, empty):
                        values.setdefault(d.text, d.entity_type)
        candidates: dict[str, set[str]] = {}
        for value, entity_type in values.items():
            words = value.split()
            if entity_type == "person" and len(words) > 1 and len(words[-1]) >= 3:
                candidates.setdefault(words[-1], set()).add(value)
        surnames = {s: next(iter(full)) for s, full in candidates.items() if len(full) == 1 and s not in values}
        return Known(values, surnames)

    def preview(self, columns: list[str], opts: dict | None = None) -> dict:
        unknown = [c for c in columns if c not in vault_db.COLUMNS]
        if unknown:
            raise PreviewError(f"Unbekannte Spalten: {', '.join(unknown)}")
        if not columns:
            raise PreviewError("Keine Spalte gewählt")
        columns = [c for c in vault_db.COLUMNS if c in columns]  # feste Reihenfolge
        try:
            opts = options(opts)
        except ValueError as exc:
            raise PreviewError(str(exc)) from exc
        data, known = self._prepare()
        out_rows = []
        with self.vault.batch():
            for i, row in enumerate(data, start=1):
                out_rows.append({"zeile": i, "cells": {c: self.cell(row[c], vault_db.COLUMNS[c][1], known, opts)
                                                       for c in columns}})
        n_hints = sum(1 for r in out_rows for c in r["cells"].values() for s in c["spans"] if s["type"] == "check")
        preview = {"id": uuid.uuid4().hex, "created_at": time.time(), "columns": columns, "rows": out_rows,
                   "options": opts, "hints": n_hints}
        self.conn.execute("INSERT INTO preview (id, created_at, columns, payload) VALUES (?, ?, ?, ?)",
                          (preview["id"], preview["created_at"], json.dumps(columns),
                           json.dumps({"rows": out_rows, "options": opts, "hints": n_hints})))
        self.conn.commit()
        return preview
