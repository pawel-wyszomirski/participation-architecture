#!/usr/bin/env python3
"""Macierz domknięcia: własności N0 na wersji finalnej, każda z własnym sabotażem.

Powstało po recenzji z 2026-09-11 wieczorem. Uwaga recenzenta brzmiała: *nie wystarczy,
że lokalne testy P2/P3/P4 są zielone; potrzebny jest finalny zapis P-A…P-I × wszystkie
dziesięć granic × wersja finalna = green, plus sabotaże*.

Do tej pory sabotaże robiłam ręcznie, jeden po drugim, przy każdym punkcie planu. Ręczny
sabotaż ma dwie wady: nie da się go powtórzyć po kolejnej zmianie i nie widać go w jednym
miejscu. Ten skrypt zamienia je w procedurę.

**Sabotaż, który nie psuje testu, znaczy test, który nie mierzy.** Dlatego skrypt kończy się
kodem 1 nie tylko wtedy, gdy suita jest czerwona, ale też wtedy, gdy psucie kodu NIE wywołało
porażki. W tej sesji ten warunek złapał dwa moje testy: permutacje przechodziły po obu
stronach naprawy, a test anulowań przechodził z wyłączoną obsługą anulowań.

Uruchomienie:
    python3 scripts/macierz-domkniecia.py                # pełna macierz + sabotaże
    python3 scripts/macierz-domkniecia.py --bez-sabotazu # tylko własności (szybciej)
    python3 scripts/macierz-domkniecia.py --zapisz plik.md
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]

# Dziesięć granic potoku z inwentarza N0.1 i własność, która ich pilnuje.
GRANICE = [
    ("1. pozyskanie danych", "P-C, P-G", "tests/test_snapshot_pokrycie.py"),
    ("2. kompletność źródła", "P-C, P-G", "tests/fatigue/test_semantic_closure.py::test_PG_pokwitowanie_rozdziela_dostepnosc_od_pokrycia"),
    ("3. rekonstrukcja i łączenie", "P-A, P-B", "tests/fatigue/test_tozsamosc_powiazania.py"),
    ("4. wejście kanoniczne", "P-B", "tests/fatigue/test_klasa_wejscia.py"),
    ("5. obliczenie składników", "P-A", "tests/fatigue/test_novelty_pokrycie.py"),
    ("6. tożsamość wyniku", "P-A, P-I", "tests/fatigue/test_tozsamosc_artefaktu.py"),
    ("7. zapis i ponowna rejestracja", "P-E", "tests/test_api_per_event.py"),
    ("8. kwalifikacja", "P-C, P-D", "tests/fatigue/test_closure_review.py"),
    ("9. promocja do datasetu", "P-F", "tests/test_granica_promocji.py"),
    ("10. odtworzenie wyniku", "P-E", "tests/test_trwalosc_pomiarow.py"),
]

WLASNOSCI = [
    ("P-A czułość semantyczna", "-k PA_"),
    ("P-B niezależność od transportu", "-k PB_"),
    ("P-C monotoniczność dowodu", "-k PC_"),
    ("P-D poprawna akceptacja", "-k PD_"),
    ("P-E równoważność odtworzenia", "-k PE_"),
    ("P-F zachowanie werdyktu w promocji", "-k PF_"),
    ("P-G kompletność osobno od jakości rekordu", "-k PG_"),
    ("P-H podstawa okna per propozycja", "-k PH_"),
    ("P-I tożsamość artefaktu", "-k PI_"),
]


@dataclass
class Sabotaz:
    """Jedno celowe zepsucie kodu i testy, które MUSZĄ na nie zareagować."""

    opis: str
    plik: str
    stare: str
    nowe: str
    testy: str
    punkt: str


SABOTAZE: List[Sabotaz] = [
    Sabotaz("ścieżka wyścigu oddaje świeży przelicz (stan sprzed P1)",
            "app/main.py",
            "        rywal = _znajdz_pomiar(db, mid)\n        if rywal is None:",
            "        rywal = None\n        if rywal is not None:",
            "tests/test_api_per_event.py -k wyscig", "P1"),
    Sabotaz("PARTIAL i TRUNCATED wracają do stanów dopuszczonych (sprzed P2)",
            "fatigue_config.yaml",
            "eligible_coverage: [COMPLETE, EMPTY_PROVEN]",
            "eligible_coverage: [COMPLETE, EMPTY_PROVEN, PARTIAL_DATA, TRUNCATED]",
            "tests/fatigue/test_semantic_closure.py -k PC_utrata", "P2"),
    Sabotaz("stronicowanie kończy się po pierwszej stronie (sprzed P2)",
            "app/services/snapshot_client.py",
            "                    if len(strona) < limit:\n                        break",
            "                    if True:\n                        break",
            "tests/test_snapshot_pokrycie.py", "P2"),
    Sabotaz("kanoniczny lifecycle_id z pierwszego etapu okna skanu (sprzed P3)",
            "app/services/fatigue_engine.py",
            '            if podstawa in (LINK_EXPLICIT_REFERENCE, LINK_VERIFIED_MAPPING):\n'
            '                surowe = "|".join(sorted(ids))',
            '            if True:\n'
            '                surowe = f"{_klucz_decyzji(pierwszy)}|{int(_czas_glosu(pierwszy))}|{ids[0]}"',
            "tests/fatigue/test_tozsamosc_powiazania.py -k odbior_3", "P3"),
    Sabotaz("powiązanie bez dowodu przestaje dyskwalifikować (sprzed P3)",
            "app/services/fatigue_engine.py",
            "            podstawy_bez_dowodu=domysly, okna_bez_dowodu=okna_bez_dowodu,",
            "            podstawy_bez_dowodu=[], okna_bez_dowodu=okna_bez_dowodu,",
            "tests/fatigue/test_tozsamosc_powiazania.py -k odbior_4", "P3"),
    Sabotaz("anulowania nie skracają okna (sprzed P4)",
            "app/services/governor_client.py",
            "                    anulowane_o = anulowane.get(str(pid))",
            "                    anulowane_o = None",
            "tests/test_okna_glosowania.py -k anulowana", "P4"),
    Sabotaz("okna bez dowodu przestają dyskwalifikować (sprzed P4)",
            "app/services/fatigue_engine.py",
            "            podstawy_bez_dowodu=domysly, okna_bez_dowodu=okna_bez_dowodu,",
            "            podstawy_bez_dowodu=domysly, okna_bez_dowodu=[],",
            "tests/test_okna_glosowania.py -k bez_dowodu", "P4"),
    Sabotaz("novelty bez podstawy - brak kategorii udaje pełny mianownik (sprzed P6)",
            "app/services/fatigue_engine.py",
            "            return self._proposal_is_novel(target), NOVELTY_TARGET_UNKNOWN, pokrycie",
            "            return self._proposal_is_novel(target), NOVELTY_COMPLETE, pokrycie",
            "tests/fatigue/test_novelty_pokrycie.py", "P6"),
    Sabotaz("brak identyfikatora snapshotu taksonomii przechodzi (sprzed P6)",
            "app/services/fatigue_engine.py",
            '        if "taxonomy" in required and not taxonomy_snapshot_id:',
            "        if False:",
            "tests/fatigue/test_novelty_pokrycie.py -k snapshotu", "P6"),
    Sabotaz("nieznana tożsamość kodu przechodzi (sprzed P7)",
            "app/services/fatigue_engine.py",
            '        if str(getattr(self, "code_commit", "") or "") in ("", "unknown"):',
            "        if False:",
            "tests/fatigue/test_tozsamosc_artefaktu.py -k commit", "P7"),
    Sabotaz("ślad wykonawczy stały, nie rozróżnia zależności (sprzed P7)",
            "app/services/fatigue_engine.py",
            "    dane = dict(_wersje_zaleznosci())",
            "    dane = {}",
            "tests/fatigue/test_tozsamosc_artefaktu.py -k zaleznosci", "P7"),
    Sabotaz("eksport manifestów nadpisuje zamiast dopisywać (sprzed P8)",
            "app/services/fatigue_engine.py",
            '        with plik.open("a", encoding="utf-8") as f:',
            '        with plik.open("w", encoding="utf-8") as f:',
            "tests/test_trwalosc_pomiarow.py -k nadpisywania", "P8"),
    Sabotaz("brama promocji nie patrzy na werdykt (sprzed P10)",
            "app/services/promocja.py",
            "    if werdykt and werdykt != ELIGIBLE:",
            "    if False:",
            "tests/test_granica_promocji.py -k niekwalifikowany", "P10"),
    Sabotaz("brak pola nie blokuje promocji - przeciek z eksportu (sprzed P10)",
            "app/services/promocja.py",
            '        if not str(manifest.get(pole) or "").strip():',
            "        if False:",
            "tests/test_granica_promocji.py -k usuniecie_pola", "P10"),
]


def pytest(argumenty: str) -> tuple[bool, str]:
    """Uruchamia pytest i zwraca (czy_zielone, ostatnia linia)."""
    r = subprocess.run(f"python3 -m pytest {argumenty} -q --no-header -p no:cacheprovider",
                       shell=True, cwd=REPO, capture_output=True, text=True, timeout=600)
    linie = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
    return r.returncode == 0, (linie[-1][:120] if linie else "brak wyjścia")


def wykonaj_sabotaz(s: Sabotaz) -> tuple[bool, str]:
    """Psuje kod, sprawdza czy testy PADŁY, przywraca. Zwraca (czy_zadzialal, opis)."""
    plik = REPO / s.plik
    kopia = plik.read_text(encoding="utf-8")
    if s.stare not in kopia:
        return False, "WZORZEC NIEAKTUALNY - sabotaż nie ma czego zepsuć"
    try:
        plik.write_text(kopia.replace(s.stare, s.nowe, 1), encoding="utf-8")
        zielone, opis = pytest(s.testy)
        # Sabotaż DZIAŁA, gdy testy padły. Zielone testy na zepsutym kodzie znaczą test,
        # który nie mierzy tego, co deklaruje.
        return (not zielone), (opis if not zielone else "TESTY PRZESZŁY NA ZEPSUTYM KODZIE")
    finally:
        plik.write_text(kopia, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bez-sabotazu", action="store_true")
    ap.add_argument("--zapisz", help="zapisz macierz do pliku markdown")
    args = ap.parse_args()

    import yaml
    wersja = yaml.safe_load((REPO / "fatigue_config.yaml").read_text(encoding="utf-8"))["version"]
    commit = subprocess.run("git rev-parse --short HEAD", shell=True, cwd=REPO,
                            capture_output=True, text=True).stdout.strip()

    wiersze: List[str] = []
    wiersze.append(f"# Macierz domknięcia - instrument {wersja}, kod {commit}\n")
    wiersze.append("Wygenerowane przez `scripts/macierz-domkniecia.py`. "
                   "Sabotaż, który nie psuje testu, znaczy test, który nie mierzy.\n")

    print("=== SUITA ===", file=sys.stderr)
    cala_zielona, opis_suity = pytest("")
    wiersze.append(f"**Cała suita**: {'ZIELONA' if cala_zielona else 'CZERWONA'} - {opis_suity}\n")

    wiersze.append("\n## Własności P-A…P-I na wersji finalnej\n")
    wiersze.append("| własność | wynik |")
    wiersze.append("|---|---|")
    bledy = 0 if cala_zielona else 1
    for nazwa, filtr in WLASNOSCI:
        print(f"  {nazwa}", file=sys.stderr)
        ok, opis = pytest(f"tests/ {filtr}")
        wiersze.append(f"| {nazwa} | {'zielona' if ok else 'CZERWONA'} - {opis} |")
        bledy += 0 if ok else 1

    wiersze.append("\n## Dziesięć granic potoku i własność, która ich pilnuje\n")
    wiersze.append("| granica | własności | test |")
    wiersze.append("|---|---|---|")
    for granica, wl, test in GRANICE:
        wiersze.append(f"| {granica} | {wl} | `{test}` |")

    if not args.bez_sabotazu:
        wiersze.append("\n## Sabotaże - każdy przywraca kod po sobie\n")
        wiersze.append("| punkt | co zepsute | czy test zareagował |")
        wiersze.append("|---|---|---|")
        print("=== SABOTAŻE ===", file=sys.stderr)
        for s in SABOTAZE:
            print(f"  [{s.punkt}] {s.opis}", file=sys.stderr)
            zadzialal, opis = wykonaj_sabotaz(s)
            wiersze.append(f"| {s.punkt} | {s.opis} | "
                           f"{'TAK' if zadzialal else 'NIE - ' + opis} |")
            bledy += 0 if zadzialal else 1

    tekst = "\n".join(wiersze) + "\n"
    wiersze.append("")
    print(tekst)
    if args.zapisz:
        Path(args.zapisz).write_text(tekst, encoding="utf-8")
        print(f"zapisane: {args.zapisz}", file=sys.stderr)

    if bledy:
        print(f"\nNIEDOMKNIĘTE: {bledy} pozycji wymaga uwagi", file=sys.stderr)
    return 1 if bledy else 0


if __name__ == "__main__":
    raise SystemExit(main())
