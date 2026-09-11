"""
Delegate Fatigue Index (DFI) Engine
====================================
Computes a deterministic, reproducible governance workload score (0-100)
grounded in the theoretical framework of the participation-architecture dissertation.

Theoretical Foundations
-----------------------
The DFI operationalizes two core theoretical constructs:

1. Collective Attention as a Rivalrous Commons (dissertation 2.3.1)
   "Kolektywna uwaga i zdolność do podejmowania decyzji" is explicitly identified
   as a scarce, rivalrous resource in the DAO commons. Volume and concurrency
   components directly measure the depletion rate of this shared resource.

2. Fogg B=MAP: Ability Reduction via Cognitive Load (dissertation 2.2.1)
   "W DAO barierą jest często rozproszenie informacji, niejasne opisy propozycji
   czy brak zwięzłych podsumowań." The reading_time and burstiness components
   operationalize reduced Ability in the behavioral model - more cognitive cost
   means less effective capacity to participate, regardless of motivation.

Component Design
----------------
  Volume       (40%): proposals/7d + proposals/30d, weighted toward recent
  Concurrency  (25%): simultaneously active proposals (parallel decision pressure)
  Burstiness   (20%): this-week spike vs. 4-week rolling average
  Reading Time (10%): avg word count / baseline (proxy for cognitive cost per item)
  Novelty       (5%): novel-domain proposals / total (new patterns cost more)

Formula
-------
  DFI = (0.40×volume + 0.25×concurrency + 0.20×burstiness
         + 0.10×reading_time + 0.05×novelty) × 100

Design Principles
-----------------
- Deterministic: same input always produces same output
- Auditable: response includes all raw metrics and component scores
- Configurable: all weights and reference values in fatigue_config.yaml
- Reproducible: computation is persisted to DB (FatigueSnapshot)
- Ecosystem-level: score reflects shared governance burden (not per-delegate)
  Address parameter is forward-compatible for future per-delegate personalization.
"""

import hashlib
import json
import datetime as dt
from functools import lru_cache
import os
import re
import subprocess
import yaml
import logging
from types import SimpleNamespace
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Instrument state
# ---------------------------------------------------------------------------

class InstrumentInvalid(RuntimeError):
    """The frozen confirmatory instrument cannot be loaded as declared.

    Closure review (/t/30604, 2026-09-03, point 6): a missing or invalid
    fatigue_config.yaml must produce INSTRUMENT_INVALID, not a different
    computation that still calls itself DFI. Until 2026-09-04 the engine fell
    back to built-in defaults with a warning - acceptable for an exploratory
    app, not for an instrument whose reference values are frozen for N=50."""

    code = "INSTRUMENT_INVALID"


# ---------------------------------------------------------------------------
# Source capability receipts (closure review point 2)
# ---------------------------------------------------------------------------

# A count cannot prove source health: a healthy source with zero events, a
# timeout, an HTTP failure, a GraphQL error and a missing API key all used to
# collapse into `0`. Every source now returns one of these explicit states.
HEALTHY_COMPLETE = "HEALTHY_COMPLETE"   # answered, nothing cut off
HEALTHY_EMPTY = "HEALTHY_EMPTY"         # answered, genuinely nothing there
PARTIAL = "PARTIAL"                     # answered, some records lack a field the
                                        # instrument needs (e.g. voting window)
TRUNCATED = "TRUNCATED"                 # answered, hit a page/scan limit - the
                                        # set may be incomplete
UNAVAILABLE = "UNAVAILABLE"             # transport failure: timeout, DNS, RPC down
AUTH_MISSING = "AUTH_MISSING"           # no key/capability to ask at all
ERROR = "ERROR"                         # the source answered with an error
                                        # (HTTP 4xx/5xx, GraphQL errors)
SOURCE_STATES = (HEALTHY_COMPLETE, HEALTHY_EMPTY, PARTIAL, TRUNCATED,
                 UNAVAILABLE, AUTH_MISSING, ERROR)

# Dwa NIEZALEŻNE wymiary pokwitowania (plan domknięcia z 11.09, P2 sekcja 3.1).
# Jeden `state` mieszał dwa pytania: "czy zapytanie się wykonało" i "czy objęliśmy
# cały obszar wymagany przez konstrukt". Mieszał je tak, że odpowiedź na pierwsze
# wystarczała do werdyktu: `HEALTHY_COMPLETE` znaczyło jednocześnie "źródło żyje"
# i "zbiór jest pełny", choć drugiego żaden klient nie dowodził. Recenzja 78179,
# własność P-G: sto procent rekordów poprawnych nie dowodzi kompletności zbioru.
AVAIL_HEALTHY = "HEALTHY"               # źródło odpowiedziało
AVAIL_ERROR = "ERROR"                   # odpowiedziało błędem
AVAIL_UNAVAILABLE = "UNAVAILABLE"       # nie odpowiedziało (transport)
AVAIL_AUTH_MISSING = "AUTH_MISSING"     # nie było czym zapytać
AVAILABILITY_STATES = (AVAIL_HEALTHY, AVAIL_ERROR, AVAIL_UNAVAILABLE, AVAIL_AUTH_MISSING)

COV_COMPLETE = "COMPLETE"               # dowód, że zbiór jest pełny dla konstruktu
COV_EMPTY_PROVEN = "EMPTY_PROVEN"       # dowiedziona pustka: nic nie było, i to wiemy
COV_TRUNCATED = "TRUNCATED"             # limit strony/skanu - zbiór może mieć dziury
COV_PARTIAL_DATA = "PARTIAL_DATA"       # rekordy są, ale części brakuje pola albo źródła
COV_UNKNOWN = "UNKNOWN_COVERAGE"        # nie wiemy, ile obszaru objęliśmy
COV_NONE = "NONE"                       # nie mamy nic
COVERAGE_STATES = (COV_COMPLETE, COV_EMPTY_PROVEN, COV_TRUNCATED, COV_PARTIAL_DATA,
                   COV_UNKNOWN, COV_NONE)

# Rzut starego, jednowymiarowego stanu na parę wymiarów. Istnieje dla zgodności:
# manifesty zapisane przed 11.09 i klienci, którzy jeszcze nie podają wymiarów jawnie,
# muszą dawać ten sam werdykt co przedtem - z jednym wyjątkiem opisanym w `_eligibility`
# (PARTIAL i TRUNCATED przestają kwalifikować, i to jest cała zmiana instrumentu).
_RZUT_STANU = {
    HEALTHY_COMPLETE: (AVAIL_HEALTHY, COV_COMPLETE),
    HEALTHY_EMPTY: (AVAIL_HEALTHY, COV_EMPTY_PROVEN),
    PARTIAL: (AVAIL_HEALTHY, COV_PARTIAL_DATA),
    TRUNCATED: (AVAIL_HEALTHY, COV_TRUNCATED),
    ERROR: (AVAIL_ERROR, COV_NONE),
    UNAVAILABLE: (AVAIL_UNAVAILABLE, COV_NONE),
    AUTH_MISSING: (AVAIL_AUTH_MISSING, COV_NONE),
}

ELIGIBLE = "PRIMARY_ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS"

# NA CZYM STOI POWIĄZANIE ETAPÓW W JEDNĄ DECYZJĘ (plan domknięcia z 11.09, P3).
# Znormalizowany tytuł jest sygnałem kandydata, nie dowodem tożsamości decyzji.
# Do 11.09 różnicy nie było widać: `merge_stages` wiązało etapy po tytule i oddawało
# cykl jako fakt, a `volume`, `burstiness` i `novelty` liczyły się po cyklach.
LINK_NATIVE_ID = "NATIVE_ID"                  # jedna obserwacja - własna tożsamość
LINK_EXPLICIT_REFERENCE = "EXPLICIT_REFERENCE"  # etap cytuje identyfikator drugiego
LINK_VERIFIED_MAPPING = "VERIFIED_MAPPING"    # mapowanie potwierdzone poza tytułem
LINK_TITLE_HEURISTIC = "TITLE_HEURISTIC"      # tylko zbieżność znormalizowanej nazwy
LINK_UNRESOLVED = "UNRESOLVED"                # kandydaci są, powiązania nie znamy
LINK_BASES = (LINK_NATIVE_ID, LINK_EXPLICIT_REFERENCE, LINK_VERIFIED_MAPPING,
              LINK_TITLE_HEURISTIC, LINK_UNRESOLVED)

# Podstawy, które wolno wpuścić do pomiaru konfirmacyjnego. `TITLE_HEURISTIC`
# i `UNRESOLVED` nie dyskwalifikują pomiaru same z siebie - dyskwalifikują wtedy,
# gdy wynik OD NICH ZALEŻY, czyli gdy w liczonej historii stoi cykl zbudowany
# na domyśle. Cykl jednoetapowy ma `NATIVE_ID` i nie jest tym dotknięty.
LINK_BASES_PRIMARY = (LINK_NATIVE_ID, LINK_EXPLICIT_REFERENCE, LINK_VERIFIED_MAPPING)

# NA CZYM STOI OKNO GŁOSOWANIA (plan domknięcia z 11.09, P4; punkt 4 recenzji 78179).
# Współbieżność liczy propozycje otwarte w mierzonej chwili, więc wynik zależy od okien.
# Okno wzięte z rejestru i okno policzone ze ŚREDNIEGO czasu bloku wyglądały w pomiarze
# identycznie, a oba wchodziły do składnika o wadze 0,25.
WINDOW_SNAPSHOT_EXACT = "SNAPSHOT_EXACT"    # `start`/`end` wprost z warstwy Snapshot
WINDOW_REGISTRY_EXACT = "REGISTRY_EXACT"    # okno z rejestru taksonomii DAO
WINDOW_GOVERNOR_EXACT = "GOVERNOR_EXACT"    # historyczny dowód start/end z łańcucha
WINDOW_ESTIMATED = "ESTIMATED"              # odtworzone z czasu bloku i parametru
WINDOW_UNKNOWN = "UNKNOWN"                  # nie wiemy, kiedy było otwarte
WINDOW_BASES = (WINDOW_SNAPSHOT_EXACT, WINDOW_REGISTRY_EXACT, WINDOW_GOVERNOR_EXACT,
                WINDOW_ESTIMATED, WINDOW_UNKNOWN)

# Do pomiaru konfirmacyjnego wchodzą wyłącznie okna z dowodem. `GOVERNOR_EXACT` wymaga
# historycznej wartości parametrów dla WŁAŚCIWEGO wdrożenia kontraktu - średni czas bloku
# i dzisiejszy `votingDelay` się nie kwalifikują, choćby skan zdarzeń się udał.
WINDOW_BASES_PRIMARY = (WINDOW_SNAPSHOT_EXACT, WINDOW_REGISTRY_EXACT, WINDOW_GOVERNOR_EXACT)

# NA CZYM STOI `novelty` (plan domkniecia z 11.09, P6; punkt 6 recenzji 78179).
# Skladnik pyta, na ile ten RODZAJ decyzji jest nowy dla delegata - czyli liczy udzial
# kategorii wsrod jego wczesniejszych decyzji. Przy nieznanej kategorii kod schodzil na
# dopasowanie po slowach kluczowych i zwracal 0,0, czyli "decyzja rutynowa": jedna liczba
# na dwa rozne stany swiata. Pokrycie taksonomia u trojki uczestnikow Fazy A to
# 1,2% / 1,8% / 30,8%, wiec zejscie bylo stanem normalnym, nie wyjatkiem.
NOVELTY_COMPLETE = "COMPLETE"                      # pelny mianownik, wartosc obowiazuje
NOVELTY_NO_PRIOR = "NO_PRIOR_OBSERVED_DECISIONS_IN_COMPLETE_CORPUS"
NOVELTY_TARGET_UNKNOWN = "TARGET_CATEGORY_UNKNOWN"  # nie wiemy, czego dotyczy cel
NOVELTY_HISTORY_INCOMPLETE = "HISTORY_COVERAGE_INCOMPLETE"  # mianownik czesciowy
NOVELTY_KEYWORD_FALLBACK = "KEYWORD_FALLBACK"      # inny konstrukt: cecha tekstu
NOVELTY_BASES = (NOVELTY_COMPLETE, NOVELTY_NO_PRIOR, NOVELTY_TARGET_UNKNOWN,
                 NOVELTY_HISTORY_INCOMPLETE, NOVELTY_KEYWORD_FALLBACK)

# Do pomiaru konfirmacyjnego wchodza dwa stany. NO_PRIOR jest WIEDZA, nie brakiem:
# zero wczesniejszych zaobserwowanych decyzji przy dowiedzionej kompletnosci korpusu
# znaczy, ze kazda kategoria jest dla tego adresu nowa.
NOVELTY_BASES_PRIMARY = (NOVELTY_COMPLETE, NOVELTY_NO_PRIOR)


# TOZSAMOSC ARTEFAKTU WYKONAWCZEGO (plan domkniecia z 11.09, P7; punkt 8 recenzji 78179).
# Sam commit opisuje kod zrodlowy, nie to, co policzylo liczbe: dwa uruchomienia z tego
# samego commitu moga rozniac sie wersja zaleznosci albo polityka kwalifikacji.
#
# Pakiety, ktorych wersja moze zmienic WYNIK, nie tylko wygodę pracy. Lista jest krotka
# swiadomie - slad ma rozrozniac artefakty, a nie zmieniac sie przy kazdej aktualizacji
# narzedzi deweloperskich.
_ZALEZNOSCI_ISTOTNE = ("pyyaml", "httpx", "sqlalchemy", "fastapi", "pydantic")


def _wersje_zaleznosci() -> Dict[str, str]:
    """Wersje pakietow, ktore moga wplynac na wynik, plus wersja Pythona."""
    import platform
    from importlib import metadata

    out: Dict[str, str] = {"python": platform.python_version()}
    for nazwa in _ZALEZNOSCI_ISTOTNE:
        try:
            out[nazwa] = metadata.version(nazwa)
        except Exception:  # noqa: BLE001 - brak pakietu tez jest informacja o artefakcie
            out[nazwa] = "brak"
    return out


@lru_cache(maxsize=1)
def _runtime_digest() -> str:
    """Skrot srodowiska wykonawczego - odpowiednik digestu obrazu, liczony bez Dockera.

    Gdy obraz jest budowany w potoku, jego digest wchodzi przez `PA_BUILD_DIGEST` i staje
    sie czescia skrotu. Bez tej zmiennej slad opiera sie na wersjach zaleznosci i Pythona,
    co wystarcza do odbioru z planu: dwa uruchomienia z tego samego commitu i inna
    zaleznoscia MUSZA byc rozroznialne.
    """
    dane = dict(_wersje_zaleznosci())
    dane["build_image_digest"] = os.environ.get("PA_BUILD_DIGEST", "")
    return "rt:" + _sha(json.dumps(dane, sort_keys=True))[:16]


# EKSPORT MANIFESTOW APPEND-ONLY (plan domkniecia z 11.09, P8, sekcja 9 punkt 4).
#
# Baza pomiarow zyje dzis WEWNATRZ obrazu kontenera (`pa/DEPLOY-prywatny.md`): Dockerfile
# robi `COPY . .`, wiec kazde `docker build` zapieka plik z drzewa roboczego, a zapisy
# runtime gina przy wdrozeniu. Dlatego dwoch pomiarow Fazy B nie da sie odtworzyc.
#
# Eksport wierszowy jest kopia POZA baza i poza obrazem, a zapisany manifest wystarcza do
# odtworzenia pelnego wyniku bez sieci (`replay`). Format wierszowy wybrany swiadomie:
# uszkodzenie ogona pliku - przerwany zapis, pelny dysk - zostawia wczesniejsze wiersze
# czytelnymi, w odroznieniu od jednego duzego dokumentu JSON.
KATALOG_MANIFESTOW = Path(__file__).resolve().parents[2] / "data" / "manifests"


def _plik_manifestow(katalog: Path, znacznik: Optional[str] = None) -> Path:
    """Jeden plik na miesiac - kopia zapasowa nie rosnie w jeden nierozdzielny blok."""
    data = (znacznik or dt.datetime.now(dt.timezone.utc).isoformat())[:7]
    return katalog / f"pomiary-{data}.jsonl"


def dopisz_manifest(manifest: Dict[str, Any], katalog: Optional[Path] = None) -> bool:
    """Dopisuje manifest pomiaru. Zwraca `True`, gdy wiersz doszedl.

    Idempotentny po `measurement_id`: rejestracja jest idempotentna, wiec eksport tez musi
    byc - inaczej liczba wierszy przestalaby cokolwiek znaczyc. Blad zapisu NIE przerywa
    pomiaru: eksport jest zabezpieczeniem, a nie warunkiem policzenia liczby.
    """
    katalog = Path(katalog or KATALOG_MANIFESTOW)
    mid = str(manifest.get("measurement_id") or "")
    if not mid:
        return False
    try:
        katalog.mkdir(parents=True, exist_ok=True)
        plik = _plik_manifestow(katalog, str(manifest.get("computed_at") or ""))
        if plik.exists():
            with plik.open(encoding="utf-8") as f:
                for linia in f:
                    if f'"measurement_id": "{mid}"' in linia or f'"{mid}"' in linia:
                        return False
        with plik.open("a", encoding="utf-8") as f:
            f.write(json.dumps(manifest, sort_keys=True, ensure_ascii=False) + "\n")
        return True
    except OSError as e:  # noqa: BLE001
        print(f"⚠ manifest nie zapisany: {e}")
        return False


def odczytaj_manifesty(katalog: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Wszystkie zapisane manifesty. Uszkodzony wiersz jest POMIJANY, nie wywraca odczytu.

    Jeden zepsuty wiersz to jeden utracony pomiar - nie caly plik i nie cala kopia.
    """
    katalog = Path(katalog or KATALOG_MANIFESTOW)
    out: List[Dict[str, Any]] = []
    if not katalog.exists():
        return out
    for plik in sorted(katalog.glob("pomiary-*.jsonl")):
        try:
            for linia in plik.read_text(encoding="utf-8").splitlines():
                linia = linia.strip()
                if not linia:
                    continue
                try:
                    out.append(json.loads(linia))
                except ValueError:
                    continue
        except OSError:
            continue
    return out


def _wersja_polityki_kwalifikacji(config: Dict[str, Any]) -> str:
    """Wersja polityki kwalifikacji ze SKROTU regul, nie z recznego numeru.

    Polityka jest czescia instrumentu (plan, P9), a recznego numeru nie da sie nie zapomniec
    podbic. Skrot zmienia sie dokladnie wtedy, gdy zmieniaja sie reguly.
    """
    reguly = (config or {}).get("eligibility") or {}
    return "pol:" + _sha(json.dumps(reguly, sort_keys=True, default=str))[:16]


@dataclass
class SourceReceipt:
    """What one source could and could not deliver for THIS measurement."""
    source: str                       # snapshot | tally | governor | ecosystem
    state: str                        # one of SOURCE_STATES
    events: int = 0                   # records delivered
    detail: str = ""                  # human-readable cause (error text, limit)
    unknown_window: int = 0           # records without a usable voting window
    limit: Optional[int] = None       # page/scan limit the query ran with
    oldest_cast_at: Optional[int] = None  # oldest record delivered (epoch) - lets
                                          # eligibility tell whether a TRUNCATED
                                          # history still covers the context window
    # P2 (plan domknięcia, 11.09): dostępność i pokrycie to dwa pytania, nie jedno.
    # Klient może podać je jawnie; gdy ich nie poda, powstają z rzutu `state`, żeby
    # manifesty sprzed 11.09 i niezmigrowani klienci czytali się bez zmiany znaczenia.
    availability_state: str = ""
    coverage_state: str = ""
    # P6 (11.09): rejestr taksonomii ZYJE - kategoria dopisana po pomiarze zmienilaby
    # historyczny wynik przy ponownym liczeniu. Identyfikator zamrozonego snapshotu mowi,
    # JAKI zbior kategorii zbudowal ten pomiar.
    taxonomy_snapshot_id: str = ""
    # Dowód pokrycia, nie jego opis: ile stron przeszło zapytanie, ile rekordów wróciło
    # i czy któraś strona dobiła do limitu. `limit_hit=None` znaczy "nie mierzono" - to
    # inny stan niż `False` i nie wolno go czytać jako dowodu kompletności.
    page_count: Optional[int] = None
    record_count: Optional[int] = None
    limit_hit: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.state not in SOURCE_STATES:
            raise ValueError(f"unknown source state {self.state!r}")
        rzut_avail, rzut_cov = _RZUT_STANU[self.state]
        if not self.availability_state:
            self.availability_state = rzut_avail
        if not self.coverage_state:
            self.coverage_state = rzut_cov
        if self.availability_state not in AVAILABILITY_STATES:
            raise ValueError(f"unknown availability state {self.availability_state!r}")
        if self.coverage_state not in COVERAGE_STATES:
            raise ValueError(f"unknown coverage state {self.coverage_state!r}")
        if self.record_count is None and self.events:
            self.record_count = self.events

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FatigueComponents:
    """Individual component scores, each in [0.0, 1.0]."""
    volume: float        # normalized volume load
    concurrency: float   # normalized concurrency pressure
    burstiness: float    # spike magnitude vs. rolling average
    reading_time: float  # normalized cognitive cost per item
    novelty: float       # ratio of novel vs. routine proposals


@dataclass
class FatigueMetrics:
    """Raw metrics used to derive component scores.
    Included in API response for full auditability."""
    proposals_7d: int          # proposals started in last 7 days
    proposals_30d: int         # proposals started in last 30 days
    concurrent_active: int     # proposals where start <= now <= end
    avg_word_count: float      # mean word count across 30d window
    weekly_avg: float          # proposals_30d / 4.33 (4-week rolling avg)
    novelty_ratio: float       # novel proposals / total in 30d window
    # Separation required by the grant review (point 3, /t/30604 post 18):
    # ecosystem governance load vs the delegate's revealed engagement.
    # concurrency_source names what concurrent_active was counted from -
    # "ecosystem:snapshot" (all proposals open in the space at t, Snapshot
    # layer) or "voted_only" (only proposals this delegate voted on; the
    # pre-2026-08-28 construction, kept as the explicit fallback when the
    # ecosystem source is unavailable). voted_concurrent always carries the
    # revealed-engagement count, whichever source drove the component.
    concurrency_source: str = "voted_only"
    voted_concurrent: int = 0


@dataclass
class MeasurementIdentity:
    """What binds one per-event result to the exact circumstances it was
    computed under (grant review point 4, /t/30604 post 18): the unique
    vote-event - not only the proposal id - plus instrument version, code
    commit, and the source-capability state including unknown windows.

    vote_event_id is a deterministic digest of (address, THIS stage's id, vote
    timestamp). Since the closure review (2026-09-03, point 1) the identity
    names ONE concrete vote - the task the NASA-TLX rating belongs to. Other
    stages of the same decision are linked through lifecycle_id and listed in
    lifecycle_stage_ids; they never enter this vote's identity or its
    computation. Two results with the same id measured the same event; a
    re-run after a source or instrument change keeps the same id and differs
    in instrument_hash/code_commit/receipts - which is the point: the registry
    can tell WHAT changed between two numbers.

    measurement_id is the digest of the COMPLETE identity (vote-event +
    instrument + code + every input set): persistence is idempotent on it
    (closure review point 5)."""
    vote_event_id: str
    stage_ids: List[str]           # THIS vote's stage id (one element)
    voted_at: int                  # vote timestamp bound into the identity
    instrument_version: str        # fatigue_config.yaml version
    code_commit: str               # git HEAD at compute time, or "unknown"
    source_state: Dict[str, Any]   # sources + history_events +
                                   # events_unknown_window + concurrency_source
    # --- complete, reconstructable manifest (closure review point 4) ---
    lifecycle_id: str = ""                       # DecisionLifecycleId
    lifecycle_stage_ids: List[str] = field(default_factory=list)
    source_vote_id: str = ""                     # native id from the source
    source_domain: str = ""                      # snapshot | tally | governor:*
    native_proposal_id: str = ""                 # proposal id as the source knows it
    target_content_hash: str = ""                # sha256 of title + body rated
    context_stage_ids: List[str] = field(default_factory=list)
    context_set_hash: str = ""                   # sha256 over context_stage_ids
    ecosystem_ids: List[str] = field(default_factory=list)
    ecosystem_set_hash: str = ""                 # sha256 over ecosystem_ids
    source_receipts: List[Dict[str, Any]] = field(default_factory=list)
    instrument_hash: str = ""                    # sha256 of fatigue_config.yaml bytes
    eligibility: str = ELIGIBLE                  # PRIMARY_ELIGIBLE | NOT_ELIGIBLE_...
    eligibility_reasons: List[str] = field(default_factory=list)   # disqualifying
    eligibility_notes: List[str] = field(default_factory=list)     # recorded, not disqualifying
    prepared_input: Dict[str, Any] = field(default_factory=dict)
    input_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    canonical_input_digest: str = ""             # sha256 of CanonicalMeasurementInput
    identity_schema_version: str = ""            # rule that produced measurement_id
    # P6 (11.09): na czym stoi `novelty` i ile mianownika znamy. Bez tych pol liczba 0,0
    # opisywala jednocześnie "delegat robi to stale" i "nie wiemy nic o kategoriach".
    # P7 (11.09): tozsamosc ARTEFAKTU, nie tylko kodu zrodlowego.
    eligibility_policy_version: str = ""         # skrot regul kwalifikacji
    runtime_digest: str = ""                     # wersje zaleznosci + digest obrazu
    # Digest obrazu STOI OSOBNO, a nie tylko w skrocie: pusty mowi wprost "policzone poza
    # zbudowanym obrazem" (lokalnie, w testach, z katalogu roboczego). Schowany w skrocie
    # bylby nieodroznialny od obrazu o jakims digescie - a to inny stan wiedzy.
    build_image_digest: str = ""
    novelty_basis: str = ""                      # NOVELTY_* - patrz staly wyzej
    category_coverage: Dict[str, Any] = field(default_factory=dict)
    taxonomy_snapshot_id: str = ""               # zamrozony zbior kategorii tego pomiaru
    measurement_id: str = ""                     # digest of the whole manifest

    def manifest(self) -> Dict[str, Any]:
        """The manifest as persisted: everything needed to reconstruct what
        was measured, without re-running anything."""
        return asdict(self)


@dataclass
class FatigueResult:
    """Full output of fatigue computation.
    All fields needed to reproduce the score are included."""
    address: str
    fatigue_score: float           # final DFI score: 0.0 - 100.0
    status: str                    # LOW | MODERATE | HIGH | CRITICAL
    components: FatigueComponents  # per-component scores (0-1)
    metrics: FatigueMetrics        # raw source metrics
    weights: Dict[str, float]      # weights used (from fatigue_config.yaml)
    config_version: str            # config version for reproducibility
    computed_at: datetime          # UTC timestamp of computation
    mode: str = "ecosystem"        # "ecosystem" (shared burden) | "per_delegate" (revealed activity)
    identity: Optional[MeasurementIdentity] = None  # per-event only (review point 4)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FatigueEngine:
    """
    Deterministic Delegate Fatigue Index computation.

    All parameters are loaded from fatigue_config.yaml.
    Pass `now` explicitly in compute() to enable reproducible testing.
    """

    FORMULA = (
        "DFI = (0.40×volume + 0.25×concurrency + 0.20×burstiness "
        "+ 0.10×reading_time + 0.05×novelty) × 100"
    )

    # Every key the frozen instrument needs. A config missing any of them is
    # INSTRUMENT_INVALID - not "close enough".
    REQUIRED_WEIGHTS = ("volume", "concurrency", "burstiness", "reading_time", "novelty")
    REQUIRED_REFERENCES = ("volume_7d", "volume_30d", "concurrent", "reading_words")
    REQUIRED_THRESHOLDS = ("low", "moderate", "high")

    def __init__(self, config_path: str = "fatigue_config.yaml"):
        self.config_path = Path(config_path)
        self.config, self.instrument_hash = self._load_config()
        self.version = str(self.config["version"])
        self.code_commit = self._read_code_commit()
        logger.info(f"FatigueEngine initialized v{self.version} "
                    f"instrument={self.instrument_hash[:12]}")

    @staticmethod
    def _read_code_commit() -> str:
        """Git HEAD of the running code, for the measurement identity (review
        point 4). Containers built without .git fall back to the GIT_COMMIT
        env var; when neither answers, the honest value is "unknown" - a
        missing capability is reported, never guessed."""
        env = os.environ.get("GIT_COMMIT")
        if env:
            return env.strip()
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:  # noqa: BLE001
            pass
        return "unknown"

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> Tuple[Dict, str]:
        """Load and VALIDATE the instrument. Fails closed (closure review
        point 6): no file, unreadable YAML, missing keys or weights that do not
        sum to 1.0 raise InstrumentInvalid instead of degrading to defaults.

        Returns (config, instrument_hash) - the hash is sha256 of the file's
        bytes, so two measurements made on byte-identical configs share it and
        any edit, including a comment, produces a new one. That is deliberate:
        the manifest must say which file was in force, not which values."""
        if not self.config_path.exists():
            raise InstrumentInvalid(
                f"INSTRUMENT_INVALID: {self.config_path} not found - refusing to "
                "compute DFI on built-in defaults"
            )
        raw = self.config_path.read_bytes()
        try:
            config = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise InstrumentInvalid(f"INSTRUMENT_INVALID: {self.config_path} is not "
                                    f"valid YAML: {e}") from e
        problems = self.validate_config(config)
        if problems:
            raise InstrumentInvalid("INSTRUMENT_INVALID: " + "; ".join(problems))
        return config, hashlib.sha256(raw).hexdigest()

    @classmethod
    def validate_config(cls, config: Any) -> List[str]:
        """Every defect found, as text. Empty list = valid instrument."""
        problems: List[str] = []
        if not isinstance(config, dict):
            return ["config is not a mapping"]
        if not config.get("version"):
            problems.append("missing version")
        weights = config.get("weights")
        if not isinstance(weights, dict):
            problems.append("missing weights")
        else:
            for k in cls.REQUIRED_WEIGHTS:
                if not isinstance(weights.get(k), (int, float)) or isinstance(weights.get(k), bool):
                    problems.append(f"weight {k} missing or not numeric")
            if not problems:
                total = sum(float(weights[k]) for k in cls.REQUIRED_WEIGHTS)
                if abs(total - 1.0) > 0.01:
                    problems.append(f"weights sum to {total:.3f}, expected 1.0")
        for section in ("reference_values", "reference_values_per_event"):
            ref = config.get(section)
            if not isinstance(ref, dict):
                problems.append(f"missing {section}")
                continue
            for k in cls.REQUIRED_REFERENCES:
                v = ref.get(k)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                    problems.append(f"{section}.{k} missing or not a positive number")
        thr = config.get("thresholds")
        if not isinstance(thr, dict):
            problems.append("missing thresholds")
        else:
            for k in cls.REQUIRED_THRESHOLDS:
                if not isinstance(thr.get(k), (int, float)) or isinstance(thr.get(k), bool):
                    problems.append(f"threshold {k} missing or not numeric")
        return problems

    # ------------------------------------------------------------------
    # Main computation
    # ------------------------------------------------------------------

    def compute(
        self,
        address: str,
        proposals: List[Any],
        now: Optional[datetime] = None,
    ) -> FatigueResult:
        """
        Compute the Delegate Fatigue Index.

        Args:
            address:   Delegate wallet address. Currently used as an identifier
                       for future per-delegate personalization. The score itself
                       is ecosystem-level (shared governance burden).
            proposals: List of Proposal ORM instances from the DB.
                       Should cover at least the last 30 days.
            now:       Reference UTC datetime. Defaults to datetime.now(UTC).
                       Pass explicitly in tests for deterministic results.

        Returns:
            FatigueResult with score, status, components, and raw metrics.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        now_ts = int(now.timestamp())
        weights = self.config["weights"]
        ref = self.config["reference_values"]

        metrics = self._compute_metrics(proposals, now_ts)
        components = self._compute_components(metrics, ref)

        fatigue_score = self._aggregate_score(components, weights)
        status = self._determine_status(fatigue_score)

        logger.info(
            f"FatigueEngine[ecosystem]: address={address} score={fatigue_score} "
            f"status={status} proposals_30d={metrics.proposals_30d} "
            f"concurrent={metrics.concurrent_active}"
        )

        return FatigueResult(
            address=address,
            fatigue_score=fatigue_score,
            status=status,
            components=components,
            metrics=metrics,
            weights=weights,
            config_version=self.version,
            computed_at=now,
            mode="ecosystem",
        )

    def compute_per_event(
        self,
        address: str,
        target_proposal: Any,
        voted_history: List[Any],
        now: Optional[datetime] = None,
        ecosystem_proposals: Optional[List[Any]] = None,
        source_counts: Optional[Dict[str, int]] = None,
        source_receipts: Optional[List[SourceReceipt]] = None,
        reconciliations: Optional[List[Dict[str, str]]] = None,
    ) -> FatigueResult:
        """
        Per-event Delegate Fatigue Index (dissertation 5.3.5a; per-event pivot
        2026-05-11).

        The unit of analysis is a SINGLE vote, not a 30-day aggregate. NASA-TLX
        is task-specific and validated only up to ~24h (Hernandez 2021), so the
        survey rates one concrete vote and DFI is matched to it via
        as_of = vote timestamp (`now`). Grounded in Cognitive Load Theory
        (Sweller 1988; Klepsch et al. 2017):

          - reading_time, novelty : INTRINSIC load of THE voted proposal
            (its length and whether it is a novel governance domain). This is
            the main source of between-event variance (proposal length on
            Arbitrum ranges ~150-6000 words).
          - volume, concurrency, burstiness : EXTRANEOUS/context load - how
            much the delegate had on their plate around the vote, computed from
            their voting history in the window ending at `now`.

        Args:
            address:         Delegate wallet address.
            target_proposal: The proposal the vote (and the NASA-TLX rating)
                             refers to. Needs .body / .title.
            voted_history:   Proposals the delegate voted on up to `now`
                             (e.g. from Snapshot `votes`). Drives the context
                             components. Should cover >=30 days before `now`.
            now:             Vote timestamp (as_of). Defaults to now(UTC).
                             Pass explicitly in tests for deterministic results.
            ecosystem_proposals:
                             ALL proposals of the space whose voting window may
                             cover `now` - not just the ones this delegate voted
                             on. When given (an empty list is a real answer:
                             nothing was open), concurrency measures ECOSYSTEM
                             governance load, per point 3 of the grant review
                             (/t/30604 post 18). When None, the source is
                             unavailable and concurrency falls back to the
                             delegate's own voted proposals - the result then
                             says so in metrics.concurrency_source instead of
                             passing the narrower number off as ecosystem load.
            source_receipts: One SourceReceipt per source consulted (closure
                             review point 2). Decides eligibility: a required
                             source outside the eligible states, or the
                             voted_only concurrency fallback, marks the result
                             NOT_ELIGIBLE_FOR_PRIMARY_ANALYSIS. None (offline
                             use, tests) is itself a reason: without receipts
                             nothing proves the inputs were complete.
            reconciliations: What reconcile_observations merged, for the manifest.

        Unit of analysis (closure review point 1): ONE concrete vote. Stages of
        the same decision found in voted_history are counted as one decision in
        the volume/burstiness windows (at the moment of the FIRST stage, where
        the reading happened) but no stage lends anything to another: the
        target's body, category and timestamp are its own.

        Returns:
            FatigueResult with mode="per_event".

        Limitations (dissertation 5.3.5a): vote activity is endogenous (both
        exposure and a possible response to load); off-vote reading and
        forum/Discord load are not captured; Snapshot data is off-chain. See 6.5.
        """
        now_ts = int((now or datetime.now(timezone.utc)).timestamp())
        receipts = [r.to_dict() if isinstance(r, SourceReceipt) else dict(r)
                    for r in (source_receipts or [])]
        wejscie = CanonicalMeasurementInput(
            target_proposal, voted_history, ecosystem_proposals,
            self.instrument_hash, receipts, now_ts=now_ts, address=address,
            config=self.config, code_commit=self.code_commit,
            source_counts=source_counts, reconciliations=reconciliations)
        return self.compute_prepared(wejscie)

    @staticmethod
    def compute_prepared(wejscie: "CanonicalMeasurementInput") -> FatigueResult:
        """Obliczenie bez dostępu do surowych źródeł ani bieżącego YAML."""
        data = wejscie.to_dict()
        worker = object.__new__(FatigueEngine)
        worker.config = data["config"]
        worker.version = str(worker.config["version"])
        worker.instrument_hash = data["instrument_hash"]
        worker.code_commit = data["code_commit"]
        return worker._compute_prepared(wejscie)

    @staticmethod
    def replay(manifest: Dict[str, Any]) -> FatigueResult:
        """Odtwarza pomiar tym samym kodem; nie podszywa się pod starszy silnik."""
        prepared = CanonicalMeasurementInput.from_dict(
            manifest["prepared_input"], manifest["canonical_input_digest"])
        if prepared.to_dict()["code_commit"] != FatigueEngine._read_code_commit():
            raise ValueError("Odtworzenie wymaga wersji kodu zapisanej w pomiarze")
        result = FatigueEngine.compute_prepared(prepared)
        if result.identity.measurement_id != manifest["measurement_id"]:
            raise ValueError("Tożsamość odtworzonego pomiaru jest inna")
        return result

    def _compute_prepared(self, wejscie: "CanonicalMeasurementInput") -> FatigueResult:
        data = wejscie.to_dict()
        target_proposal = SimpleNamespace(**data["target"])
        frozen_history = [SimpleNamespace(**p) for p in data["history"]]
        ecosystem_proposals = ([SimpleNamespace(**p) for p in data["ecosystem"]]
                               if data["ecosystem"] is not None else None)
        now_ts = data["now_ts"]
        now = datetime.fromtimestamp(now_ts, timezone.utc)
        address = data["address"]
        source_receipts = data["receipts"]
        source_counts = data["source_counts"]
        reconciliations = data["reconciliations"]
        weights = self.config["weights"]
        ref = self.config.get(
            "reference_values_per_event", self.config["reference_values"]
        )

        # Freeze the evidence set at the target vote before anything is counted.
        # A proposal may open before the target vote and be voted on days after
        # it; without this filter that later vote would enter the target's
        # history and the historical DFI would depend on information that did
        # not exist at the declared as_of boundary.

        # One decision = one workload event. Stages of a lifecycle collapse to
        # the EARLIEST frozen stage for counting only - a view over immutable
        # observations, not a merged object (closure review point 1).
        decisions = self._decision_representatives(frozen_history)

        # Context components from the delegate's history around the vote.
        ctx = self._compute_metrics(decisions, now_ts, by_vote_time=True, context_only=True)

        # Separation of the two quantities (grant review point 3): what the
        # delegate's own votes show at t is REVEALED ENGAGEMENT and is always
        # kept; ECOSYSTEM LOAD replaces it as the concurrency driver whenever
        # the space-wide proposal list is available. The same unknown-window
        # rule applies: a proposal without `end` is skipped, not counted.
        voted_concurrent = ctx.concurrent_active
        if ecosystem_proposals is not None:
            ctx.concurrent_active = sum(
                1 for p in ecosystem_proposals
                if getattr(p, "end", None) and (p.start or 0) <= now_ts <= p.end
            )
            # Nazwa źródła ma opisywać, SKĄD naprawdę pochodzi ekspozycja (I3, 2026-09-09).
            # Do dziś stała tu na sztywno etykieta `ecosystem:snapshot`, więc po naprawie
            # czytającej obie warstwy wynik nadal twierdziłby, że policzono go z Snapshota.
            # To ta sama klasa błędu, którą naprawiamy: etykieta niezgodna z faktem.
            warstwy = sorted({
                "governor" if str(getattr(p, "source_domain", "") or "").startswith("governor")
                else "snapshot"
                for p in ecosystem_proposals
            })
            concurrency_source = ("ecosystem:" + "+".join(warstwy)) if warstwy else "ecosystem:empty"
        else:
            concurrency_source = "voted_only"

        ctx_components = self._compute_components(ctx, ref)

        # Intrinsic components from THE voted proposal (per-event).
        ref_words = max(ref.get("reading_words", 1500), 1)
        words = len((getattr(target_proposal, "body", None) or "").split())
        reading_time = round(min(min(words / ref_words, 2.0) / 2.0, 1.0), 4)
        novelty_raw, novelty_basis, category_coverage = self._novelty_z_podstawa(
            target_proposal, frozen_history)
        novelty = round(novelty_raw, 4)

        components = FatigueComponents(
            volume=ctx_components.volume,
            concurrency=ctx_components.concurrency,
            burstiness=ctx_components.burstiness,
            reading_time=reading_time,
            novelty=novelty,
        )

        fatigue_score = self._aggregate_score(components, weights)
        status = self._determine_status(fatigue_score)

        # Measurement identity (review point 4): THIS vote-event - its own
        # stage id plus the vote timestamp - bound to the instrument, the code
        # commit and the source-capability receipts. Other stages of the same
        # decision are linked, never bound.
        own_id = _stage_id(target_proposal)
        if not own_id:
            # A source that carries no event id must not collapse two different
            # events into one identity - fall back to the decision key + start,
            # both deterministic properties of the proposal itself.
            own_id = (f"~{_klucz_decyzji(target_proposal)}"
                      f"@{getattr(target_proposal, 'start', 0) or 0}")
        stage_ids = [own_id]
        identity_raw = f"{address.lower()}|{own_id}|{now_ts}"
        vote_event_id = hashlib.sha256(identity_raw.encode()).hexdigest()[:16]

        # Pokwitowania do kwalifikacji biorą się z przygotowanego wejścia - `source_receipts`
        # w tej funkcji to już `data["receipts"]` (linia wyżej w `_compute_prepared`), więc
        # wymaganie P1 "wejście kanoniczne jest jedynym wejściem także dla eligibility" było
        # spełnione przed planem domknięcia. Znika tylko konwersja `SourceReceipt -> dict`:
        # sugerowała, że na tej warstwie mogą pojawić się obiekty z parametru wywołania, choć
        # za granicą wejścia są wyłącznie słowniki. Kontrakt czytelny zamiast domyślanego.
        receipts = list(source_receipts or [])
        cel_domena = str(getattr(target_proposal, "source_domain", "")
                         or getattr(target_proposal, "source", "") or "")
        # Powiązania bez dowodu w tym, co WCHODZI DO LICZENIA: cel i zamrożona historia.
        # Sprawdzane na obserwacjach odtworzonych z przygotowanego wejścia, nie na surowych
        # obiektach - inaczej bramka pytałaby o inny zbiór niż ten, który opisuje pomiar.
        domysly = sorted({
            str(getattr(p, "link_basis", "") or LINK_NATIVE_ID)
            for p in [target_proposal, *frozen_history]
            if str(getattr(p, "link_basis", "") or LINK_NATIVE_ID) not in LINK_BASES_PRIMARY
        })
        # Okna EKSPOZYCJI bez dowodu (P4, sekcja 5.2). Wspolbieznosc liczy propozycje
        # otwarte w mierzonej chwili, wiec kazde okno oszacowane wchodzi do wyniku tak
        # samo jak dowiedzione. Cel i historia nie sa tu sprawdzane: ich okna nie licza
        # sie do wspolbieznosci, a `reading_time` i `novelty` biora sie z tresci.
        taxonomy_snapshot_id = next(
            (str(r.get("taxonomy_snapshot_id") or "") for r in receipts
             if r.get("source") == "taxonomy"), "")
        okna_bez_dowodu = sorted({
            str(getattr(p, "window_basis", "") or WINDOW_UNKNOWN)
            for p in (ecosystem_proposals or [])
            if str(getattr(p, "window_basis", "") or WINDOW_UNKNOWN) not in WINDOW_BASES_PRIMARY
        })
        eligibility, reasons, notes = self._eligibility(
            receipts, concurrency_source, now_ts,
            ekspozycja_pusta=(ecosystem_proposals is not None and not ecosystem_proposals),
            cel_kontraktowy=cel_domena.startswith("governor"),
            podstawy_bez_dowodu=domysly, okna_bez_dowodu=okna_bez_dowodu,
            novelty_basis=novelty_basis, taxonomy_snapshot_id=taxonomy_snapshot_id)

        title = getattr(target_proposal, "title", None) or ""
        body = getattr(target_proposal, "body", None) or ""
        context_ids = sorted(_stage_id(p) or f"~{_klucz_decyzji(p)}@{getattr(p, 'start', 0) or 0}"
                             for p in frozen_history)
        ecosystem_ids = (sorted(str(getattr(p, "id", "") or "") for p in ecosystem_proposals)
                         if ecosystem_proposals is not None else [])
        # Schemat 2 (2026-09-09): tożsamość wiąże WARTOŚCI wejść, nie zbiory identyfikatorów.
        # Schemat 1 hashował `context_set_hash` i `ecosystem_set_hash`, czyli odpowiedź na
        # pytanie „na których rekordach liczono" - a nie „co te rekordy mówiły". Dwa pomiary
        # o tej samej historii i innych kategoriach dostawały jeden identyfikator przy różnym
        # wyniku (kontrprzykład: 44,90 i 46,60 pod `83df5f4f…9bea`).
        manifest_core = {
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "vote_event_id": vote_event_id,
            "instrument_hash": self.instrument_hash,
            "instrument_version": self.version,
            "code_commit": self.code_commit,
            # Skróty zbiorów zostają w manifeście jako czytelny opis zakresu - do tożsamości
            # nie wchodzą już samodzielnie, bo robi to projekcja kanoniczna.
            "target_content_hash": _sha(_serialized({"title": title, "body": body})),
            "context_set_hash": _sha("|".join(context_ids)),
            "ecosystem_set_hash": (_sha("|".join(ecosystem_ids))
                                   if ecosystem_proposals is not None else ""),
            "canonical_input_digest": wejscie.digest(),
            "eligibility": eligibility,
        }
        identity = MeasurementIdentity(
            vote_event_id=vote_event_id,
            stage_ids=stage_ids,
            voted_at=now_ts,
            instrument_version=self.version,
            code_commit=self.code_commit,
            source_state={
                "sources": source_counts or {},
                "history_events": len(frozen_history),
                "history_decisions": len(decisions),
                "events_unknown_window": sum(
                    1 for p in frozen_history if not getattr(p, "end", None)),
                "concurrency_source": concurrency_source,
                # Ujawnione zaangażowanie delegata NALEŻY do pomiaru, więc stoi
                # w manifeście obok źródła współbieżności. Do 10.09 go tu nie było,
                # a odpowiedź budowana z zapisanego wiersza brała je z zapasowej
                # ścieżki na świeże obliczenie - czyli wiersz oddawał liczbę policzoną
                # przed chwilą, nie tę, którą zarejestrowano (recenzja Codeksa,
                # `main.py:768`).
                "voted_concurrent": voted_concurrent,
                "reconciliations": list(reconciliations or []),
            },
            lifecycle_id=str(getattr(target_proposal, "lifecycle_id", "") or ""),
            lifecycle_stage_ids=[str(s) for s in
                                 (getattr(target_proposal, "lifecycle_stage_ids", None) or stage_ids)],
            source_vote_id=str(getattr(target_proposal, "source_vote_id", "") or ""),
            source_domain=str(getattr(target_proposal, "source_domain", "")
                              or getattr(target_proposal, "source", "") or ""),
            native_proposal_id=str(getattr(target_proposal, "native_proposal_id", "") or ""),
            target_content_hash=manifest_core["target_content_hash"],
            context_stage_ids=context_ids,
            context_set_hash=manifest_core["context_set_hash"],
            ecosystem_ids=ecosystem_ids,
            ecosystem_set_hash=manifest_core["ecosystem_set_hash"],
            source_receipts=receipts,
            instrument_hash=self.instrument_hash,
            eligibility=eligibility,
            eligibility_reasons=reasons,
            eligibility_notes=notes,
            prepared_input=wejscie.to_dict(),
            input_conflicts=_input_conflicts(data["history"]),
            canonical_input_digest=manifest_core["canonical_input_digest"],
            identity_schema_version=IDENTITY_SCHEMA_VERSION,
            novelty_basis=novelty_basis,
            category_coverage=category_coverage,
            taxonomy_snapshot_id=taxonomy_snapshot_id,
            eligibility_policy_version=_wersja_polityki_kwalifikacji(self.config),
            runtime_digest=_runtime_digest(),
            build_image_digest=os.environ.get("PA_BUILD_DIGEST", ""),
            measurement_id=_sha(json.dumps(manifest_core, sort_keys=True))[:32],
        )

        # Metrics reflect the per-event view: context counts + THIS proposal's length.
        metrics = FatigueMetrics(
            proposals_7d=ctx.proposals_7d,
            proposals_30d=ctx.proposals_30d,
            concurrent_active=ctx.concurrent_active,
            avg_word_count=float(words),
            weekly_avg=ctx.weekly_avg,
            novelty_ratio=novelty,
            concurrency_source=concurrency_source,
            voted_concurrent=voted_concurrent,
        )

        logger.info(
            f"FatigueEngine[per_event]: address={address} score={fatigue_score} "
            f"status={status} words={words} ctx_voted_30d={ctx.proposals_30d} "
            f"concurrent={ctx.concurrent_active}"
        )

        return FatigueResult(
            address=address,
            fatigue_score=fatigue_score,
            status=status,
            components=components,
            metrics=metrics,
            weights=weights,
            config_version=self.version,
            computed_at=now,
            mode="per_event",
            identity=identity,
        )

    @staticmethod
    def _decision_representatives(history: List[Any]) -> List[Any]:
        """One observation per decision lifecycle: the earliest frozen stage.
        Observations without a lifecycle are their own decision."""
        pierwsze: Dict[str, Any] = {}
        for p in history:
            k = _lifecycle_key(p)
            if k not in pierwsze or _observation_order(p) < _observation_order(pierwsze[k]):
                pierwsze[k] = p
        return list(pierwsze.values())

    def _eligibility(self, receipts: List[Dict[str, Any]], concurrency_source: str,
                     now_ts: int, ekspozycja_pusta: bool = False,
                     cel_kontraktowy: bool = False,
                     podstawy_bez_dowodu: Optional[List[str]] = None,
                     okna_bez_dowodu: Optional[List[str]] = None,
                     novelty_basis: str = "",
                     taxonomy_snapshot_id: str = "",
                     ) -> Tuple[str, List[str], List[str]]:
        """Fail closed (closure review points 2 and 6, plan domknięcia P2):
        pomiar konfirmacyjny jest `PRIMARY_ELIGIBLE` tylko wtedy, gdy każde wymagane
        źródło ODPOWIEDZIAŁO i DOWIODŁO pokrycia obszaru wymaganego przez konstrukt,
        a współbieżność policzono na konstrukcie, który instrument deklaruje. Reguły
        stoją w `fatigue_config.yaml#eligibility`; ta metoda je tylko stosuje.

        DWA WYMIARY, NIE JEDEN (zmiana z 11.09). Dotąd jeden `state` odpowiadał na oba
        pytania naraz, więc `PARTIAL` kwalifikował się jako „źródło odpowiedziało",
        choć znaczy „część rekordów nie ma pola, którego instrument potrzebuje",
        a `TRUNCATED` przechodził, gdy najstarszy DOSTARCZONY rekord był starszy niż
        okno kontekstu. To drugie było rozumowaniem wewnątrz jednego źródła, nie
        dowodem pokrycia: wiek najstarszego rekordu nie mówi nic o rekordach, które
        limit strony uciął. Dowodem jest `coverage_state`, a ten ma się brać z liczby
        stron i z tego, czy którakolwiek dobiła do limitu.

        Wiek najstarszego rekordu zostaje w NOTATCE, bo jest użyteczną informacją
        o zakresie - przestaje być podstawą werdyktu.

        Returns (verdict, disqualifying reasons, non-disqualifying notes)."""
        rules = self.config.get("eligibility") or {}
        required = list(rules.get("required_sources") or [])
        ok_avail = set(rules.get("eligible_availability") or [AVAIL_HEALTHY])
        ok_coverage = set(rules.get("eligible_coverage") or [COV_COMPLETE, COV_EMPTY_PROVEN])
        window = int(rules.get("context_window_days") or 30) * 86_400
        reasons: List[str] = []
        notes: List[str] = []
        if not receipts:
            reasons.append("no source receipts supplied - completeness of inputs unproven")
        by_source = {r.get("source"): r for r in receipts}
        for name in required:
            r = by_source.get(name)
            if r is None:
                reasons.append(f"required source {name}: no receipt")
                continue
            # Pokwitowania zapisane przed 11.09 nie mają wymiarów - rzutujemy je tak samo,
            # jak robi to `SourceReceipt.__post_init__`, żeby stary manifest dał ten sam
            # werdykt, jaki dałby dziś świeży pomiar o tym samym stanie źródeł.
            rzut = _RZUT_STANU.get(r.get("state") or "", (AVAIL_UNAVAILABLE, COV_NONE))
            avail = r.get("availability_state") or rzut[0]
            coverage = r.get("coverage_state") or rzut[1]
            if avail not in ok_avail:
                reasons.append(f"required source {name}: availability {avail}"
                               + (f" ({r.get('detail')})" if r.get("detail") else ""))
                continue
            if coverage not in ok_coverage:
                powod = f"required source {name}: coverage {coverage} - completeness not proven"
                if r.get("limit_hit"):
                    powod += f" (page limit {r.get('limit')} reached)"
                if r.get("detail"):
                    powod += f" ({r['detail']})"
                reasons.append(powod)
                continue
            if r.get("oldest_cast_at") is not None \
                    and int(r["oldest_cast_at"]) <= now_ts - window:
                notes.append(f"{name}: delivered records reach beyond the "
                             f"{window // 86_400}-day context window "
                             f"({r.get('record_count') or r.get('events')} records)")
            if r.get("coverage_state") == COV_PARTIAL_DATA and r.get("detail"):
                notes.append(f"{name}: {r['detail']}")
        # P3: powiązanie etapów bez dowodu nie może wpłynąć na liczbę wchodzącą do
        # analizy konfirmacyjnej. `volume` i `burstiness` liczą się po cyklach, więc
        # cykl zbudowany na zbieżności nazwy jest domysłem w mianowniku obciążenia.
        for okno in (okna_bez_dowodu or []):
            reasons.append(
                f"exposure window basis {okno} - concurrency counts proposals open at the "
                "measured moment, and this one's window is reconstructed, not evidenced")
        # P6: `novelty` policzona na czesciowym mianowniku albo bez znanej kategorii celu
        # nie jest pomiarem pierwszorzednym. Iloraz z jednego procenta sklasyfikowanych
        # decyzji opisuje ten procent i milczy o pozostalych dziewiecdziesieciu dziewieciu.
        if novelty_basis and novelty_basis not in NOVELTY_BASES_PRIMARY:
            reasons.append(
                f"novelty basis {novelty_basis} - the component's denominator is partial "
                "or the target category is unknown, so the value is not a primary measure")
        # P7: brak tozsamosci kodu to brak dowodu, nie pominieta metadana. Wynik traktowany
        # jako odtwarzalny musi wiedziec, JAKI artefakt go policzyl - inaczej dwa builda
        # staja sie nieodroznialne na warstwie tozsamosci.
        if str(getattr(self, "code_commit", "") or "") in ("", "unknown"):
            reasons.append(
                "code identity missing (code_commit unknown) - the measurement cannot say "
                "which build produced it, so it is not reproducible evidence")
        # Rejestr taksonomii ZYJE: bez identyfikatora zamrozonego snapshotu nie da sie
        # powiedziec, jaki zbior kategorii zbudowal ten pomiar, ani powtorzyc go pozniej.
        if "taxonomy" in required and not taxonomy_snapshot_id:
            reasons.append(
                "taxonomy snapshot id missing - the category set behind this measurement "
                "is not frozen, so a later registry change would silently alter it")
        for podstawa in (podstawy_bez_dowodu or []):
            reasons.append(
                f"stage linking basis {podstawa} - one decision was assembled without "
                "evidence beyond a normalized title match, and volume/burstiness count "
                "by decision")
        # Rodzina `ecosystem:*` - konkretne warstwy nazywa sama etykieta (snapshot,
        # governor, snapshot+governor, empty). Porównanie z jedną nazwą odrzucałoby po
        # naprawie każdą ekspozycję czytaną z obu warstw.
        #
        # `ecosystem:empty` PRZECHODZI świadomie: pusta lista jest pomiarem („nic nie było
        # otwarte"), a nie awarią - rozróżnienie `None` od `[]` stoi w silniku od 28.08 i ma
        # własny test. Niebezpieczny przypadek pustki - cel z kontraktu przy zerowej
        # ekspozycji - łapie osobny warunek niżej, bo dopiero tam widać, że pustka może
        # znaczyć „pytaliśmy nie tę warstwę".
        if not concurrency_source.startswith("ecosystem:"):
            reasons.append(f"concurrency measured as {concurrency_source}, not ecosystem "
                           "exposure - a different construct than the frozen instrument")
        # I3 (2026-09-09): źródło odpowiedziało - ale czy miało czego szukać?
        #
        # Warunek wyżej pyta, KTÓRĄ DROGĄ policzono składnik. Nie pyta, czy ta droga sięga
        # warstwy, w której oceniane zdarzenie powstało. Do 09.09 ekspozycja czytała sam
        # Snapshot, więc każdy głos kontraktowy po 27.08 - dnia zamknięcia ostatniej
        # propozycji Snapshot - dostawał `concurrency` = 0 przy pokwitowaniu HEALTHY_EMPTY
        # i werdykcie PRIMARY_ELIGIBLE. „Nic nie było otwarte" było nieodróżnialne od
        # „pytaliśmy nie tę warstwę" (ANALIZA-2026-09-09, sekcja 8b).
        #
        # Źródło jest naprawione - ekspozycja czyta obie warstwy - ale bezpiecznik zostaje:
        # przy pustej ekspozycji i celu z kontraktu zero nie przechodzi jako pomiar.
        if ekspozycja_pusta and cel_kontraktowy:
            reasons.append(
                "ecosystem exposure empty while the rated vote comes from the contract "
                "layer - zero here cannot be told apart from asking the wrong layer")
        return (ELIGIBLE if not reasons else NOT_ELIGIBLE), reasons, notes

    def _novelty_per_event(self, target: Any, history: List[Any]) -> float:
        """Na ile ten RODZAJ decyzji jest nowy DLA TEGO delegata.

        Do 2026-08-05 składnik pytał o właściwość samej propozycji: czy w tytule
        albo treści stoi słowo z naszej listy „nowych domen". Wychodziło 0,0
        u wszystkich trzech uczestników Phase A, więc składnik nie różnicował
        nikogo - a przy wadze 5% nikt tego nie zauważył.

        Dwa powody zmiany. Po pierwsze, teoria: obciążenie poznawcze przy nowości
        jest z definicji względne wobec doświadczenia osoby (CLT, Sweller 1988) -
        propozycja o awarii jest nowa dla kogoś, kto pierwszy raz się z tym mierzy,
        i rutynowa dla kogoś, kto przerabiał to pięć razy. Lista słów mierzyła
        cechę tekstu, nie stan czytającego.

        Po drugie, dane: DAO utrzymuje własną taksonomię propozycji (12 kategorii,
        `arbdata`), wskazaną przez uczestnika badania jako źródło używane przez
        społeczność. Klasyfikacja, którą prowadzi teren, broni się lepiej niż
        słowa, które sami wybraliśmy - i sami przyznaliśmy, że nie działają.

        Wynik: udział głosów TEGO delegata w TEJ kategorii wśród jego głosów
        wcześniejszych, odjęty od jedynki. Pierwsze zetknięcie z kategorią daje
        1,0, kategoria stanowiąca całość jego dorobku daje 0,0.

        Bez znanej kategorii wracamy do dopasowania po słowach. Zamiana braku
        klasyfikacji na zero byłaby twierdzeniem, że decyzja jest rutynowa - a to
        inna rzecz niż „nie wiemy".
        """
        wartosc, _podstawa, _pokrycie = self._novelty_z_podstawa(target, history)
        return wartosc

    def _novelty_z_podstawa(self, target: Any, history: List[Any]):
        """Wartość `novelty` RAZEM z podstawą i pokryciem mianownika (P6, 11.09).

        Zwraca `(wartosc, podstawa, pokrycie)`. Do 11.09 ta funkcja zwracała samą liczbę,
        więc stan "nie wiemy" wychodził jako 0,0 - nieodróżnialne od "delegat robi to stale".
        Pokrycie liczy się na TYM SAMYM korpusie, z którego bierze się mianownik: własny
        cykl celu jest wyłączony, bo endpoint podaje cel wewnątrz jego własnej historii.
        """
        kat = (getattr(target, "category", None) or "").strip().lower()
        wlasny = _lifecycle_key(target)

        # Kategorie cykli historii. Jedna decyzja = jedno wcześniejsze zetknięcie, a kategoria
        # cyklu to pierwsza znana wśród jego ZAMROŻONYCH etapów (wszystkie <= now, więc to
        # informacja, która w chwili głosu istniała).
        kategorie_cykli: Dict[str, str] = {}
        identyfikatory: Dict[str, str] = {}
        for p in sorted(history, key=_observation_order):
            k = _lifecycle_key(p)
            if k == wlasny:
                # Own lifecycle excluded (closure review 2026-09-03): do 2026-09-04
                # PIERWSZY głos delegata w kategorii dawał 1 - 1/1 = 0,0, czyli "rutynowa".
                continue
            c = (getattr(p, "category", None) or "").strip().lower()
            if c and not kategorie_cykli.get(k):
                kategorie_cykli[k] = c
            else:
                kategorie_cykli.setdefault(k, "")
            identyfikatory.setdefault(k, str(getattr(p, "id", "") or k))

        wczesniej = [c for c in kategorie_cykli.values() if c]
        brakujace = [identyfikatory[k] for k, c in kategorie_cykli.items() if not c]
        pokrycie = {
            "classified_count": len(wczesniej),
            "eligible_history_count": len(kategorie_cykli),
            "coverage_ratio": (len(wczesniej) / len(kategorie_cykli)
                               if kategorie_cykli else 1.0),
            "coverage_basis": ("prior decision lifecycles in the measured history, "
                              "own lifecycle excluded"),
            "missing_ids": sorted(brakujace)[:50],
            "missing_count": len(brakujace),
        }

        if not kat:
            # Kategoria celu nieznana. Słowa kluczowe policzone DO WGLĄDU - to inny konstrukt
            # (cecha tekstu, nie stan czytającego), więc nie wolno go promować jako `novelty`.
            return self._proposal_is_novel(target), NOVELTY_TARGET_UNKNOWN, pokrycie

        if not kategorie_cykli:
            # Brak wcześniejszych ZAOBSERWOWANYCH decyzji. To wiedza, nie brak: każda
            # kategoria jest dla tego adresu nowa. Nazwa stanu nie mówi "pierwszy głos
            # człowieka" - osoba może mieć historię pod innym adresem albo w innym DAO.
            return 1.0, NOVELTY_NO_PRIOR, pokrycie

        if brakujace:
            # Iloraz z podzbioru NIE jest estymatą punktową (plan, 7.4). Wartość wraca
            # do wglądu, ale podstawa mówi, że mianownik jest częściowy.
            w_tej = sum(1 for c in wczesniej if c == kat)
            czesciowa = (1.0 - min(w_tej / len(wczesniej), 1.0)) if wczesniej else 1.0
            return czesciowa, NOVELTY_HISTORY_INCOMPLETE, pokrycie

        w_tej = sum(1 for c in wczesniej if c == kat)
        return 1.0 - min(w_tej / len(wczesniej), 1.0), NOVELTY_COMPLETE, pokrycie

    def _proposal_is_novel(self, proposal: Any) -> float:
        """
        Zapas, gdy kategoria nieznana: 1.0 gdy tytuł albo treść zawiera słowo
        z listy nowych domen i żadnego z listy rutynowych, inaczej 0.0.
        Ta sama logika co w wariancie ekosystemowym, zastosowana do jednej pozycji.
        """
        novel_kw = [k.lower() for k in self.config.get("novel_keywords", [])]
        routine_kw = [k.lower() for k in self.config.get("routine_keywords", [])]
        text = (
            (getattr(proposal, "title", None) or "")
            + " "
            + (getattr(proposal, "body", None) or "")
        ).lower()
        has_novel = any(kw in text for kw in novel_kw)
        has_routine = any(kw in text for kw in routine_kw)
        return 1.0 if (has_novel and not has_routine) else 0.0

    @staticmethod
    def _aggregate_score(
        components: "FatigueComponents", weights: Dict[str, float]
    ) -> float:
        """Weighted aggregate of component scores -> DFI in [0, 100].
        Shared by compute() and compute_per_event() so the formula
        lives in exactly one place."""
        raw = (
            weights["volume"]        * components.volume
            + weights["concurrency"]  * components.concurrency
            + weights["burstiness"]   * components.burstiness
            + weights["reading_time"] * components.reading_time
            + weights["novelty"]      * components.novelty
        )
        return round(min(raw * 100, 100.0), 1)

    # ------------------------------------------------------------------
    # Metrics computation
    # ------------------------------------------------------------------

    @staticmethod
    def _vote_ts(item: Any) -> int:
        """When the delegate acted on this item. Falls back to the proposal's
        start for sources that carry no vote timestamp (the ecosystem variant
        counts proposals, not votes)."""
        return int(getattr(item, "voted_at", None) or getattr(item, "start", None) or 0)

    def _compute_metrics(
        self, proposals: List[Any], now_ts: int, by_vote_time: bool = False,
        context_only: bool = False
    ) -> FatigueMetrics:
        """
        Volume windows measure votes per week/month when `by_vote_time` is set
        (per-event variant): the window anchors on when the delegate voted, not
        on when the proposal opened. A proposal that opened 40 days out but was
        voted on yesterday is yesterday's workload.

        Concurrency stays on proposal start/end in both variants - it asks how
        many decisions stood open around the delegate at `now_ts`, which is a
        proposal-time concept and not a substitute for the vote timestamp.
        """
        cutoff_7d  = now_ts - (7  * 86_400)
        cutoff_30d = now_ts - (30 * 86_400)

        def window_ts(p: Any) -> int:
            return self._vote_ts(p) if by_vote_time else (p.start or 0)

        # Upper bound (<= now_ts) lets caller pass `now` in the past
        # to compute DFI retrospectively (see endpoint `as_of` parameter).
        proposals_7d  = sum(1 for p in proposals if cutoff_7d  <= window_ts(p) <= now_ts)
        proposals_30d = sum(1 for p in proposals if cutoff_30d <= window_ts(p) <= now_ts)

        # Concurrent: proposals where start <= now <= end.
        #
        # A proposal whose voting window is unknown is SKIPPED, deliberately.
        # Sources differ in what they can supply (Tally omits the end timestamp;
        # the on-chain client cannot reconstruct it when ProposalCreated falls
        # outside its scan window), and an absent window must not be read as
        # "did not overlap". Until 2026-08-05 this happened by accident - the
        # `or 0` turned a missing end into the epoch, so the comparison was
        # false and every on-chain vote scored zero concurrency in silence.
        concurrent_active = sum(
            1 for p in proposals
            if getattr(p, "end", None) and (p.start or 0) <= now_ts <= p.end
        )

        # Average word count across 30d window
        recent = [p for p in proposals if cutoff_30d <= window_ts(p) <= now_ts]
        if recent and not context_only:
            word_counts = [len((p.body or "").split()) for p in recent]
            avg_word_count = sum(word_counts) / len(word_counts)
        else:
            avg_word_count = 0.0

        # 4-week rolling average (proposals_30d / 4.33 weeks)
        weekly_avg = proposals_30d / 4.33

        novelty_ratio = 0.0 if context_only else self._compute_novelty_ratio(recent)

        return FatigueMetrics(
            proposals_7d=proposals_7d,
            proposals_30d=proposals_30d,
            concurrent_active=concurrent_active,
            avg_word_count=round(avg_word_count, 1),
            weekly_avg=round(weekly_avg, 2),
            novelty_ratio=round(novelty_ratio, 3),
        )

    def _compute_novelty_ratio(self, proposals: List[Any]) -> float:
        """
        Proportion of recent proposals classified as novel (not routine).

        Novel = contains at least one novel keyword AND no routine keywords.
        This proxies the extra cognitive cost of processing genuinely new
        governance domains vs. familiar, repeating patterns.
        """
        if not proposals:
            return 0.0

        novel_kw   = [k.lower() for k in self.config.get("novel_keywords", [])]
        routine_kw = [k.lower() for k in self.config.get("routine_keywords", [])]

        novel_count = 0
        for p in proposals:
            text = ((p.title or "") + " " + (p.body or "")).lower()
            has_novel   = any(kw in text for kw in novel_kw)
            has_routine = any(kw in text for kw in routine_kw)
            if has_novel and not has_routine:
                novel_count += 1

        return novel_count / len(proposals)

    # ------------------------------------------------------------------
    # Component score normalization
    # ------------------------------------------------------------------

    def _compute_components(
        self, metrics: FatigueMetrics, ref: Dict
    ) -> FatigueComponents:
        """
        Normalize raw metrics into [0.0, 1.0] component scores.

        Each component is designed to return 0.5 at the reference value
        and approach 1.0 at 2× the reference (capped there).
        """
        ref_7d         = max(ref.get("volume_7d", 5), 1)
        ref_30d        = max(ref.get("volume_30d", 20), 1)
        ref_concurrent = max(ref.get("concurrent", 5), 1)
        ref_words      = max(ref.get("reading_words", 3000), 1)

        # Volume: weighted average of normalized 7d and 30d rates
        # Recent week weighted 60%, monthly context 40%
        v7  = min(metrics.proposals_7d  / ref_7d,  2.0) / 2.0
        v30 = min(metrics.proposals_30d / ref_30d, 2.0) / 2.0
        volume = 0.6 * v7 + 0.4 * v30

        # Concurrency: normalize against reference concurrent count
        concurrency = min(metrics.concurrent_active / ref_concurrent, 2.0) / 2.0

        # Burstiness: how much this week exceeds the rolling weekly average
        # Score = 0 when at or below average, 1 when 3× the average (2 std above)
        if metrics.weekly_avg > 0:
            burst_ratio = metrics.proposals_7d / metrics.weekly_avg
        else:
            burst_ratio = 1.0 if metrics.proposals_7d > 0 else 0.0
        burstiness = min(max(burst_ratio - 1.0, 0.0) / 2.0, 1.0)

        # Reading time: normalize average word count
        reading_time = min(metrics.avg_word_count / ref_words, 2.0) / 2.0

        # Novelty: directly a ratio in [0, 1]
        novelty = metrics.novelty_ratio

        return FatigueComponents(
            volume=round(min(volume, 1.0), 4),
            concurrency=round(min(concurrency, 1.0), 4),
            burstiness=round(min(burstiness, 1.0), 4),
            reading_time=round(min(reading_time, 1.0), 4),
            novelty=round(novelty, 4),
        )

    # ------------------------------------------------------------------
    # Status mapping
    # ------------------------------------------------------------------

    def _determine_status(self, score: float) -> str:
        t = self.config.get("thresholds", {})
        if score < t.get("low", 30):
            return "LOW"
        elif score < t.get("moderate", 70):
            return "MODERATE"
        elif score < t.get("high", 85):
            return "HIGH"
        return "CRITICAL"

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_config_info(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "formula": self.FORMULA,
            "weights": self.config["weights"],
            "reference_values": self.config["reference_values"],
            "thresholds": self.config["thresholds"],
        }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


IDENTITY_SCHEMA_VERSION = "3"
"""Wersja reguły, według której powstaje `measurement_id`.

`1` (do 2026-09-09): manifest wiązał ZBIORY IDENTYFIKATORÓW - `context_set_hash`,
`ecosystem_set_hash` - więc dwa pomiary o tych samych rekordach i różnych WARTOŚCIACH tych
rekordów dostawały jeden identyfikator. Udowodnione kontrprzykładem: DFI 44,90 i 46,60 pod
`83df5f4f2301ef52b6b98551f1ae9bea`, przy zmienionej wyłącznie kategorii wpisów historii.

`2` (od 2026-09-09): identyfikator hashuje projekcję wartości.
`3` (od 2026-09-10): składniki czytają to samo zapisane wejście co tożsamość;
osobne title/body, jedna reguła czasu, deterministyczne remisy i odtworzenie offline.

Bez tego pola stare i nowe identyfikatory dałoby się rozróżnić tylko przez wnioskowanie
z commita - a rejestr będzie zawierał jedne i drugie obok siebie.
"""


def _wejscie_kanoniczne(p: Any) -> Dict[str, Any]:
    """Kopia wartości obserwacji; bez referencji do obiektu źródłowego."""
    title = getattr(p, "title", None) or ""
    body = getattr(p, "body", None) or ""
    start = int(getattr(p, "start", 0) or 0)
    end = int(getattr(p, "end", 0) or 0)
    own_id = _stage_id(p) or "~" + _sha(json.dumps(
        [title, body, start, end], ensure_ascii=False))
    return {
        "id": own_id,
        "lifecycle_id": str(getattr(p, "lifecycle_id", None) or own_id),
        "voted_at": FatigueEngine._vote_ts(p),
        "start": start, "end": end,
        "category": (getattr(p, "category", None) or "").strip().lower(),
        "title": title, "body": body,
        "source_domain": str(getattr(p, "source_domain", None)
                             or getattr(p, "source", None) or ""),
        "source_vote_id": str(getattr(p, "source_vote_id", None) or ""),
        "native_proposal_id": str(getattr(p, "native_proposal_id", None) or ""),
        "lifecycle_stage_ids": sorted(str(x) for x in
            (getattr(p, "lifecycle_stage_ids", None) or [own_id])),
        # P3 (11.09): podstawa powiązania rozstrzyga o werdykcie, więc musi przejść
        # granicę wejścia - kwalifikacja liczy się z przygotowanego wejścia (P1).
        # Obserwacja, która nie przeszła przez `merge_stages` (testy, korpus), jest
        # własną decyzją, czyli ma podstawę natywną.
        # P4 (11.09): podstawa okna rozstrzyga o werdykcie, wiec musi przejsc granice
        # wejscia. Obserwacja bez podstawy pochodzi z warstwy, ktora jej nie podala -
        # to stan NIEZNANY, nie domyslnie dobry.
        "window_basis": str(getattr(p, "window_basis", None) or ""),
        "window_uncertainty_reason": str(getattr(p, "window_uncertainty_reason", None) or ""),
        "link_basis": str(getattr(p, "link_basis", None) or LINK_NATIVE_ID),
        "linked_stage_ids": sorted(str(x) for x in
            (getattr(p, "linked_stage_ids", None)
             or getattr(p, "lifecycle_stage_ids", None) or [own_id])),
    }


def _observation_order(p):
    return (FatigueEngine._vote_ts(p), _stage_id(p),
            _serialized(_wejscie_kanoniczne(p)))


def _input_conflicts(history):
    cycles = {}
    ids = {}
    for p in history:
        cycles.setdefault(p["lifecycle_id"], []).append(p)
        ids.setdefault(p["id"], []).append(p)
    result = []
    for lifecycle, stages in sorted(cycles.items()):
        known = sorted((p for p in stages if p["category"]),
                       key=lambda p: (p["voted_at"], p["id"], _serialized(p)))
        if len({p["category"] for p in known}) > 1:
            result.append({"kind": "category", "lifecycle_id": lifecycle,
                           "selected_stage_id": known[0]["id"],
                           "selected_category": known[0]["category"],
                           "stages": known})
    for stage_id, stages in sorted(ids.items()):
        if len({_serialized(p) for p in stages}) > 1:
            result.append({"kind": "duplicate_id", "stage_id": stage_id,
                           "stages": sorted(stages, key=_serialized)})
    return result


def _serialized(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


class CanonicalMeasurementInput:
    """Samowystarczalny zapis wejścia. Odczyt zawsze zwraca niezależną kopię.

    Po przygotowaniu składniki nie mogą sięgać do obserwacji źródłowych.
    Czas i okna normalizujemy do całkowitych sekund dokładnie jeden raz.
    """
    __slots__ = ("_json",)

    def __init__(self, target, history, ecosystem, instrument_hash, receipts,
                 *, now_ts=None, address="", config=None, code_commit="unknown",
                 source_counts=None, reconciliations=None):
        target = _wejscie_kanoniczne(target)
        now_ts = target["voted_at"] if now_ts is None else int(now_ts)
        history = [_wejscie_kanoniczne(p) for p in history]
        self._json = _serialized({
            "schema": IDENTITY_SCHEMA_VERSION,
            "target": target,
            "history": sorted((p for p in history if p["voted_at"] <= now_ts),
                              key=lambda p: (p["id"], _serialized(p))),
            "ecosystem": (sorted((_wejscie_kanoniczne(p) for p in ecosystem),
                                 key=lambda p: (p["id"], _serialized(p)))
                          if ecosystem is not None else None),
            "now_ts": now_ts, "address": address.lower(),
            "instrument_hash": instrument_hash, "config": config,
            "code_commit": code_commit,
            "receipts": sorted(receipts, key=_serialized),
            "source_counts": source_counts or {},
            "reconciliations": sorted(reconciliations or [], key=_serialized),
        })

    @classmethod
    def from_dict(cls, data, expected_digest=None):
        if data.get("schema") != IDENTITY_SCHEMA_VERSION:
            raise ValueError("Nieobsługiwana wersja przygotowanego wejścia")
        problems = FatigueEngine.validate_config(data.get("config"))
        if problems:
            raise InstrumentInvalid("; ".join(problems))
        instance = object.__new__(cls)
        instance._json = _serialized(data)
        if expected_digest is not None and instance.digest() != expected_digest:
            raise ValueError("Zapisane wejście nie zgadza się ze skrótem")
        return instance

    def to_dict(self):
        return json.loads(self._json)

    def kanonicznie(self):
        return self._json

    def digest(self):
        return _sha(self._json)


def _klucz_decyzji(p: Any) -> str:
    r"""Tytuł sprowadzony do postaci porównywalnej między źródłami.

    Snapshot i kontrakt zapisują ten sam tytuł inaczej: nawiasy kwadratowe,
    przedrostek `Constitutional AIP:`, wielkość liter, znaki ucieczki w opisie
    ze zdarzenia (`[Constitutional\] AIP:`). Porównanie znak w znak dałoby zero
    trafień i cichy brak scalania - czyli stan sprzed poprawki, tylko z kodem,
    który wygląda, jakby coś robił.
    """
    t = (getattr(p, "title", None) or "").lower()
    t = re.sub(r"\\", "", t)
    t = re.sub(r"[\[\]()]", " ", t)
    t = re.sub(r"\b(constitutional|non-constitutional|aip|proposal)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _czas_glosu(p: Any) -> float:
    """Moment głosu w sekundach. Gdy brak `voted_at` - start propozycji."""
    v = getattr(p, "voted_at", None) or getattr(p, "start", None) or 0
    return v if isinstance(v, (int, float)) else 0


def _lifecycle_key(p: Any) -> str:
    """Klucz GRUPOWANIA obserwacji w jedną decyzję - do zliczania obciążenia.

    To nie jest tożsamość cyklu zapisywana w manifeście. Od 11.09 (P3) te dwie
    rzeczy są rozdzielone: `lifecycle_id` bez dowodu powiązania jest tożsamością
    natywną etapu, bo kanoniczny identyfikator oparty na zbieżności nazwy zmieniałby
    się wraz z zakresem skanu. Zliczanie ma jednak dalej traktować jedną decyzję jako
    jedno zdarzenie, więc grupuje po ZAPISANYM ZWIĄZKU (`linked_stage_ids`), a nie po
    tożsamości - najmniejszy identyfikator związku jest stabilny wobec kolejności,
    w jakiej odpowiedziały źródła.

    Obserwacja spoza `merge_stages` (testy, korpus) jest własną decyzją. Zapasowe
    `id(p)` zostało usunięte: adres obiektu w pamięci nie jest stabilny między
    uruchomieniami, więc wynik mógł zależeć od tego, jak Python rozmieścił obiekty.
    Bez identyfikatora i bez związku klucz powstaje z wartości obserwacji.
    """
    zwiazek = [str(x) for x in (getattr(p, "linked_stage_ids", None) or []) if str(x)]
    # Związek rozstrzyga tylko wtedy, gdy faktycznie wiąże WIĘCEJ niż jedną obserwację.
    # Jednoelementowy związek to zapis „nic tu nie scalono" i nie może przesłonić
    # przynależności podanej wprost (`lifecycle_id`) - tak robią testy i korpus, które
    # nie przechodzą przez `merge_stages`. Pierwsza wersja tej funkcji tego nie
    # rozróżniała i rozbijała cykle podane w danych wejściowych: `novelty` spadało
    # z 1,0 na 0,5, bo jedna wcześniejsza decyzja liczyła się jako dwie.
    if len(zwiazek) > 1:
        return min(zwiazek)
    wlasne = str(getattr(p, "lifecycle_id", None) or getattr(p, "id", "") or "")
    if wlasne:
        return wlasne
    return "~" + _sha(json.dumps([
        getattr(p, "title", None) or "", getattr(p, "body", None) or "",
        int(getattr(p, "start", 0) or 0), int(getattr(p, "end", 0) or 0),
    ], ensure_ascii=False))


def _stage_id(p: Any) -> str:
    return str(getattr(p, "id", "") or "")


def reconcile_observations(votes: List[Any]) -> Tuple[List[Any], List[Dict[str, str]]]:
    """Scala WYŁĄCZNIE rekordy dowiedzione jako ta sama obserwacja: ten sam
    głosujący, to samo źródło, ta sama propozycja w tym źródle (closure review
    2026-09-03, punkt 3). Klienci źródeł do 2026-09-04 robili to same, po cichu,
    ZANIM powstał identyfikator zdarzenia - i identyfikator nazywał się
    „unikalny" dla obiektu, który już wchłonął inne rekordy.

    Zostaje rekord o NAJPÓŹNIEJSZYM `cast_at` (ponowne głosowanie zastępuje
    poprzednie - tak też zachowywały się klienci, które brały pierwszy rekord
    z listy sortowanej od najnowszego). Wchłonięte identyfikatory nie giną:
    trafiają do `superseded_source_vote_ids` obserwacji i do zwracanej listy
    uzgodnień, z której manifest je zapisze.

    Rekordy bez natywnego identyfikatora propozycji nie są uzgadniane z niczym.
    """
    grupy: Dict[Tuple[str, str, str], List[Any]] = {}
    luzem: List[Any] = []
    for v in votes:
        klucz = (str(getattr(v, "voter", "") or "").lower(),
                 str(getattr(v, "source_domain", "") or getattr(v, "source", "") or ""),
                 str(getattr(v, "native_proposal_id", "") or ""))
        if not klucz[2]:
            luzem.append(v)
            continue
        grupy.setdefault(klucz, []).append(v)
    wynik: List[Any] = list(luzem)
    uzgodnienia: List[Dict[str, str]] = []
    for czlonkowie in grupy.values():
        czlonkowie.sort(key=lambda x: (int(getattr(x, "cast_at", None) or _czas_glosu(x) or 0),
                                       str(getattr(x, "source_vote_id", "") or "")))
        zwyciezca = czlonkowie[-1]
        zwyciezca.superseded_source_vote_ids = [
            str(getattr(x, "source_vote_id", "") or _stage_id(x)) for x in czlonkowie[:-1]]
        for x in czlonkowie[:-1]:
            uzgodnienia.append({
                "kept": str(getattr(zwyciezca, "source_vote_id", "") or _stage_id(zwyciezca)),
                "superseded": str(getattr(x, "source_vote_id", "") or _stage_id(x)),
                "reason": "same voter, source and native proposal id",
            })
        wynik.append(zwyciezca)
    return wynik, uzgodnienia


def scal_ekspozycje(snap, gov):
    """Ekspozycja ekosystemu z dwóch warstw, jedna decyzja liczona RAZ (I3, 2026-09-09).

    Prosta suma byłaby błędem odwrotnym do dzisiejszego: ta sama decyzja bywa etapem na
    Snapshocie i później na kontrakcie, więc podwójne zliczenie zawyżałoby współbieżność
    dokładnie tam, gdzie dziś ją zeruje. Klucz scalania to `_klucz_decyzji` z silnika -
    tytuł sprowadzony do postaci porównywalnej między źródłami, ten sam, którym silnik
    łączy etapy w cykl od 04.09.

    `None` z obu źródeł zostaje `None`: brak odpowiedzi nie jest pustym ekosystemem, a
    `compute_per_event` odróżnia te przypadki (`None` schodzi na `voted_only` i dyskwalifikuje,
    pusta lista znaczy „nic nie było otwarte").
    """
    # Awaria KTÓREJKOLWIEK warstwy znaczy, że pełnej ekspozycji nie znamy - a nie, że
    # znamy ją w części. Zwrócenie tego, co odpowiedziało, podałoby stan zdegradowany jako
    # pomiar ekosystemu: dokładnie to, przed czym ostrzega recenzja („a degraded state must
    # never cross as a valid, qualified result"). `None` schodzi na `voted_only`, co silnik
    # dyskwalifikuje, a pokwitowania obu warstw zostają w manifeście, więc widać, która padła.
    if snap is None or gov is None:
        return None

    # Scalamy WYŁĄCZNIE MIĘDZY warstwami (09.09, druga runda I3). Wcześniej jeden słownik
    # obejmował obie listy naraz, więc dwie RÓŻNE propozycje kontraktowe, których tytuły
    # schodzą się po normalizacji, zlewały się w jedną i zaniżały współczynnik. W obrębie
    # jednej warstwy powtórzony tytuł to zawsze dwa obciążenia - governance nie wystawia
    # jednej propozycji dwa razy w tym samym miejscu, a jeżeli nazywa dwie sprawy tak samo,
    # delegat i tak czyta obie.
    #
    # Klucz jest MOCNIEJSZY niż `_klucz_decyzji` o jedną rzecz: znika z niego odstęp. Snapshot
    # i kontrakt zapisują ten sam tytuł raz jako „ArbOS 61", raz jako „ArbOS61", i sam
    # `_klucz_decyzji` zostawiał je jako dwie decyzje - czyli ZAWYŻAŁ ekspozycję dokładnie tam,
    # gdzie naprawa miała ją urealnić. Mocniejsza normalizacja jest tu bezpieczna właśnie
    # dlatego, że działa wyłącznie na parach z dwóch różnych warstw.
    def _klucz_ekspozycji(p):
        return re.sub(r"\s+", "", _klucz_decyzji(p) or "")

    klucze_gov = {_klucz_ekspozycji(p) for p in gov} - {""}
    # Przy tej samej decyzji zostaje etap kontraktowy: od czerwca 2026 to on jest wiążący,
    # więc jego okno opisuje realny czas trwania obciążenia.
    return [p for p in snap if _klucz_ekspozycji(p) not in klucze_gov] + list(gov)


def merge_stages(votes: List[Any], okno_dni: int = 45) -> List[Any]:
    """Wiąże etapy JEDNEJ decyzji w cykl (lifecycle), NIE mutując żadnego etapu.

    Arbitrum prowadzi propozycję przez sondę nastrojów na Snapshocie, a potem
    przez wiążący głos na kontrakcie. Do 2026-08-05 liczyliśmy to jako dwa
    zdarzenia, z komentarzem w kodzie, że tak ma być, bo „obciążenie nie zależy
    od tego, w którym systemie oddano głos". Dwaj uczestnicy obalili tę przesłankę
    niezależnie i z nazwanym mechanizmem: P03 - „the workload is 1 time.
    Arbitrum works with temperature check and then the real vote"; P01 - drugie
    przejście to „quick review to make sure the text hasn't changed".

    DO 2026-09-04 ta funkcja SCALAŁA etapy w jeden obiekt: zostawał etap
    o najwcześniejszym głosie, dostawał najdłuższą treść i kategorię z etapu,
    który ją znał. Closure review (/t/30604, 2026-09-03, punkt 1) pokazał,
    że to przeciek w przyszłość drugą drogą: obiekt o `voted_at` = t1 niósł
    treść i klasyfikację z etapu o t2 > t1, a `compute_per_event(as_of=t1)`
    liczył reading_time i novelty z informacji, która w t1 nie istniała.
    Do tego jednostka analizy przestawała być jednym głosem - a NASA-TLX
    ocenia jedno konkretne zadanie.

    OD 2026-09-04: każdy etap zostaje osobną, ZAMROŻONĄ obserwacją
    (`TaskObservation` w języku recenzji) z własnym `id`, `voted_at`, `body`
    i `category`. Przynależność do cyklu zapisują pola:
      - `lifecycle_id`      - DecisionLifecycleId (skrót klucza decyzji i
                              momentu pierwszego etapu),
      - `lifecycle_stage_ids` - identyfikatory wszystkich etapów cyklu,
      - `stage_index`       - pozycja etapu w cyklu (1 = pierwsze czytanie),
      - `stages`            - liczba etapów (zgodność z dotychczasowym API).
    Zliczanie obciążenia po cyklach (jedna decyzja = jedno zdarzenie w oknie
    volume/burstiness) robi `compute_per_event`, na zamrożonych obserwacjach.

    OKNO CZASOWE (od 2026-08-06). Sam tytuł nie wystarczy do orzeczenia, że dwa
    głosy są etapami tej samej decyzji. Governance powtarza procesy cyklicznie
    pod niezmienioną nazwą - „Security Council Election Process Improvements"
    wraca co roku. Bez ograniczenia czasowego wybory z 2025 i z 2026 lądowały
    w jednym zdarzeniu, a ono dziedziczyło znacznik starszego etapu. Zmierzone
    na dwóch uczestnikach Phase A: głos P02 z 2026-07-30 wchłonięty przez głos
    z 2025-09-10 (odstęp 323 dni), głos P01 z 2026-08-03 przez 2025-09-08
    (329 dni). W obu wypadkach zniknął NAJNOWSZY głos uczestnika, więc endpoint
    bez `proposal_id` wskazywał zdarzenie sprzed tygodnia, a zapytanie o właściwy
    identyfikator on-chain zwracało 404.

    Próg wzięty z rozkładu odstępów, nie z wyczucia. U obu uczestników odstępy
    układają się w skupisko do 33 dni (najdłuższy wiarygodny: 32,2), a następna
    wartość to dopiero 65,7 dnia. 45 dni leży w tej przerwie: mieści pełną drogę
    sonda-głos wiążący razem z zapasem i odcina powtórzenia cyklu.

    Ograniczeniem jest to, że odstępy 65-112 dni też przestają się scalać.
    Nie wiem, czy któreś z nich było prawdziwym dwuetapowym przejściem - przy
    takim odstępie „szybkie sprawdzenie, czy tekst się nie zmienił" przestaje
    być wiarygodnym opisem pracy delegata.
    """
    okno = okno_dni * 86_400
    # kubełek: klucz decyzji -> lista cykli; cykl = lista etapów rosnąco po czasie
    kubelki: Dict[str, List[List[Any]]] = {}
    # Sortowanie po momencie głosu, a przy remisie po identyfikatorze. Bez tego
    # wynik zależałby od kolejności, w jakiej odpowiedziały trzy źródła - a
    # niezmiennik z 05.08 mówi: ten sam cel i te same dowody dają ten sam pomiar.
    for p in sorted(votes, key=lambda x: (_czas_glosu(x), _stage_id(x))):
        k = _klucz_decyzji(p)
        if not k:
            k = f"__bez_tytulu__{id(p)}"
        czas = _czas_glosu(p)
        cykl = None
        # Od najnowszego cyklu w tej rodzinie - etap dokleja się do cyklu,
        # który trwa, nie do zamkniętego sprzed roku. Odstęp liczy się od
        # OSTATNIEGO etapu cyklu, jak przed zmianą (kubełek trzymał najnowszy
        # obiekt rodziny, a ten miał czas najwcześniejszego etapu - stąd
        # porównanie z pierwszym etapem, zachowane tu co do wartości).
        for kandydat in reversed(kubelki.setdefault(k, [])):
            pierwszy = _czas_glosu(kandydat[0])
            if czas and pierwszy and (czas - pierwszy) <= okno:
                cykl = kandydat
                break
        if cykl is None:
            kubelki[k].append([p])
        else:
            cykl.append(p)

    wynik: List[Any] = []
    for rodzina in kubelki.values():
        for cykl in rodzina:
            ids = [_stage_id(s) for s in cykl]
            pierwszy = cykl[0]
            podstawa, dowod = _podstawa_powiazania(cykl)

            # TOŻSAMOŚĆ CYKLU NIE MOŻE ZALEŻEĆ OD ZAKRESU SKANU (P3, plan z 11.09).
            # Do 11.09 `lifecycle_id` liczył się z klucza decyzji, czasu PIERWSZEGO
            # etapu i jego identyfikatora - więc skan, który nie objął starszego etapu,
            # oddawał tę samą decyzję pod innym identyfikatorem. `measurement_id`
            # dziedziczy po tej wartości, czyli dwa pomiary tej samej rzeczy nie dawały
            # się porównać.
            #
            # Teraz identyfikator powstaje z DOWODU, nie z tego, co akurat widzieliśmy:
            #  - jeden etap: tożsamość natywna tej obserwacji;
            #  - powiązanie z dowodem: skrót zbioru identyfikatorów, których dowód
            #    dotyczy (zbiór jest wtedy własnością decyzji, nie okna);
            #  - powiązanie po tytule: WŁASNA tożsamość każdego etapu plus jawny zapis
            #    niepewnego związku. Plan, sekcja 4: "jeżeli nie istnieje stabilna
            #    tożsamość cyklu oparta na dowodzie źródłowym, używamy tożsamości
            #    obserwacji natywnych i przechowujemy związek jako niepewny, zamiast
            #    tworzyć zmienny kanoniczny identyfikator".
            if podstawa in (LINK_EXPLICIT_REFERENCE, LINK_VERIFIED_MAPPING):
                surowe = "|".join(sorted(ids))
                lifecycle_id = "lc:" + hashlib.sha256(surowe.encode()).hexdigest()[:16]
            else:
                lifecycle_id = None     # ustawiany per etap niżej

            for i, s in enumerate(cykl, start=1):
                # Etap NIE dostaje niczego od innych etapów - ani treści, ani
                # kategorii, ani czasu. Tylko przynależność i jej podstawę.
                #
                # ROZDZIAŁ TOŻSAMOŚCI OD ZLICZANIA (P3). Bez dowodu `lifecycle_id`
                # jest tożsamością natywną tego etapu, bo kanoniczny identyfikator
                # cyklu zbudowany na zbieżności nazwy byłby zmienny: zależałby od tego,
                # które etapy objął skan. Związek NIE ginie - stoi w `linked_stage_ids`
                # i to po nim grupuje zliczanie obciążenia (`_lifecycle_key`), więc
                # jedna decyzja nadal jest jednym zdarzeniem w oknie volume.
                # Werdykt osobno mówi, że taki pomiar nie wchodzi do analizy głównej.
                s.lifecycle_id = lifecycle_id or _stage_id(s)
                s.lifecycle_stage_ids = list(ids)
                s.linked_stage_ids = list(ids)
                s.link_basis = podstawa
                s.link_evidence = dowod
                s.stage_index = i
                s.stages = len(cykl)
                s.lifecycle_started_at = int(_czas_glosu(pierwszy))
                s.stage_ids = [_stage_id(s)]
                wynik.append(s)
    return wynik


def _podstawa_powiazania(cykl: List[Any]) -> Tuple[str, str]:
    """Na czym stoi powiązanie etapów w jedną decyzję i jaki jest dowód.

    Jeden etap to jedna obserwacja - podstawa natywna, bez powiązania. Dla dwóch
    i więcej szukamy dowodu MOCNIEJSZEGO niż zbieżność nazwy: czy któryś etap cytuje
    w treści natywny identyfikator innego. Wiążąca propozycja w Arbitrum zwykle podaje
    identyfikator swojej sondy nastrojów, więc dowód bywa dostępny - tam, gdzie go nie
    ma, powiązanie zostaje domysłem i pomiar to mówi.
    """
    if len(cykl) < 2:
        return LINK_NATIVE_ID, f"single observation {_stage_id(cykl[0])}"

    identyfikatory = {}
    for s in cykl:
        for pole in ("native_proposal_id", "id"):
            wartosc = str(getattr(s, pole, "") or "")
            if len(wartosc) >= 6:
                identyfikatory[wartosc] = _stage_id(s)

    for s in cykl:
        tresc = ((getattr(s, "body", None) or "") + " "
                 + (getattr(s, "title", None) or "")).lower()
        for wartosc, wlasciciel in identyfikatory.items():
            if wlasciciel == _stage_id(s):
                continue            # cytat z siebie nie jest dowodem powiązania
            if wartosc.lower() in tresc:
                return (LINK_EXPLICIT_REFERENCE,
                        f"stage {_stage_id(s)} cites {wartosc} of stage {wlasciciel}")

    return (LINK_TITLE_HEURISTIC,
            f"normalized title match only: {_klucz_decyzji(cykl[0])!r}")
