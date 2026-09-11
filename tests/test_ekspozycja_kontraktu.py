"""Każde pole kontraktu pomiaru ma wyjść przez `/debug/fatigue-config`.

POWÓD (11.09.2026, wdrożenie instrumentu 1.8.0 na produkcję badawczą)
--------------------------------------------------------------------
`sprawdz-wdrozenie.py` orzekł „brakuje: primary_components_per_event,
thresholds_per_event" przy ZGODNYM numerze wersji: produkcja 1.8.0, repozytorium
1.8.0. Numer jechał, pola nie miały którędy wyjść - `get_config_info` wyliczała
pięć kluczy z palca i nie widziała niczego, co dołożyła nowsza wersja instrumentu.
Sześć pól kontraktu (zakres DFI-core, progi per-event, odniesienia per-event,
kwalifikowalność, okno scalania etapów, listy słów) było niewidocznych z zewnątrz.

TRZECIE wystąpienie tej samej klasy w jednej sesji: brama promocji z własną kopią
reguły `novelty`, schemat odpowiedzi gubiący pola manifestu, teraz ekspozycja
konfiguracji. Wzorzec: **źródło ma wartość, warstwa ekspozycji niesie własną,
ręcznie utrzymywaną listę** i rozjeżdża się przy pierwszej zmianie kontraktu.

DLACZEGO STRAŻNIK KLASY, A NIE TEST NA DWA POLA
------------------------------------------------
Test sprawdzający obecność `primary_components_per_event` i `thresholds_per_event`
przechodziłby przy SIÓDMYM polu dołożonym jutro - czyli pilnowałby zapisu, nie
reguły. Ten test czyta plik konfiguracji i wymaga, żeby KAŻDY jego klucz był
widoczny w odpowiedzi, więc następne pole instrumentu jest objęte pomiarem
z chwili, w której powstaje.

Uruchomienie: python3 -m pytest tests/test_ekspozycja_kontraktu.py -q
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.fatigue_engine import FatigueEngine  # noqa: E402

KONFIGURACJA = Path(ROOT) / "fatigue_config.yaml"

# Pola, przez których brak wdrożenie 1.8.0 wyglądało jak kompletne. Stoją tu
# DOSŁOWNIE, bo regresja ma nazywać ten pomiar, nie parafrazę reguły wyżej.
POLA_1_8_0 = ("primary_components_per_event", "thresholds_per_event")


@pytest.fixture(scope="module")
def silnik():
    return FatigueEngine(str(KONFIGURACJA))


@pytest.fixture(scope="module")
def plik():
    return yaml.safe_load(KONFIGURACJA.read_text(encoding="utf-8"))


def test_kazde_pole_konfiguracji_jest_widoczne_z_zewnatrz(silnik, plik):
    """Strażnik KLASY: nowe pole instrumentu nie może zniknąć po cichu."""
    widoczne = silnik.get_config_info()
    brakuje = sorted(k for k in plik if k not in widoczne)
    assert not brakuje, (
        "kontrakt pomiaru ma pola niewidoczne przez /debug/fatigue-config: "
        f"{brakuje}. Ekspozycja nie może wyliczać kluczy z palca - wdrożenie "
        "z takim brakiem wygląda na kompletne, bo numer wersji jedzie osobno."
    )


def test_wartosci_nie_sa_okrojone(silnik, plik):
    """Obecność klucza to za mało - liczy się ta sama treść co w pliku."""
    widoczne = silnik.get_config_info()
    rozne = sorted(k for k, v in plik.items() if widoczne.get(k) != v)
    assert not rozne, f"ekspozycja zmienia wartości kontraktu: {rozne}"


def test_pola_wersji_1_8_0_sa_w_odpowiedzi(silnik):
    """Regresja pomiaru z 11.09 - dokładnie te dwa pola zgłosiła produkcja."""
    widoczne = silnik.get_config_info()
    for pole in POLA_1_8_0:
        assert pole in widoczne, f"{pole} nie wychodzi przez ekspozycję"
    assert widoczne["primary_components_per_event"] == [
        "volume", "concurrency", "burstiness", "reading_time",
    ]
    assert set(widoczne["thresholds_per_event"]) >= {"low", "moderate", "high"}


def test_wersja_i_formuly_opisuja_KOD_nie_plik(silnik):
    """Numer wersji i obie formuły mają być w odpowiedzi - to po nich poznaje się
    wdrożenie. `formula_per_event` niesie dzielnik 0,95, czyli rozstrzygnięcie D2=A."""
    widoczne = silnik.get_config_info()
    assert widoczne["version"] == silnik.version
    assert widoczne["formula"] == silnik.FORMULA
    assert widoczne["formula_per_event"] == silnik.FORMULA_PER_EVENT
    assert "0.95" in widoczne["formula_per_event"]


def test_odpowiedz_jest_kopia_a_nie_uchwytem_do_instrumentu(silnik):
    """Wołający dostaje dane do obejrzenia. Gdyby dostawał uchwyt, zmiana
    u konsumenta cicho przestawiłaby ZAMROŻONY instrument w trakcie rundy."""
    pierwsza = silnik.get_config_info()
    pierwsza["weights"]["volume"] = 0.99
    pierwsza["thresholds_per_event"]["low"] = 1.0

    assert silnik.config["weights"]["volume"] != 0.99
    assert silnik.config["thresholds_per_event"]["low"] != 1.0
    assert silnik.get_config_info()["weights"]["volume"] != 0.99
