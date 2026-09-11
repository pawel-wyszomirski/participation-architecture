"""Granica promocji: JEDNA brama do zbioru pierwszorzędnego (P10, plan z 2026-09-11).

Stan przed tą zmianą, sprawdzony w trzech ogniwach 2026-09-11:

1. `pa/analiza/prep-dataset.py:349-356` przy werdykcie innym niż `PRIMARY_ELIGIBLE`
   drukował ostrzeżenie na stderr i **zwracał `fatigue_score` tak samo jak dla
   kwalifikowanego**;
2. `dataset-clean.csv` nie miał kolumny werdyktu, więc informacja nie przechodziła dalej;
3. `pa/analiza/spearman-validation.py:189` brał pary `df[["dfi", name]].dropna()` - filtr
   po brakach danych, żaden filtr kwalifikacji.

Czyli pomiar oznaczony `NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS` wchodził do korelacji H_val jako
zwykła liczba, a jedyny ślad werdyktu ginął w logu. Komentarz w eksporcie mówił „to pozycja
do wykluczenia z H_val, nie do NaN" - wykluczenie miało nastąpić dalej i nie nastąpiło nigdzie.

Reguła planu, sekcja 11: *tylko jedna funkcja może oznaczyć rekord jako dopuszczony do
zbioru H_val; nie wolno filtrować ręcznie po `fatigue_score != null` ani po samym HTTP 200*.

Ten moduł jest tą funkcją. Nie liczy niczego - sprawdza, czy wolno użyć tego, co policzono.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.fatigue_engine import (
    ELIGIBLE, NOVELTY_BASES_PRIMARY, WINDOW_BASES_PRIMARY,
)

# Wersja kontraktu analitycznego. Zmienia się, gdy zmienia się ZNACZENIE zbioru
# pierwszorzędnego: zestaw wymaganych pól albo reguły promocji. Wersja wchodzi do każdego
# wiersza eksportu, żeby analiza mogła odmówić pracy na zbiorze zbudowanym inną regułą.
ANALYSIS_CONTRACT_VERSION = "ac-1.0.0"

# Pola, które MUSZĄ dojść do zbioru analitycznego. Każde odpowiada na inne pytanie:
# skąd liczba, na jakim instrumencie, pod jaką polityką, z jakiego zdarzenia.
POLA_WYMAGANE = (
    "measurement_id",
    "vote_event_id",
    "eligibility",
    "instrument_version",
    "instrument_hash",
    "eligibility_policy_version",
    "code_commit",
)


@dataclass
class WynikPromocji:
    """Czy pomiar wolno użyć w analizie głównej - i dlaczego nie, jeśli nie wolno."""

    dopuszczony: bool
    powody: List[str] = field(default_factory=list)
    wiersz: Dict[str, Any] = field(default_factory=dict)

    @property
    def do_wrazliwosci(self) -> bool:
        """Pomiar niedopuszczony nie jest bezużyteczny - wchodzi do analizy wrażliwości.

        Rozróżnienie jest istotne: „nie do H_val" to nie to samo co „wyrzuć". Liczba dalej
        opisuje coś zmierzonego, tylko z dowodem słabszym niż wymaga analiza konfirmacyjna.
        """
        return not self.dopuszczony and bool(self.wiersz.get("measurement_id"))


def promote_to_primary(manifest: Optional[Dict[str, Any]],
                       wynik: Optional[Dict[str, Any]] = None) -> WynikPromocji:
    """Jedyna brama do zbioru H_val.

    `manifest` to tożsamość pomiaru (`MeasurementIdentity.manifest()` albo kolumna
    `manifest` z bazy), `wynik` to odpowiedź API, gdy jest pod ręką.

    Fail-closed: brak manifestu, brak któregokolwiek pola wymaganego albo werdykt inny niż
    `PRIMARY_ELIGIBLE` kończy się odmową. **Usunięcie pola nie może podnosić kwalifikacji** -
    to jest cały sens tej bramy, bo taki właśnie przeciek był w eksporcie.
    """
    powody: List[str] = []
    if not manifest:
        return WynikPromocji(False, ["brak manifestu pomiaru - nie ma czego promować"])

    for pole in POLA_WYMAGANE:
        if not str(manifest.get(pole) or "").strip():
            powody.append(f"brak pola {pole} - pomiar nie opisuje swojego pochodzenia")

    werdykt = str(manifest.get("eligibility") or "")
    if werdykt and werdykt != ELIGIBLE:
        powody.extend(str(x) for x in (manifest.get("eligibility_reasons") or [werdykt]))

    # Podstawy składników, których werdykt silnika mógł nie objąć - gdy manifest przyszedł
    # ze starszej wersji instrumentu. Sprawdzamy je jeszcze raz U BRAMY, bo brama jest
    # ostatnim miejscem przed analizą: pomiar zapisany pod inną polityką nie przestaje być
    # zapisem, ale nie zna reguł, które obowiązują dziś.
    novelty = str(manifest.get("novelty_basis") or "")
    if novelty and novelty not in NOVELTY_BASES_PRIMARY:
        powody.append(f"novelty basis {novelty} - mianownik składnika nie jest pełny")

    for propozycja in ((manifest.get("prepared_input") or {}).get("ecosystem") or []):
        podstawa = str(propozycja.get("window_basis") or "")
        if podstawa and podstawa not in WINDOW_BASES_PRIMARY:
            powody.append(f"exposure window basis {podstawa} - okno bez dowodu")
            break

    wiersz = {
        "measurement_id": manifest.get("measurement_id", ""),
        "vote_event_id": manifest.get("vote_event_id", ""),
        "eligibility": werdykt,
        "eligibility_reasons": "; ".join(str(x) for x in
                                        (manifest.get("eligibility_reasons") or [])),
        "instrument_version": manifest.get("instrument_version", ""),
        "instrument_hash": manifest.get("instrument_hash", ""),
        "eligibility_policy_version": manifest.get("eligibility_policy_version", ""),
        "novelty_basis": novelty,
        "taxonomy_snapshot_id": manifest.get("taxonomy_snapshot_id", ""),
        "runtime_digest": manifest.get("runtime_digest", ""),
        "code_commit": manifest.get("code_commit", ""),
        "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
        "primary_usable": not powody,
    }
    if wynik:
        wiersz["dfi"] = wynik.get("fatigue_score")
    return WynikPromocji(not powody, powody, wiersz)


def sprawdz_zbior_analityczny(kolumny) -> List[str]:
    """Czego brakuje zbiorowi, żeby analiza mogła go użyć.

    Analiza H_val ma ODMÓWIĆ pracy na zbiorze bez kolumny kwalifikacji, zamiast policzyć
    korelację na wszystkim, co ma liczbę. Brak kolumny to nie „zbiór bez ograniczeń" -
    to zbiór, o którym nie wiadomo, co zawiera.
    """
    posiadane = set(kolumny)
    brakujace = [p for p in ("primary_usable", "eligibility", "measurement_id",
                             "analysis_contract_version") if p not in posiadane]
    return brakujace
