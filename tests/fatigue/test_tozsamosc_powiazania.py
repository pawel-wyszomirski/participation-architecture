"""P3: heurystyka tytułu nie ma autorytetu tożsamości kanonicznej.

Punkt 3 recenzji 78179 uznałam 10.09 za zamknięty, bo oba kierunki błędu (sklejenie
dwóch decyzji, rozdzielenie jednej) mają testy. Recenzja planu z 11.09 odrzuciła tę
ocenę i ma rację: test dwóch kierunków mówi, że heurystyka działa zgodnie z opisem,
a nie że wolno jej rozstrzygać, czy dwie obserwacje są jedną decyzją.

Kontrakt: każde powiązanie etapów niesie PODSTAWĘ (`link_basis`) i dowód. Powiązanie
bez dowodu (`TITLE_HEURISTIC`, `UNRESOLVED`) nie może cicho wpływać na `volume`,
`burstiness`, `novelty` ani na tożsamość przy werdykcie pierwszorzędnym.

Cztery przypadki odbioru z sekcji 4 planu, plus stabilność identyfikatora cyklu.

Uruchomienie: python3 -m pytest tests/fatigue/test_tozsamosc_powiazania.py -v
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.fatigue_engine import (  # noqa: E402
    HEALTHY_COMPLETE, LINK_EXPLICIT_REFERENCE, LINK_NATIVE_ID, LINK_TITLE_HEURISTIC,
    FatigueEngine, SourceReceipt, merge_stages,
)

T = 1_780_000_000
WYMAGANE = ("snapshot", "governor", "ecosystem", "ecosystem_governor", "taxonomy")


def etap(id_, dni_temu, *, title="ArbOS 61 Elara", body="tresc " * 50, domena="snapshot",
         kategoria="network changes"):
    t = T - dni_temu * 86_400
    return SimpleNamespace(
        id=id_, title=title, body=body, state="closed",
        start=t - 86_400, end=t + 86_400, voted_at=t, cast_at=t,
        category=kategoria, source_domain=domena, source=domena,
        source_vote_id=f"v-{id_}", native_proposal_id=id_, voter="0xA",
        # Okno z dowodem (P4): test dotyczy powiązania etapów, nie podstawy okna.
        window_basis="SNAPSHOT_EXACT", window_uncertainty_reason="",
    )


def pokwitowania():
    return [SourceReceipt(
        z, HEALTHY_COMPLETE, events=3, page_count=1, record_count=3, limit_hit=False,
        taxonomy_snapshot_id="tax:testowy0000000@2026-09-11" if z == "taxonomy" else "")
        for z in WYMAGANE]


@pytest.fixture
def silnik():
    eng = FatigueEngine("fatigue_config.yaml")
    eng.config.setdefault(
        "reference_values_per_event",
        {"volume_7d": 7, "volume_30d": 18, "concurrent": 2, "reading_words": 710})
    return eng


def _teraz():
    return datetime.fromtimestamp(T, timezone.utc)


# ---------------------------------------------------------------------------
# Podstawa powiązania musi istnieć i nazywać dowód
# ---------------------------------------------------------------------------

def test_obserwacja_bez_scalania_ma_podstawe_natywna():
    """Jeden etap to jedna decyzja - tożsamość własna obserwacji, nie domysł."""
    etapy = merge_stages([etap("snap-1", 3)])
    assert len(etapy) == 1
    assert etapy[0].link_basis == LINK_NATIVE_ID
    assert etapy[0].linked_stage_ids == ["snap-1"]


def test_scalanie_po_samym_tytule_jest_oznaczone_jako_heurystyka():
    """Sonda na Snapshocie i głos na kontrakcie pod tym samym tytułem.

    Nic poza znormalizowanym tytułem nie łączy tych dwóch rekordów - i pomiar
    ma to powiedzieć wprost, zamiast oddać jedną decyzję jako fakt.
    """
    etapy = merge_stages([etap("snap-1", 10), etap("governor:core:9", 3, domena="governor:core")])
    assert {e.link_basis for e in etapy} == {LINK_TITLE_HEURISTIC}
    for e in etapy:
        assert sorted(e.linked_stage_ids) == ["governor:core:9", "snap-1"]
        assert "title" in (e.link_evidence or ""), (
            f"dowód ma nazywać, na czym stoi powiązanie: {e.link_evidence!r}")


def test_jawne_odwolanie_w_tresci_jest_dowodem_powiazania():
    """Głos na kontrakcie cytujący identyfikator sondy to dowód, nie zbieżność nazw.

    Wiążąca propozycja w Arbitrum zwykle podaje w opisie identyfikator swojej
    sondy nastrojów. Tam, gdzie to zrobiono, powiązanie przestaje być domysłem -
    i tylko taki cykl wolno liczyć jako jedną decyzję w pomiarze pierwszorzędnym.
    """
    sonda = etap("0xabc123", 10)
    onchain = etap("governor:core:9", 3, domena="governor:core",
                   body="Following the temperature check 0xabc123 the DAO now votes onchain.")
    etapy = merge_stages([sonda, onchain])
    assert {e.link_basis for e in etapy} == {LINK_EXPLICIT_REFERENCE}
    assert all("0xabc123" in (e.link_evidence or "") for e in etapy)


# ---------------------------------------------------------------------------
# Cztery przypadki odbioru z sekcji 4 planu
# ---------------------------------------------------------------------------

def test_odbior_1_rozne_decyzje_ten_sam_tytul_nie_scalaja_sie_cicho():
    """Wybory Rady Bezpieczeństwa wracają co roku pod tą samą nazwą.

    Okno 45 dni je rozdziela - ten test pilnuje, żeby rozdzielenie było widoczne
    w podstawie powiązania, nie tylko w liczbie zdarzeń.
    """
    etapy = merge_stages([etap("snap-2025", 400, title="Security Council Election"),
                          etap("snap-2026", 3, title="Security Council Election")])
    assert len({e.lifecycle_id for e in etapy}) == 2, "dwa lata, dwie decyzje"
    assert {e.link_basis for e in etapy} == {LINK_NATIVE_ID}


def test_odbior_2_ta_sama_decyzja_zmieniony_tytul_zostaje_nierozwiazana():
    """Tytuł zmieniony między warstwami: heurystyka nie widzi powiązania.

    To nie jest usterka do naprawienia tytułem - to granica metody. Pomiar ma
    pokazać dwie obserwacje o własnej tożsamości, nie udawać jednej decyzji ani
    nie chować faktu, że powiązania nie zna.
    """
    etapy = merge_stages([etap("snap-1", 10, title="ArbOS 61 Elara"),
                          etap("governor:core:9", 3, domena="governor:core",
                               title="Upgrade to ArbOS Elara (revised)")])
    assert len({e.lifecycle_id for e in etapy}) == 2
    assert {e.link_basis for e in etapy} == {LINK_NATIVE_ID}


def test_odbior_3_pierwszy_etap_poza_oknem_skanu_nie_zmienia_tozsamosci_pozostalych():
    """NAJWAŻNIEJSZY z czterech: identyfikator cyklu nie może zależeć od tego,
    które etapy akurat wpadły w okno skanu.

    Do 11.09 `lifecycle_id` liczył się z klucza decyzji, czasu PIERWSZEGO etapu
    i jego identyfikatora. Skan o innym zakresie oddawał tę samą decyzję pod innym
    identyfikatorem, więc dwa pomiary tej samej rzeczy nie dawały się porównać -
    a `measurement_id` dziedziczy po tej wartości.
    """
    pelny = merge_stages([etap("snap-1", 20), etap("snap-2", 10), etap("governor:core:9", 3,
                                                                       domena="governor:core")])
    bez_pierwszego = merge_stages([etap("snap-2", 10), etap("governor:core:9", 3,
                                                            domena="governor:core")])

    id_pelny = {e.id: e.lifecycle_id for e in pelny}
    id_bez = {e.id: e.lifecycle_id for e in bez_pierwszego}
    wspolne = set(id_pelny) & set(id_bez)
    assert wspolne, "test nie ma czego porównać"
    for stage_id in wspolne:
        assert id_pelny[stage_id] == id_bez[stage_id], (
            f"etap {stage_id} zmienił przynależność, bo skan nie objął starszego etapu: "
            f"{id_pelny[stage_id]} wobec {id_bez[stage_id]}")


def test_odbior_4_pomiar_zalezny_od_heurystyki_nie_jest_pierwszorzedny(silnik):
    """Powiązanie bez dowodu nie może wpłynąć na liczbę wchodzącą do analizy.

    Historia zawiera dwuetapową decyzję powiązaną wyłącznie tytułem, więc `volume`
    i `burstiness` policzone po cyklach zależą od domysłu. Liczba zostaje policzona
    i zwrócona - werdykt mówi, że do H_val nie wchodzi.
    """
    cel = etap("governor:core:9", 0, domena="governor:core")
    historia = merge_stages([etap("snap-1", 10), etap("snap-1b", 8), cel])
    wynik = silnik.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=historia, now=_teraz(),
        ecosystem_proposals=[], source_receipts=pokwitowania())

    assert wynik.fatigue_score > 0, "liczba ma być policzona"
    assert wynik.identity.eligibility != "PRIMARY_ELIGIBLE"
    assert any("TITLE_HEURISTIC" in x for x in wynik.identity.eligibility_reasons), (
        f"powód ma nazywać podstawę powiązania: {wynik.identity.eligibility_reasons}")


def test_pomiar_na_dowiedzionym_powiazaniu_jest_pierwszorzedny(silnik):
    """Odwrotna strona bramki - bez tego P3 byłoby implementacją „odrzuć wszystko".

    Ten sam kształt historii, ale powiązanie ma dowód w treści: pomiar wchodzi
    do analizy konfirmacyjnej.
    """
    sonda = etap("0xabc123", 10)
    cel = etap("governor:core:9", 0, domena="governor:core",
               body="Temperature check 0xabc123 passed; binding vote follows. " + "tresc " * 40)
    historia = merge_stages([sonda, cel])
    # Ekspozycja NIEPUSTA celowo: pusta lista przy celu z warstwy kontraktowej ma własny,
    # poprawny powód dyskwalifikacji (od 09.09 - pustka może znaczyć „pytaliśmy nie tę
    # warstwę"). Test o powiązaniu etapów musi mierzyć powiązanie, nie tamten warunek.
    ekspozycja = [etap("eco-1", 2, title="Inna propozycja ekosystemu")]
    wynik = silnik.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=historia, now=_teraz(),
        ecosystem_proposals=ekspozycja, source_receipts=pokwitowania())

    assert wynik.identity.eligibility == "PRIMARY_ELIGIBLE", wynik.identity.eligibility_reasons


def test_podstawa_powiazania_przechodzi_przez_wejscie_kanoniczne(silnik):
    """Pole, które rozstrzyga o werdykcie, musi przejść granicę wejścia.

    Projekcja kanoniczna ma ręcznie wypisaną listę pól, więc nowe pole nieuwzględnione
    tam zniknęłoby za granicą - i kwalifikacja liczona z wejścia (P1) przestałaby je
    widzieć. Własność P-A w wersji dla jednego pola.
    """
    cel = etap("governor:core:9", 0, domena="governor:core")
    historia = merge_stages([etap("snap-1", 10), cel])
    wynik = silnik.compute_per_event(
        address="0xA", target_proposal=cel, voted_history=historia, now=_teraz(),
        ecosystem_proposals=[], source_receipts=pokwitowania())

    wejscie = wynik.identity.manifest()["prepared_input"]
    assert wejscie["target"].get("link_basis"), "cel bez podstawy powiązania w wejściu"
    assert all(h.get("link_basis") for h in wejscie["history"]), "historia bez podstaw"
