"""P8: pomiar przeżywa przebudowę kontenera i utratę bazy.

Sekcja 9 planu domknięcia. Stan przed zmianą (`pa/DEPLOY-prywatny.md`): baza SQLite leży
w `/app/participation.db` WEWNĄTRZ obrazu, bo Dockerfile robi `COPY . .`. Każde
`docker build` bierze plik z drzewa roboczego i zapieka go w nowy obraz, więc zapisy
runtime giną przy wdrożeniu. Dlatego dwóch pomiarów Fazy B nie da się dziś odtworzyć -
nigdy nie zostały zarejestrowane, a gdyby zostały, przebudowa by je skasowała.

Kontrakt z planu, cykl odbioru:

    register -> rebuild container -> read -> destroy container -> restore -> replay

W każdym etapie ten sam `measurement_id`, to samo wejście kanoniczne i pełny wynik.

Ten plik sprawdza to, co da się sprawdzić bez Dockera, i sprawdza rzecz mocniejszą niż
kopia bazy: **manifest wyeksportowany append-only wystarcza do odtworzenia pomiaru**.
Utrata bazy przestaje wtedy być utratą danych badawczych.

Uruchomienie: python3 -m pytest tests/test_trwalosc_pomiarow.py -v
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app.services.fatigue_engine import (  # noqa: E402
    HEALTHY_COMPLETE, FatigueEngine, SourceReceipt, dopisz_manifest, odczytaj_manifesty,
)

T = 1_780_000_000
WYMAGANE = ("snapshot", "governor", "ecosystem", "ecosystem_governor", "taxonomy")


def obs(id_, dni_temu, *, kategoria="grants"):
    t = T - dni_temu * 86_400
    return SimpleNamespace(
        id=id_, title=f"Proposal {id_}", body="tresc " * 60, state="closed",
        start=t - 86_400, end=t + 86_400, voted_at=t, cast_at=t,
        category=kategoria, source_domain="snapshot", source="snapshot",
        source_vote_id=f"v-{id_}", native_proposal_id=id_, voter="0xA",
        window_basis="SNAPSHOT_EXACT", window_uncertainty_reason="",
        lifecycle_id=id_, linked_stage_ids=[id_], link_basis="NATIVE_ID",
    )


def pokwitowania():
    return [SourceReceipt(
        z, HEALTHY_COMPLETE, events=3, page_count=1, record_count=3, limit_hit=False,
        taxonomy_snapshot_id="tax:testowy0000000@2026-09-11" if z == "taxonomy" else "")
        for z in WYMAGANE]


def zmierz(silnik=None):
    eng = silnik or FatigueEngine("fatigue_config.yaml")
    cel = obs("target", 0, kategoria="network changes")
    return eng.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=[cel, obs("h1", 10)],
        now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=[obs("eco-1", 1)], source_receipts=pokwitowania())


# ---------------------------------------------------------------------------
# Eksport append-only
# ---------------------------------------------------------------------------

def test_manifest_dopisuje_sie_bez_nadpisywania(tmp_path):
    """Append-only: nowy pomiar nie może skasować poprzedniego.

    Zapis nadpisujący przy błędzie w jednym pomiarze zabrałby wszystkie wcześniejsze -
    a to jedyna kopia poza bazą.
    """
    katalog = tmp_path / "manifests"
    a = zmierz()
    dopisz_manifest(a.identity.manifest(), katalog=katalog)
    dopisz_manifest({"measurement_id": "inny", "prepared_input": {}}, katalog=katalog)

    wpisy = odczytaj_manifesty(katalog)
    assert len(wpisy) == 2
    assert {w["measurement_id"] for w in wpisy} == {a.identity.measurement_id, "inny"}


def test_ten_sam_pomiar_nie_dubluje_wpisu(tmp_path):
    """Rejestracja jest idempotentna, więc eksport też musi być.

    Bez tego ponowne wywołanie POST rosłoby w pliku bez końca, a liczba wierszy
    przestałaby cokolwiek znaczyć.
    """
    katalog = tmp_path / "manifests"
    a = zmierz()
    dopisz_manifest(a.identity.manifest(), katalog=katalog)
    dopisz_manifest(a.identity.manifest(), katalog=katalog)
    assert len(odczytaj_manifesty(katalog)) == 1


def test_uszkodzony_wiersz_nie_zabiera_pozostalych(tmp_path):
    """Jeden zepsuty wiersz to jeden utracony pomiar, nie cały plik.

    Format wierszowy wybrany właśnie dlatego: uszkodzenie ogona pliku (przerwany zapis,
    pełny dysk) zostawia wcześniejsze wiersze czytelnymi.
    """
    katalog = tmp_path / "manifests"
    a = zmierz()
    dopisz_manifest(a.identity.manifest(), katalog=katalog)
    plik = next(katalog.glob("*.jsonl"))
    with plik.open("a", encoding="utf-8") as f:
        f.write('{"measurement_id": "urwany', )

    wpisy = odczytaj_manifesty(katalog)
    assert len(wpisy) == 1
    assert wpisy[0]["measurement_id"] == a.identity.measurement_id


# ---------------------------------------------------------------------------
# Cykl odbioru: utrata bazy nie jest utratą pomiaru
# ---------------------------------------------------------------------------

def test_odtworzenie_pomiaru_z_samego_eksportu(tmp_path, monkeypatch):
    """Katastrofa: baza znika. Manifest wystarcza do odtworzenia PEŁNEGO wyniku.

    To odpowiednik etapów `destroy container -> restore -> replay` z planu, bez Dockera:
    odtworzenie nie dotyka bazy ani sieci, czyta wyłącznie wyeksportowany wiersz.
    """
    katalog = tmp_path / "manifests"
    zywy = zmierz()
    dopisz_manifest(zywy.identity.manifest(), katalog=katalog)

    # „Czyste środowisko": nowy silnik, brak dostępu do sieci, brak bazy.
    import socket

    def zabronione(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("odtworzenie sięgnęło po zasób zewnętrzny")

    monkeypatch.setattr(socket.socket, "connect", zabronione)

    wpis = odczytaj_manifesty(katalog)[0]
    odtworzony = FatigueEngine.replay(wpis)

    assert odtworzony.identity.measurement_id == zywy.identity.measurement_id
    assert odtworzony.fatigue_score == zywy.fatigue_score
    assert odtworzony.components == zywy.components
    assert odtworzony.metrics == zywy.metrics
    assert odtworzony.identity.eligibility == zywy.identity.eligibility
    assert odtworzony.identity.novelty_basis == zywy.identity.novelty_basis


def test_eksport_niesie_wejscie_kanoniczne(tmp_path):
    """Bez przygotowanego wejścia manifest byłby opisem, nie dowodem."""
    katalog = tmp_path / "manifests"
    a = zmierz()
    dopisz_manifest(a.identity.manifest(), katalog=katalog)
    wpis = odczytaj_manifesty(katalog)[0]

    assert wpis["prepared_input"]["target"]["title"]
    assert wpis["prepared_input"]["config"]["weights"]
    assert wpis["canonical_input_digest"]


def test_pliki_dziela_sie_po_miesiacach(tmp_path):
    """Nazwa pliku niesie miesiąc pomiaru - kopia zapasowa nie rośnie w jeden blok."""
    katalog = tmp_path / "manifests"
    dopisz_manifest(zmierz().identity.manifest(), katalog=katalog)
    pliki = list(katalog.glob("*.jsonl"))
    assert len(pliki) == 1
    assert pliki[0].name.startswith("pomiary-"), pliki[0].name
    assert len(pliki[0].stem.split("-")[1]) == 4, "rok w nazwie"


# ---------------------------------------------------------------------------
# Konfiguracja wdrożenia: baza poza obrazem
# ---------------------------------------------------------------------------

def test_docker_trzyma_baze_na_wolumenie():
    """Baza nie może mieszkać w obrazie - przebudowa kasuje zapisy.

    Sprawdzane na konfiguracji, bo to ona rozstrzyga o wdrożeniu. Dwóch pomiarów Fazy B
    nie da się dziś odtworzyć właśnie z tego powodu (rejestr pomiarów, `uwaga_trwalosc`).
    """
    tresc = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "pa_data:/app/data" in tresc or "/app/data" in tresc, (
        "compose nie montuje katalogu danych")
    assert "DATABASE_URL" in tresc and "/app/data/" in tresc, (
        "DATABASE_URL nie wskazuje na katalog montowany poza obrazem")


def test_dockerfile_nie_kopiuje_bazy_do_obrazu():
    """`COPY . .` zapiekał `participation.db` z drzewa roboczego w obraz."""
    ignore = Path(".dockerignore")
    assert ignore.exists(), "brak .dockerignore - baza z drzewa trafia do obrazu"
    tresc = ignore.read_text(encoding="utf-8")
    assert "participation.db" in tresc
