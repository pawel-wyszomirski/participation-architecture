"""
Rule Engine for Participation Architecture
Implements deterministic triage logic based on rulebook.yaml

Design Principles:
- Deterministic: Same input always produces same output
- Auditable: Every score includes rule IDs that fired
- Testable: Pure functions with no side effects
- Versioned: Rulebook changes tracked via SemVer
"""

import yaml
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ProposalInput:
    """Normalized proposal schema (Section 2 of rulebook.md)"""
    # Core fields
    item_id: str
    title: str
    body: str
    author: str = "unknown"
    created_at: int = field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp()))
    start_at: Optional[int] = None
    end_at: Optional[int] = None
    status: str = "active"  # draft|active|closed|executed|canceled|unknown
    
    # Optional governance metadata
    venue: str = "snapshot"
    chain: str = "arbitrum-one"
    item_type: str = "proposal"
    proposal_kind: Optional[str] = None  # constitutional|treasury|election|technical|ops|meta|unknown
    requested_amount_usd: Optional[float] = None
    #: Waluta wniosku, gdy kwota jest, ale nieprzeliczalna na dolary (np. ARB).
    #: Pozwala regule powiedziec "progu nie da sie ocenic" zamiast milczec.
    requested_currency: Optional[str] = None
    requested_amount_arb: Optional[float] = None
    execution_type: Optional[str] = None
    affects_protocol_parameters: Optional[bool] = None
    affects_security: Optional[bool] = None
    affects_treasury: Optional[bool] = None
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    
    # Text-derived fields (computed during ingestion)
    word_count: int = 0
    keyword_hits: Dict[str, int] = field(default_factory=dict)

    def get(self, key: str, default=None):
        """Helper to access fields dynamically with alias support"""
        # Alias 'state' to 'status' to match rulebook terminology where 'state' is used
        if key == 'state':
            return self.status
        return getattr(self, key, default)


@dataclass
class TriageResult:
    """Output of rule evaluation (Section 3 of rulebook.md)"""
    item_id: str
    labels: List[str]
    priority_score: int  # 0-100
    recommended_handling: str
    reasons: List[str]  # Rule IDs that fired
    
    # Debug/explain information
    explain: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationState:
    """Internal state during rule evaluation"""
    proposal: ProposalInput
    labels: Set[str] = field(default_factory=set)
    flags: Set[str] = field(default_factory=set)  # NEW: Context flags (e.g., STATE_CLOSED)
    priority_score: int = 0
    min_priority: int = 0
    max_priority: int = 100
    reasons: List[str] = field(default_factory=list)
    priority_adjustments: List[Dict[str, Any]] = field(default_factory=list)
    manual_handling_override: Optional[str] = None


# ============================================================================
# RULE ENGINE
# ============================================================================

class RuleEngine:
    """
    Deterministic rule evaluation engine.
    
    Evaluation order:
    1. Load rules and regex patterns.
    2. Sort rules by PRIORITY (Phase 0 -> Phase 5).
    3. Execute sequentially to allow flags to be set in early phases.
    4. Apply tiers (Time, Treasury, Workload).
    5. Clamp and Map scores.
    """
    
    def __init__(self, rulebook_path: str = "rulebook.yaml"):
        """Load and parse rulebook"""
        self.rulebook_path = Path(rulebook_path)
        self.rulebook = self._load_rulebook()
        self.version = self.rulebook.get("version", "unknown")
        
        # Pre-compile regexes for performance
        self.keyword_patterns = self._compile_keyword_groups()
        
        logger.info(f"RuleEngine initialized with rulebook v{self.version}")
    
    def _load_rulebook(self) -> Dict:
        """Load YAML rulebook"""
        if not self.rulebook_path.exists():
            # Fallback check mainly for test environments if needed, but per request strictly checking for file
            logger.error(f"Rulebook not found: {self.rulebook_path}")
            # Return empty structure to prevent immediate crash init, but eval will fail
            return {"rules": [], "keyword_groups": {}, "score_mapping": {}}
        
        with open(self.rulebook_path, 'r') as f:
            rulebook = yaml.safe_load(f)
        
        return rulebook

    def _compile_keyword_groups(self) -> Dict[str, re.Pattern]:
        """Compile regex patterns for all keyword groups"""
        patterns = {}
        groups = self.rulebook.get("keyword_groups", {})
        for group_name, keywords in groups.items():
            # Escape keywords and join with OR (|)
            # Use \b for word boundaries to avoid partial matches
            pattern_str = "|".join([re.escape(k) for k in keywords])
            patterns[group_name] = re.compile(f"(?i)\\b({pattern_str})\\b")
        return patterns
    
    def evaluate_proposal(self, proposal: ProposalInput) -> TriageResult:
        """
        Main entry point: evaluate a proposal against all rules.
        """
        logger.debug(f"Evaluating proposal {proposal.item_id}: {proposal.title[:50]}")
        
        # Initialize state
        state = EvaluationState(proposal=proposal)
        
        # Compute derived data if missing
        if proposal.word_count == 0 and proposal.body:
             proposal.word_count = len(proposal.body.split())
        
        # Compute keyword hits if not already done
        if not proposal.keyword_hits:
            proposal.keyword_hits = self._compute_keyword_hits(proposal)
        
        # --- EXECUTION PIPELINE ---
        
        # In Rulebook v2.5, execution is strictly Priority-based.
        # Higher priority rules (Context, Security) must run before standard rules.
        rules = self.rulebook.get("rules", [])
        
        # Sort by priority descending (10000 -> 1)
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)
        
        for rule in sorted_rules:
            # Check conditions
            if self._evaluate_condition(rule.get("when", {}), state):
                # Apply actions
                state = self._apply_actions(rule, state)
        
        # --- FINALIZATION ---

        # Clamp score to valid range
        final_score = self._clamp_score(
            state.priority_score, 
            state.min_priority, 
            state.max_priority
        )
        
        # Map to recommended handling
        handling = self._determine_handling(final_score, state)
        
        # Build result
        result = TriageResult(
            item_id=proposal.item_id,
            labels=sorted(list(state.labels)),
            priority_score=final_score,
            recommended_handling=handling,
            reasons=state.reasons,
            explain={
                "min_priority": state.min_priority,
                "max_priority": state.max_priority,
                "priority_adjustments": state.priority_adjustments,
                "rulebook_version": self.version,
                "flags_set": list(state.flags)
            }
        )
        
        logger.info(
            f"Proposal {proposal.item_id}: "
            f"score={final_score}, handling={handling}, "
            f"labels={len(result.labels)}, rules_fired={len(result.reasons)}"
        )
        
        return result
    
    # -------------------------------------------------------------------------
    # CONDITION EVALUATION
    # -------------------------------------------------------------------------

    def _evaluate_condition(self, condition: Dict, state: EvaluationState) -> bool:
        """
        Recursively evaluate a condition block against the state.
        Dispatches to specific helper methods for each condition type.
        """
        # --- Logic Operators ---
        if "any" in condition:
            return any(self._evaluate_condition(c, state) for c in condition["any"])
        
        if "all" in condition:
            return all(self._evaluate_condition(c, state) for c in condition["all"])
        
        if condition.get("always") is True:
            return True
        
        # --- Keyword & Text Matchers ---
        if "keyword_group_hits" in condition:
            return self._check_keyword_group_hits(condition["keyword_group_hits"], state.proposal)
        
        if "title_contains" in condition:
            return self._check_title_contains(condition["title_contains"], state.proposal)
        
        if "body_contains" in condition:
            return self._check_body_contains(condition["body_contains"], state.proposal)
        
        # --- Field Matchers ---
        if "field_equals" in condition:
            return self._check_field_equals(condition["field_equals"], state.proposal)
        
        if "field_exists" in condition:
            return self._check_field_exists(condition["field_exists"], state.proposal)
        
        if "field_in" in condition:
            return self._check_field_in(condition["field_in"], state.proposal)
        
        # --- State Matchers (Labels, Flags) ---
        if "has_label" in condition:
            return self._check_has_label(condition["has_label"], state)
        
        if "not_labeled" in condition:
            return self._check_not_labeled(condition["not_labeled"], state)
        
        if "label_count" in condition:
            return self._check_label_count(condition["label_count"], state)

        if "flag_set" in condition:
            return self._check_flag_set(condition["flag_set"], state)
        
        if "not_flag" in condition:
            return self._check_not_flag(condition["not_flag"], state)
        
        # --- Modifiers ---
        if "time_remaining" in condition:
            return self._check_time_remaining(condition["time_remaining"], state.proposal)
        
        if "word_count" in condition:
            return self._check_word_count(condition["word_count"], state.proposal)
        
        return False
    
    # --- Specific Matcher Helpers ---

    def _check_keyword_group_hits(self, params: Dict, proposal: ProposalInput) -> bool:
        group_name = params["group"]
        threshold = params.get("gte", 1)
        hits = proposal.keyword_hits.get(group_name, 0)
        return hits >= threshold

    def _check_title_contains(self, params: Dict, proposal: ProposalInput) -> bool:
        return self._check_text_match(proposal.title, params)

    def _check_body_contains(self, params: Dict, proposal: ProposalInput) -> bool:
        return self._check_text_match(proposal.body, params)

    def _check_text_match(self, text: str, config: Dict) -> bool:
        if not text: return False
        keywords = config.get("keywords", [])
        min_hits = config.get("min_hits", 1)
        text_lower = text.lower()
        hits = sum(1 for k in keywords if k.lower() in text_lower)
        return hits >= min_hits

    def _check_field_equals(self, params: Dict, proposal: ProposalInput) -> bool:
        field = params["field"]
        expected = params["value"]
        # Use .get() method on proposal to handle aliases like 'state'
        actual = proposal.get(field)
        return actual == expected
    
    def _check_field_exists(self, params: Dict, proposal: ProposalInput) -> bool:
        field = params["field"]
        return proposal.get(field) is not None
    
    def _check_field_in(self, params: Dict, proposal: ProposalInput) -> bool:
        field = params["field"]
        values = params["values"]
        actual = proposal.get(field)
        return actual in values

    def _check_has_label(self, label: str, state: EvaluationState) -> bool:
        return label in state.labels
    
    def _check_not_labeled(self, labels: Union[str, List[str]], state: EvaluationState) -> bool:
        if isinstance(labels, str):
            labels = [labels]
        return not any(label in state.labels for label in labels)
    
    def _check_label_count(self, params: Dict, state: EvaluationState) -> bool:
        count = len(state.labels)
        if "lt" in params and count >= params["lt"]: return False
        if "gt" in params and count <= params["gt"]: return False
        if "eq" in params and count != params["eq"]: return False
        return True

    def _check_flag_set(self, flag: str, state: EvaluationState) -> bool:
        return flag in state.flags

    def _check_not_flag(self, flag: str, state: EvaluationState) -> bool:
        return flag not in state.flags

    def _check_time_remaining(self, params: Dict, proposal: ProposalInput) -> bool:
        if not proposal.end_at: return False
        now = datetime.now(timezone.utc).timestamp()
        remaining_seconds = proposal.end_at - now
        remaining_hours = remaining_seconds / 3600
        
        if "max_hours" in params and remaining_hours > params["max_hours"]:
            return False
        if "min_hours" in params and remaining_hours < params["min_hours"]:
            return False
        return True
    
    def _check_word_count(self, params: Dict, proposal: ProposalInput) -> bool:
        wc = proposal.word_count
        if "gte" in params and wc < params["gte"]: return False
        if "lt" in params and wc >= params["lt"]: return False
        return True

    # -------------------------------------------------------------------------
    # ACTION APPLICATION
    # -------------------------------------------------------------------------

    def _apply_actions(self, rule: Dict, state: EvaluationState) -> EvaluationState:
        """Apply rule actions to state."""
        rule_id = rule.get("id", "unknown")
        actions = rule.get("then", {})
        
        # Audit trail
        state.reasons.append(rule_id)
        
        # Labels
        if "add_labels" in actions:
            for label in actions["add_labels"]:
                state.labels.add(label)
        
        # Context Flags
        if "set_flag" in actions:
            state.flags.add(actions["set_flag"])
        
        # Priority Scores
        if "add_priority" in actions:
            delta = actions["add_priority"]
            state.priority_score += delta
            state.priority_adjustments.append({
                "rule": rule_id,
                "delta": delta,
                "reason": rule.get("name")
            })
            
        if "set_min_priority" in actions:
            new_min = actions["set_min_priority"]
            # Protection: If a higher priority rule has capped the score (max_priority < 100),
            # do not allow a lower priority rule to raise the floor to equal or exceed that cap.
            # This prevents generic rules (like DEFAULT) from forcing a specific score against
            # the limiting intent of a specific rule.
            if state.max_priority < 100 and new_min >= state.max_priority:
                 logger.debug(f"Rule {rule_id} set_min_priority {new_min} ignored: exceeds max_priority {state.max_priority} set by higher rule.")
            else:
                state.min_priority = max(state.min_priority, new_min)
            
        if "set_max_priority" in actions:
            new_max = actions["set_max_priority"]
            # Protection: Since we execute High Priority -> Low Priority,
            # a lower priority rule (like DEFAULT) should not be allowed to set a max
            # that contradicts a min set by a higher priority rule.
            if new_max >= state.min_priority:
                state.max_priority = min(state.max_priority, new_max)
            else:
                logger.debug(f"Rule {rule_id} tried to set max {new_max} < min {state.min_priority}. Ignored.")

        if "set_recommended_handling" in actions:
            # Protection: Only set override if not already set by a higher priority rule
            if state.manual_handling_override is None:
                state.manual_handling_override = actions["set_recommended_handling"]

        # Advanced Logic Tiers
        if actions.get("apply_treasury_tiers_usd"):
            self._apply_treasury_tiers(state, rule_id)
        
        if actions.get("apply_time_sensitivity_tiers"):
            self._apply_time_tiers(state, rule_id)
            
        if actions.get("apply_workload_tiers"):
            self._apply_workload_tiers(state, rule_id)
        
        return state

    # --- Tier Applicators ---

    def _apply_treasury_tiers(self, state: EvaluationState, rule_id: str):
        amount = state.proposal.requested_amount_usd
        if amount is None:
            # NIE cicha rezygnacja. Do v0.1.0 stalo tu `if amount is None: return`,
            # a kwota byla ZAWSZE None, bo model nie mial takiego pola - cala
            # warstwa progow finansowych nie odpalala sie nigdy i nikt tego nie
            # widzial. Brak kwoty i kwota ponizej progu dawaly ten sam wynik.
            #
            # Teraz rozniemy trzy sytuacje: nie znaleziono kwoty, kwota jest
            # w walucie nieprzeliczalnej na dolary (ARB, ETH), kwota jest znana.
            waluta = getattr(state.proposal, "requested_currency", None)
            if waluta:
                state.labels.add("TREASURY_TIER_NOT_EVALUABLE")
                state.reasons.append(f"{rule_id}:amount_in_{waluta}_no_usd_rate")
            else:
                state.labels.add("TREASURY_AMOUNT_UNKNOWN")
                state.reasons.append(f"{rule_id}:no_amount_found_in_text")
            return

        tiers = self.rulebook.get("treasury_tiers_usd", [])
        # Iterate tiers (assuming defined in order or we search for best match)
        for tier in tiers:
            if amount >= tier["min_usd"]:
                if "label" in tier: 
                    state.labels.add(tier["label"])
                
                if "add_priority" in tier:
                    delta = tier["add_priority"]
                    state.priority_score += delta
                    state.priority_adjustments.append({
                        "rule": rule_id, 
                        "delta": delta, 
                        "reason": f"Treasury > ${tier['min_usd']}"
                    })
                
                if "set_min_priority" in tier:
                    state.min_priority = max(state.min_priority, tier["set_min_priority"])
                break

    def _apply_time_tiers(self, state: EvaluationState, rule_id: str):
        if not state.proposal.end_at: return
        now = datetime.now(timezone.utc).timestamp()
        remaining_hours = (state.proposal.end_at - now) / 3600
        if remaining_hours < 0: return

        tiers = self.rulebook.get("time_sensitivity_tiers", [])
        # Sort by hours ascending (closest deadline first)
        sorted_tiers = sorted(tiers, key=lambda x: x["max_hours_remaining"])
        
        for tier in sorted_tiers:
            if remaining_hours <= tier["max_hours_remaining"]:
                if "add_priority" in tier:
                    delta = tier["add_priority"]
                    state.priority_score += delta
                    state.priority_adjustments.append({
                        "rule": rule_id, 
                        "delta": delta, 
                        "reason": tier.get("description", "Time Tier")
                    })
                break

    def _apply_workload_tiers(self, state: EvaluationState, rule_id: str):
        wc = state.proposal.word_count
        tiers = self.rulebook.get("workload_tiers", [])
        # Sort by words descending (largest content first)
        sorted_tiers = sorted(tiers, key=lambda x: x["min_word_count"], reverse=True)
        
        for tier in sorted_tiers:
            if wc >= tier["min_word_count"]:
                if "label" in tier: 
                    state.labels.add(tier["label"])
                
                if "add_priority" in tier:
                    delta = tier["add_priority"]
                    state.priority_score += delta
                    state.priority_adjustments.append({
                        "rule": rule_id, 
                        "delta": delta, 
                        "reason": "Workload Size"
                    })
                break

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _clamp_score(self, score: int, min_p: int, max_p: int) -> int:
        """
        Clamp score to valid range with conflict resolution.
        If min > max, the Cap (Max) wins per rulebook spec.
        
        Logic: 
        1. Raise score to min_priority.
        2. Cap score at max_priority.
        
        If min_p > max_p (Conflict):
           score = max(min_p, score) -> score is at least min_p
           score = min(max_p, score) -> score is capped at max_p
           Since max_p < min_p, the result is max_p.
           This satisfies the 'Cap wins' rule.
        """
        score = max(min_p, score)
        return min(max_p, score)
    
    def _determine_handling(self, score: int, state: EvaluationState) -> str:
        """Map score to handling recommendation"""
        mappings = self.rulebook.get("score_mapping", {})

        # Check for specific override first
        if state.manual_handling_override:
            override = state.manual_handling_override
            
            # CONSISTENCY CHECK:
            # If a High Priority rule set a low max_priority (e.g., 30 for Informational),
            # and a Low Priority rule (e.g., Default) set a "Standard Review" override (min 40),
            # we must reject the override because the Cap (Max Priority) wins conflicts.
            
            override_config = mappings.get(override)
            if override_config:
                req_min = override_config.get("min", 0)
                
                # If the state's hard cap is lower than the override's minimum requirement,
                # the override is invalid.
                if state.max_priority < req_min:
                    logger.debug(
                        f"Ignoring override '{override}' (requires min {req_min}) "
                        f"because max_priority is capped at {state.max_priority}."
                    )
                    # Fall through to score-based mapping
                else:
                    return override
            else:
                # If mapping doesn't exist, assume override is valid custom string
                return override

        # Fallback to score mapping
        for handling, ranges in mappings.items():
            if ranges["min"] <= score <= ranges["max"]:
                return handling
        
        return "standard_review"
    
    def _compute_keyword_hits(self, proposal: ProposalInput) -> Dict[str, int]:
        """Compute keyword hits for all groups (deterministic)"""
        text = (proposal.title + " " + proposal.body).lower()
        hits = {}
        for group_name, pattern in self.keyword_patterns.items():
            matches = pattern.findall(text)
            hits[group_name] = len(matches)
        return hits
    
    def get_rulebook_info(self) -> Dict[str, Any]:
        """Get rulebook metadata"""
        return {
            "version": self.version,
            "path": str(self.rulebook_path),
            "num_rules": len(self.rulebook.get("rules", [])),
            "num_keyword_groups": len(self.rulebook.get("keyword_groups", {})),
            "metadata": self.rulebook.get("metadata", {})
        }

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

#: Waluty, w ktorych progi rulebooka (dolarowe) maja sens bez kursu.
_STABILNE = {"USD", "USDC", "USDT", "DAI"}


def _kwota_w_usd(db_proposal) -> Optional[float]:
    """Kwota, jesli da sie ja porownac z progiem dolarowym.

    Propozycje Arbitrum wnioskuja najczesciej o ARB, a przeliczenie wymaga kursu
    z konkretnej chwili, ktorego nie mamy. Zwracamy None i ODNOTOWUJEMY walute -
    regula ma wtedy powiedziec, ze progu nie da sie ocenic, zamiast przemilczec.
    """
    kwota = getattr(db_proposal, "requested_amount", None)
    waluta = (getattr(db_proposal, "requested_currency", None) or "").upper()
    if kwota is None or waluta not in _STABILNE:
        return None
    return float(kwota)


def proposal_from_db_model(db_proposal) -> ProposalInput:
    """Convert database Proposal model to ProposalInput"""
    # Compute word count
    body_text = db_proposal.body or ""
    word_count = len(body_text.split())
    
    # Safely handle dates which might be timestamps or strings in DB
    created_ts = 0
    if hasattr(db_proposal, 'created_at') and db_proposal.created_at:
        if hasattr(db_proposal.created_at, 'timestamp'):
            created_ts = int(db_proposal.created_at.timestamp())
        else:
            # Assume it might be an int/float already if not a datetime object
            try:
                created_ts = int(db_proposal.created_at)
            except (ValueError, TypeError):
                created_ts = 0

    return ProposalInput(
        item_id=str(db_proposal.id),
        title=db_proposal.title,
        body=body_text,
        author=db_proposal.author or "unknown",
        created_at=created_ts,
        start_at=int(db_proposal.start) if hasattr(db_proposal, 'start') and db_proposal.start else 0,
        end_at=int(db_proposal.end) if hasattr(db_proposal, 'end') and db_proposal.end else 0,
        status=getattr(db_proposal, 'state', 'unknown') or "unknown",
        word_count=word_count,
        # Map extra fields if they exist on the DB model
        requested_amount_usd=_kwota_w_usd(db_proposal),
        requested_currency=getattr(db_proposal, 'requested_currency', None),
        proposal_kind=getattr(db_proposal, 'proposal_kind', None)
    )

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

def create_test_proposal(**kwargs) -> ProposalInput:
    """Helper to create test proposals"""
    defaults = {
        "item_id": "test_001",
        "title": "Test Proposal",
        "body": "Test body content",
        "author": "0xtest",
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "status": "active",
    }
    defaults.update(kwargs)
    return ProposalInput(**defaults)

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Initialize engine
    engine = RuleEngine()
    
    print("="*70)
    print("RULEBOOK INFO")
    print("="*70)
    print(engine.get_rulebook_info())
    
    # Test case: Security incident
    p = create_test_proposal(
        title="Urgent: Active Exploit Detected",
        body="Funds are being drained. Emergency pause required."
    )
    result = engine.evaluate_proposal(p)
    print("\nResult:", result)