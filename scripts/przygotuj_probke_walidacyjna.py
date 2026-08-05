#!/usr/bin/env python3
"""Przygotowuje próbkę propozycji do RĘCZNEGO oznaczenia (zarzut Z9).

PO CO
-----
`validate_ex_ante.py` wykrywa fałszywe trafienia listą słów w tytule, uruchamianą
na tym samym korpusie, na którym strojono reguły. To sprawdza spójność heurystyki
z regułami, nie ich trafność. Bez niezależnie oznaczonej prawdy nie da się podać
ani liczby fałszywych trafień, ani przeoczeń - a raport grantowy podawał obie.

CO ROBI
-------
Losuje warstwową próbkę i zapisuje arkusz do oznaczenia. Arkusz **NIE POKAZUJE
WYNIKU REGUŁ** - oznaczający widzi tytuł, fragment treści i stan, i decyduje sam.
Pokazanie klasyfikacji przed oceną zakotwiczyłoby ją i unieważniło cały pomiar;
to ta sama pułapka, przed którą broni decyzja D8 w protokole think-aloud.

WARSTWY
-------
Losowanie proste dałoby prawie same propozycje operacyjne i grantowe, bo takie
stanowią większość korpusu. Rzadkie kategorie - incydent, zmiana konstytucji -
nie trafiłyby do próbki wcale, a to właśnie na nich reguła bezpieczeństwa ma
działać. Stąd warstwy po długości i stanie propozycji, oraz świadome dołożenie
wszystkich propozycji zawierających słowa incydentu.

UŻYCIE
------
    python3 scripts/przygotuj_probke_walidacyjna.py --ile 50
    python3 scripts/przygotuj_probke_walidacyjna.py --ile 80 --plik probka.md
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.append(os.getcwd())

DB = "participation.db"
ZIARNO = 20260805          # losowanie ma być odtwarzalne


KRYTERIA = """\
# Próbka walidacyjna - instrukcja oznaczania

Oceniasz KAŻDĄ propozycję niezależnie, **nie znając wyniku reguł**. To celowe:
wynik pokazany przed oceną zakotwiczyłby ją i unieważnił pomiar.

Dla każdej pozycji wpisz w kolumnach `[ ]` znak `x` tam, gdzie odpowiedź brzmi TAK.

## Kolumny

**INCYDENT** - czy to AKTYWNY incydent bezpieczeństwa wymagający pilnej reakcji?
Tak: trwający atak, wykryta podatność wymagająca łatki, awaryjne zatrzymanie
protokołu, nieplanowany hard fork w reakcji na zagrożenie.
Nie: analiza po fakcie, raport z audytu, propozycja procedury na przyszłość,
wybory do rady bezpieczeństwa.

**PROTOKÓŁ** - czy zmienia kod albo parametry protokołu?
Tak: aktualizacja ArbOS, zmiana kontraktu, zmiana parametru sieci.
Nie: zmiana procesu zarządzania, budżet zespołu technicznego.

**SKARBIEC** - czy wnioskuje o wydanie środków DAO?
Tak: grant, finansowanie zespołu, alokacja na program.
Nie: raport z wydatków, propozycja zmiany procedury budżetowej.

**PILNE** - czy zwłoka w decyzji ma realny koszt?
Tak: termin narzucony z zewnątrz, ryzyko rosnące z czasem.
Nie: sprawa organizacyjna bez terminu.

## Zasady

- Oceniasz **treść propozycji**, nie to, jak brzmi tytuł.
- Gdy nie wiesz - zostaw puste i dopisz znak zapytania w `UWAGI`. Puste pole
  to informacja, zgadywanie jej nie zastąpi.
- Nie zaglądaj do wyniku triażu przed oznaczeniem całości.

---

"""


def pobierz(limit_tresci: int = 700) -> list[dict]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, title, body, state, start FROM proposals")
    wiersze = [dict(r) for r in cur.fetchall()]
    conn.close()
    for w in wiersze:
        tresc = (w.get("body") or "").strip().replace("\n", " ")
        w["fragment"] = tresc[:limit_tresci]
        w["slow"] = len(tresc.split())
    return wiersze


SLOWA_INCYDENTU = ("exploit", "hack", "vulnerabilit", "drain", "emergency",
                   "pause", "incident", "attack", "breach")


def probka(wiersze: list[dict], ile: int) -> list[dict]:
    """Warstwowo: stan, długość, plus wszystkie z sygnałem incydentu."""
    los = random.Random(ZIARNO)

    def ma_incydent(w):
        # PELNA tresc, nie fragment. Druga przyczyna tej samej usterki: przy
        # krotszym fragmencie slowo incydentu wypadalo poza okno i propozycja
        # ladowala w innej warstwie. Wszystko, co decyduje o SKLADZIE probki,
        # musi czytac zrodlo, nie jego skrot.
        t = f"{w['title']} {w.get('body') or ''}".lower()
        return any(s in t for s in SLOWA_INCYDENTU)

    incydentowe = [w for w in wiersze if ma_incydent(w)]
    reszta = [w for w in wiersze if not ma_incydent(w)]

    # Wszystkie z sygnalem incydentu - to na nich stoi regula bezpieczenstwa,
    # a jest ich w korpusie garstka. Losowanie proste pominieloby je.
    wybrane = list(incydentowe[:max(1, ile // 3)])

    warstwy: dict[tuple, list] = {}
    for w in reszta:
        dlugosc = "krotka" if w["slow"] < 300 else ("srednia" if w["slow"] < 1200 else "dluga")
        warstwy.setdefault((w["state"], dlugosc), []).append(w)

    brakuje = ile - len(wybrane)
    if brakuje > 0 and warstwy:
        na_warstwe = max(1, brakuje // len(warstwy))
        for klucz in sorted(warstwy):
            los.shuffle(warstwy[klucz])
            wybrane.extend(warstwy[klucz][:na_warstwe])

    los.shuffle(wybrane)
    return wybrane[:ile]


def arkusz(wybrane: list[dict]) -> str:
    czesci = [KRYTERIA]
    for i, w in enumerate(wybrane, 1):
        czesci.append(f"""## {i}. {w['title']}

`{w['id'][:24]}` · stan: {w['state']} · {w['slow']} słów

{w['fragment']}{'…' if w['slow'] > 120 else ''}

| INCYDENT | PROTOKÓŁ | SKARBIEC | PILNE | UWAGI |
|---|---|---|---|---|
| [ ] | [ ] | [ ] | [ ] |  |

---
""")
    return "\n".join(czesci)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ile", type=int, default=50)
    ap.add_argument("--plik", default="probka-walidacyjna.md")
    args = ap.parse_args()

    if not Path(DB).exists():
        raise SystemExit(f"Brak bazy {DB} - najpierw uruchom pobieranie.")

    wiersze = pobierz()
    if len(wiersze) < args.ile:
        raise SystemExit(
            f"Korpus ma {len(wiersze)} propozycji, mniej niz zadana probka {args.ile}.")

    wybrane = probka(wiersze, args.ile)
    Path(args.plik).write_text(arkusz(wybrane), encoding="utf-8")

    import collections
    stany = collections.Counter(w["state"] for w in wybrane)
    print(f"Zapisano {len(wybrane)} propozycji do {args.plik}")
    print(f"  korpus: {len(wiersze)} | stany w probce: {dict(stany)}")
    print(f"  ziarno losowania: {ZIARNO} (powtorzenie da te sama probke)")
    print("\nArkusz NIE pokazuje wyniku regul - to warunek wazności pomiaru.")


if __name__ == "__main__":
    main()
