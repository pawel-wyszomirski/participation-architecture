#!/usr/bin/env python3
"""Trafność reguł wobec NIEZALEŻNIE oznaczonej próbki (zamyka Z9).

CZYM SIĘ RÓŻNI OD `validate_ex_ante.py`
---------------------------------------
Tamten skrypt wykrywa fałszywe trafienia listą słów w tytule, uruchamianą na tym
samym korpusie, na którym strojono reguły. Sprawdza więc spójność heurystyki
z regułami, nie ich trafność - i mimo to jego wynik trafiał do raportu grantowego
jako liczba fałszywych trafień.

Ten skrypt porównuje wynik reguł z oznaczeniem wykonanym **przed** uruchomieniem
triażu, bez patrzenia na jego wynik. Dopiero to pozwala policzyć czułość
i precyzję.

CZEGO NIE ROZSTRZYGA
--------------------
Jeden oznaczający. Bez drugiego przebiegu nie ma miary zgodności i nie da się
oddzielić błędu oznaczenia od błędu reguły. Arkusz do drugiego przebiegu leży
w `probka-walidacyjna.md`, przy tym samym ziarnie losowania.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.append(os.getcwd())
sys.path.insert(0, "scripts")

from app.services.rule_engine import RuleEngine, proposal_from_db_model  # noqa: E402
from przygotuj_probke_walidacyjna import pobierz, probka                 # noqa: E402

ETYKIETY = Path("scripts/etykiety_walidacyjne.json")

#: Ktora etykieta reguly odpowiada ktorej kolumnie oznaczenia.
ODWZOROWANIE = {
    "incydent": {"INCIDENT", "EMERGENCY"},
    "protokol": {"PROTOCOL_UPGRADE"},
    "skarbiec": {"TREASURY"},
}


class _Wiersz:
    """Adapter na ProposalInput - probka trzyma slowniki, nie modele ORM."""
    def __init__(self, d: dict):
        self.id = d["id"]
        self.title = d["title"]
        self.body = d.get("body") or ""
        self.author = "unknown"
        self.state = d.get("state") or "unknown"
        self.start = d.get("start") or 0
        self.end = 0
        self.created_at = d.get("start") or 0


def macierz(prawda: list[bool], regula: list[bool]) -> dict:
    tp = sum(1 for a, b in zip(prawda, regula) if a and b)
    fp = sum(1 for a, b in zip(prawda, regula) if not a and b)
    fn = sum(1 for a, b in zip(prawda, regula) if a and not b)
    tn = sum(1 for a, b in zip(prawda, regula) if not a and not b)
    czulosc = tp / (tp + fn) if (tp + fn) else None
    precyzja = tp / (tp + fp) if (tp + fp) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "pozytywow_w_prawdzie": tp + fn,
            "czulosc": czulosc, "precyzja": precyzja}


def main() -> None:
    dane = json.loads(ETYKIETY.read_text(encoding="utf-8"))
    etykiety = dane["etykiety"]

    wiersze = pobierz(limit_tresci=420)
    wybrane = probka(wiersze, 50)

    silnik = RuleEngine("rulebook.yaml")
    surowe = {w["id"]: w for w in wiersze}

    kolumny = {k: {"prawda": [], "regula": []} for k in ODWZOROWANIE}
    niepewnych = 0
    ocenionych = 0

    for i, w in enumerate(wybrane, 1):
        ozn = etykiety.get(str(i))
        if not ozn:
            continue
        if ozn.get("niepewne"):
            niepewnych += 1
            continue          # niepewne NIE wchodzi do liczb - puste pole to informacja
        pelny = surowe[w["id"]]
        wynik = silnik.evaluate_proposal(
            proposal_from_db_model(_Wiersz(pelny)), evaluated_at=pelny.get("start") or 0)
        etyk = set(wynik.labels)
        for kol, zbior in ODWZOROWANIE.items():
            kolumny[kol]["prawda"].append(bool(ozn[kol]))
            kolumny[kol]["regula"].append(bool(etyk & zbior))
        ocenionych += 1

    print(f"Probka: {len(wybrane)} | ocenionych: {ocenionych} | "
          f"pominietych jako niepewne: {niepewnych}\n")
    print(f"{'kategoria':<12}{'TP':>4}{'FP':>4}{'FN':>4}{'TN':>5}"
          f"{'czulosc':>10}{'precyzja':>10}")
    wyniki = {}
    for kol in ODWZOROWANIE:
        m = macierz(kolumny[kol]["prawda"], kolumny[kol]["regula"])
        wyniki[kol] = m
        cz = f"{m['czulosc']:.2f}" if m["czulosc"] is not None else "n/d"
        pr = f"{m['precyzja']:.2f}" if m["precyzja"] is not None else "n/d"
        print(f"{kol:<12}{m['tp']:>4}{m['fp']:>4}{m['fn']:>4}{m['tn']:>5}{cz:>10}{pr:>10}")

    print("\nUWAGI DO ODCZYTU")
    for kol, m in wyniki.items():
        if m["pozytywow_w_prawdzie"] == 0:
            print(f"  {kol}: ZERO przypadkow pozytywnych w probce - czulosci NIE DA SIE")
            print(f"      oszacowac. Brak falszywych trafien przy zerze pozytywow nic")
            print(f"      nie mowi o regule.")
    print("\n  Jeden oznaczajacy, brak miary zgodnosci. Drugi przebieg:"
          " probka-walidacyjna.md")


if __name__ == "__main__":
    main()
