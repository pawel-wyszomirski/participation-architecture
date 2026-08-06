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

import re
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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

    def __init__(self, config_path: str = "fatigue_config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.version = self.config.get("version", "unknown")
        logger.info(f"FatigueEngine initialized v{self.version}")

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self) -> Dict:
        if not self.config_path.exists():
            logger.warning(
                f"fatigue_config.yaml not found at {self.config_path}, using defaults"
            )
            return self._default_config()
        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)
        self._validate_weights(config.get("weights", {}))
        return config

    def _default_config(self) -> Dict:
        return {
            "version": "1.0.0",
            "weights": {
                "volume": 0.40,
                "concurrency": 0.25,
                "burstiness": 0.20,
                "reading_time": 0.10,
                "novelty": 0.05,
            },
            "reference_values": {
                "volume_7d": 5,
                "volume_30d": 20,
                "concurrent": 5,
                "reading_words": 3000,
            },
            "thresholds": {"low": 30, "moderate": 70, "high": 85},
            "novel_keywords": [
                "exploit", "hack", "drain", "vulnerability", "hard fork",
                "upgrade", "emergency", "pause", "security council",
                "new program", "pilot", "constitution", "amendment",
            ],
            "routine_keywords": [
                "report", "transparency", "renewal", "housekeeping",
                "maintenance", "salary", "stipend", "compensation",
                "monthly", "quarterly", "routine", "operational",
            ],
        }

    def _validate_weights(self, weights: Dict) -> None:
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(
                f"Fatigue weights sum to {total:.3f}, expected 1.0. "
                "Scores may be outside 0-100 range."
            )

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

        Returns:
            FatigueResult with mode="per_event".

        Limitations (dissertation 5.3.5a): vote activity is endogenous (both
        exposure and a possible response to load); off-vote reading and
        forum/Discord load are not captured; Snapshot data is off-chain. See 6.5.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        now_ts = int(now.timestamp())
        weights = self.config["weights"]
        ref = self.config.get(
            "reference_values_per_event", self.config["reference_values"]
        )

        # Freeze the evidence set at the target vote before anything is counted.
        # A proposal may open before the target vote and be voted on days after
        # it; without this filter that later vote would enter the target's
        # history and the historical DFI would depend on information that did
        # not exist at the declared as_of boundary.
        frozen_history = [p for p in voted_history if self._vote_ts(p) <= now_ts]

        # Context components from the delegate's history around the vote.
        ctx = self._compute_metrics(frozen_history, now_ts, by_vote_time=True)
        ctx_components = self._compute_components(ctx, ref)

        # Intrinsic components from THE voted proposal (per-event).
        ref_words = max(ref.get("reading_words", 1500), 1)
        words = len((getattr(target_proposal, "body", None) or "").split())
        reading_time = round(min(min(words / ref_words, 2.0) / 2.0, 1.0), 4)
        novelty = round(self._novelty_per_event(target_proposal, frozen_history), 4)

        components = FatigueComponents(
            volume=ctx_components.volume,
            concurrency=ctx_components.concurrency,
            burstiness=ctx_components.burstiness,
            reading_time=reading_time,
            novelty=novelty,
        )

        fatigue_score = self._aggregate_score(components, weights)
        status = self._determine_status(fatigue_score)

        # Metrics reflect the per-event view: context counts + THIS proposal's length.
        metrics = FatigueMetrics(
            proposals_7d=ctx.proposals_7d,
            proposals_30d=ctx.proposals_30d,
            concurrent_active=ctx.concurrent_active,
            avg_word_count=float(words),
            weekly_avg=ctx.weekly_avg,
            novelty_ratio=novelty,
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
        )

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
        kat = (getattr(target, "category", None) or "").strip().lower()
        if kat:
            wczesniej = [p for p in history
                         if (getattr(p, "category", None) or "").strip().lower()]
            if wczesniej:
                w_tej = sum(1 for p in wczesniej
                            if (p.category or "").strip().lower() == kat)
                return 1.0 - min(w_tej / len(wczesniej), 1.0)
            return 1.0  # brak historii z kategoriami = wszystko jest nowe
        return self._proposal_is_novel(target)

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
        self, proposals: List[Any], now_ts: int, by_vote_time: bool = False
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
        if recent:
            word_counts = [len((p.body or "").split()) for p in recent]
            avg_word_count = sum(word_counts) / len(word_counts)
        else:
            avg_word_count = 0.0

        # 4-week rolling average (proposals_30d / 4.33 weeks)
        weekly_avg = proposals_30d / 4.33

        novelty_ratio = self._compute_novelty_ratio(recent)

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


def merge_stages(votes: List[Any], okno_dni: int = 45) -> List[Any]:
    """Scala etapy JEDNEJ decyzji w jedno zdarzenie obciążenia.

    Arbitrum prowadzi propozycję przez sondę nastrojów na Snapshocie, a potem
    przez wiążący głos na kontrakcie. Do 2026-08-05 liczyliśmy to jako dwa
    zdarzenia, z komentarzem w kodzie, że tak ma być, bo „obciążenie nie zależy
    od tego, w którym systemie oddano głos". Dwaj uczestnicy obalili tę przesłankę
    niezależnie i z nazwanym mechanizmem: P03 - „the workload is 1 time.
    Arbitrum works with temperature check and then the real vote"; P01 - drugie
    przejście to „quick review to make sure the text hasn't changed".

    Zostaje zdarzenie o NAJWCZEŚNIEJSZYM głosie, bo tam odbyło się czytanie,
    a późniejsze przejście jest sprawdzeniem. Treść bierzemy najdłuższą
    z dostępnych - kontrakt niesie pełny opis, Snapshot bywa skrócony, a
    `reading_time` ma opisywać to, co delegat naprawdę przeczytał.

    Liczba etapów ląduje w `stages`. Informacja, że decyzja miała dwa przejścia,
    jest wynikiem badawczym, nie śmieciem do wyrzucenia.

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
    kubelki: Dict[str, List[Any]] = {}
    # Sortowanie po momencie głosu, a przy remisie po identyfikatorze. Bez tego
    # wynik zależałby od kolejności, w jakiej odpowiedziały trzy źródła - a
    # niezmiennik z 05.08 mówi: ten sam cel i te same dowody dają ten sam pomiar.
    for p in sorted(votes, key=lambda x: (_czas_glosu(x), str(getattr(x, "id", "") or ""))):
        k = _klucz_decyzji(p)
        if not k:
            k = f"__bez_tytulu__{id(p)}"
        czas = _czas_glosu(p)
        obecny = None
        # Od najnowszego zdarzenia w tej rodzinie - etap dokleja się do cyklu,
        # który trwa, nie do zamkniętego sprzed roku.
        for kandydat in reversed(kubelki.setdefault(k, [])):
            odstep = czas - _czas_glosu(kandydat)
            if czas and _czas_glosu(kandydat) and odstep <= okno:
                obecny = kandydat
                break
        if obecny is None:
            p.stages = 1
            kubelki[k].append(p)
            continue
        obecny.stages = getattr(obecny, "stages", 1) + 1
        # dłuższa treść wygrywa - pełny opis nad skróconym
        if len(getattr(p, "body", "") or "") > len(getattr(obecny, "body", "") or ""):
            obecny.body = p.body
        # Kategoria przechodzi z tego etapu, który ją zna. Bez tego scalanie gubiło
        # klasyfikację: rejestr DAO kluczuje po identyfikatorze on-chain, więc
        # kategorię niesie wyłącznie zdarzenie z kontraktu, a scalenie zostawiało
        # wcześniejszy obiekt ze Snapshota. Po pierwszym przebiegu kategorię miała
        # jedna propozycja na 209 i składnik `novelty` wyszedł zerem u wszystkich.
        if getattr(p, "category", None) and not getattr(obecny, "category", None):
            obecny.category = p.category
        # Wcześniejszy głos wyznacza moment zdarzenia. Po sortowaniu wejścia
        # kubełek trzyma już najwcześniejszy etap, więc warunek jest bezpiecznikiem
        # na wypadek zmiany kolejności, nie ścieżką roboczą.
        if (getattr(p, "voted_at", 0) or 0) < (getattr(obecny, "voted_at", 0) or 0):
            obecny.voted_at = p.voted_at
            obecny.start = getattr(p, "start", obecny.start)
            if getattr(p, "end", None):
                obecny.end = p.end
    return [p for rodzina in kubelki.values() for p in rodzina]
