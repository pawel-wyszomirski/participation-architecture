"""Wyciąga kwotę wnioskowaną z treści propozycji.

DLACZEGO ISTNIEJE
-----------------
Do v0.1.0 model `Proposal` nie miał pola z kwotą, a `proposal_from_db_model`
brało `getattr(db_proposal, 'requested_amount_usd', None)`. Wartość była więc
zawsze `None`, warunek `if amount is None: return` kończył sprawę i **cała
warstwa progów finansowych nie odpalała się nigdy** poza testami syntetycznymi.
Reguły istniały, przechodziły własne testy i nie miały żadnego wpływu na wynik.

CO ROBI, A CZEGO NIE
--------------------
Zwraca kwotę razem z **walutą**, bo to nie to samo. Progi w rulebooku są
w dolarach, a propozycje Arbitrum wnioskują najczęściej o ARB. Przeliczenie
wymaga kursu z konkretnej chwili, którego nie mamy i którego ten moduł nie
zgaduje - wynik w ARB wraca jako ARB.

Gdy kwoty nie ma albo jest w walucie nieprzeliczalnej, **reguła ma to powiedzieć**,
nie przemilczeć. Cichy brak wygląda dokładnie tak samo jak propozycja
bezkosztowa, a to dwie różne rzeczy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: Waluty, w których progi rulebooka (dolarowe) mają sens bez kursu.
STABILNE = {"USD", "USDC", "USDT", "DAI"}

#: Mnozniki skrotem ORAZ slowem. Pierwsza wersja znala tylko skroty, wiec
#: `$12.8 million USD` dawalo 12,8 - wynik milion razy za maly, wygladajacy jak
#: poprawna liczba. Zmierzone na 200 propozycjach Arbitrum: 8 kwot ponizej tysiaca,
#: z czego polowa to wlasnie ten blad.
_MNOZNIKI = {
    "k": 1_000, "thousand": 1_000, "tys": 1_000,
    "m": 1_000_000, "mm": 1_000_000, "mln": 1_000_000, "million": 1_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000,
}
_MNOZNIK_WZ = r"(k|m|mm|b|bn|mln|tys|thousand|million|billion)"

#: `$1,500,000` albo `$1.5M`
_WZ_DOLAR = re.compile(
    r"\$\s*([\d][\d,\.]*)\s*" + _MNOZNIK_WZ + r"?\b", re.I)
#: `1,500,000 ARB`, `1.5M ARB`, `500k USDC`
_WZ_WALUTA = re.compile(
    r"\b([\d][\d,\.]*)\s*" + _MNOZNIK_WZ + r"?\s*(ARB|USDC|USDT|DAI|ETH|USD)\b", re.I)


@dataclass
class Kwota:
    wartosc: float
    waluta: str
    fragment: str          # kawałek tekstu, z którego to wyszło - do audytu

    @property
    def porownywalna_z_progiem_usd(self) -> bool:
        return self.waluta.upper() in STABILNE


def _liczba(surowa: str, mnoznik: Optional[str]) -> Optional[float]:
    czysta = surowa.replace(",", "")
    # `1.500.000` (zapis europejski) kontra `1.5` - kropka jako separator tysięcy
    # ma zawsze trzy cyfry po sobie i występuje więcej niż raz albo kończy grupę.
    if czysta.count(".") > 1:
        czysta = czysta.replace(".", "")
    elif "." in czysta:
        calosc, _, reszta = czysta.partition(".")
        if len(reszta) == 3 and not mnoznik:
            czysta = calosc + reszta
    try:
        w = float(czysta)
    except ValueError:
        return None
    if mnoznik:
        w *= _MNOZNIKI[mnoznik.lower()]
    return w


#: Słowa, obok których stoi kwota WNIOSKOWANA.
_PROSBA = re.compile(
    r"\b(request(?:ing|ed|s)?|ask(?:ing)?\s+for|allocat\w*|fund(?:ing)?|"
    r"budget|grant(?:ing)?|disburs\w*|transfer\s+of|total\s+cost)\b", re.I)

#: Słowa, obok których stoi kwota NIE będąca wnioskiem - stan skarbca, obrót,
#: kapitalizacja. Bez tego „the DAO holds $3.2B in treasury but we ask for
#: 100,000 ARB" dawało 3,2 mld: największa liczba w tekście opisywała skarbiec.
_TLO = re.compile(
    r"\b(treasury\s+(?:holds|balance|of|size)|holds|balance|market\s+cap|"
    r"tvl|total\s+value\s+locked|revenue|circulating)\b", re.I)

#: Granice zdań. Kontekstem liczby jest JEJ zdanie, nie okno znaków wokół niej.
#: Wersja z oknem myliła się na „Market cap is $5B. We are requesting 750,000
#: USDC" - słowo prośby z następnego zdania stało bliżej niż słowo tła z tego
#: samego. Liczba należy do zdania, w którym stoi, i tam trzeba jej szukać sensu.
_ZDANIE = re.compile(r"(?<=[.!?;\n])\s+")


def wyciagnij(tekst: str) -> Optional[Kwota]:
    """Kwota WNIOSKOWANA albo None.

    Wybór nie jest „największa liczba w tekście". Propozycje podają obok siebie
    kwotę wniosku, pozycje rozbicia budżetu i wielkości tła - stan skarbca,
    kapitalizację. Największa z nich zwykle opisuje tło, nie wniosek.

    Kolejność: kwoty stojące przy słowach prośby, z pominięciem tych stojących
    przy słowach tła. Dopiero gdy żadna nie ma takiego kontekstu, bierzemy
    największą - z zastrzeżeniem, że to zgadywanie i nadaje się do progu
    orientacyjnego, nie do decyzji finansowej.
    """
    if not tekst:
        return None

    kandydaci: list[tuple[float, str, str, bool]] = []   # (wartość, waluta, fragment, prosba)

    def _blizej(wzorzec: re.Pattern, zdanie: str, poz: int) -> Optional[int]:
        odl = [abs(x.start() - poz) for x in wzorzec.finditer(zdanie)]
        return min(odl) if odl else None

    def zbierz(zdanie: str, w: Optional[float], waluta: str, m: re.Match) -> None:
        if w is None or w <= 0:
            return
        prosba = bool(_PROSBA.search(zdanie))
        tlo = bool(_TLO.search(zdanie))
        if tlo and not prosba:
            return                     # całe zdanie opisuje tło, nie wniosek
        if tlo and prosba:
            # Jedno zdanie niosące obie rzeczy: „the DAO holds $3.2B in treasury
            # but we ask for 100,000 ARB". Rozstrzyga, do którego słowa liczbie
            # bliżej. Bez tego wygrywała większa, czyli stan skarbca.
            d_p = _blizej(_PROSBA, zdanie, m.start())
            d_t = _blizej(_TLO, zdanie, m.start())
            if d_t is not None and (d_p is None or d_t < d_p):
                return
        fragment = zdanie.strip()[:110]
        kandydaci.append((w, waluta.upper(), fragment, prosba))

    for zdanie in _ZDANIE.split(tekst):
        for m in _WZ_DOLAR.finditer(zdanie):
            zbierz(zdanie, _liczba(m.group(1), m.group(2)), "USD", m)
        for m in _WZ_WALUTA.finditer(zdanie):
            zbierz(zdanie, _liczba(m.group(1), m.group(2)), m.group(3), m)

    if not kandydaci:
        return None

    przy_prosbie = [k for k in kandydaci if k[3]]
    wybrane = max(przy_prosbie or kandydaci, key=lambda k: k[0])
    return Kwota(wybrane[0], wybrane[1], wybrane[2])
