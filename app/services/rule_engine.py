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
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
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
    author: str
    created_at: int  # Unix timestamp
    start_at: int
    end_at: int
    status: str  # draft|active|closed|executed|canceled|unknown
    
    # Optional governance metadata
    venue: str = "snapshot"
    chain: str = "arbitrum-one"
    item_type: str = "proposal"
    proposal_kind: Optional[str] = None  # constitutional|treasury|election|technical|ops|meta|unknown
    requested_amount_usd: Optional[float] = None
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
    priority_score: int = 50  # Start at baseline
    min_priority: int = 0
    max_priority: int = 100
    reasons: List[str] = field(default_factory=list)
    priority_adjustments: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# RULE ENGINE
# ============================================================================

class RuleEngine:
    """
    Deterministic rule evaluation engine.
    
    Evaluation order (Section 4.1):
    1. Label rules
    2. Base priority rules
    3. Time modifiers
    4. Workload modifiers
    5. Clamp score
    6. Apply overrides
    7. Map to handling
    """
    
    def __init__(self, rulebook_path: str = "rulebook.yaml"):
        """Load and parse rulebook"""
        self.rulebook_path = Path(rulebook_path)
        self.rulebook = self._load_rulebook()
        self.version = self.rulebook.get("version", "unknown")
        
        logger.info(f"RuleEngine initialized with rulebook v{self.version}")
    
    def _load_rulebook(self) -> Dict:
        """Load YAML rulebook"""
        if not self.rulebook_path.exists():
            raise FileNotFoundError(f"Rulebook not found: {self.rulebook_path}")
        
        with open(self.rulebook_path, 'r') as f:
            rulebook = yaml.safe_load(f)
        
        # Validate required sections
        required = ["version", "keyword_groups", "score_mapping", "rules"]
        missing = [r for r in required if r not in rulebook]
        if missing:
            raise ValueError(f"Rulebook missing required sections: {missing}")
        
        return rulebook
    
    def evaluate_proposal(self, proposal: ProposalInput) -> TriageResult:
        """
        Main entry point: evaluate a proposal against all rules.
        
        Returns:
            TriageResult with labels, score, handling, and audit trail
        """
        logger.debug(f"Evaluating proposal {proposal.item_id}: {proposal.title[:50]}")
        
        # Initialize state
        state = EvaluationState(proposal=proposal)
        
        # Compute keyword hits if not already done
        if not proposal.keyword_hits:
            proposal.keyword_hits = self._compute_keyword_hits(proposal)
        
        # Execute evaluation pipeline
        state = self._apply_rules_by_category(state, "SECURITY")
        state = self._apply_rules_by_category(state, "TECHNICAL")
        state = self._apply_rules_by_category(state, "TREASURY")
        state = self._apply_rules_by_category(state, "GOVERNANCE")
        state = self._apply_rules_by_category(state, "ELECTIONS")
        state = self._apply_rules_by_category(state, "OPERATIONS")
        state = self._apply_rules_by_category(state, "REPORTING")
        state = self._apply_rules_by_category(state, "META_GOVERNANCE")
        state = self._apply_rules_by_category(state, "TIME_MODIFIER")
        state = self._apply_rules_by_category(state, "WORKLOAD_MODIFIER")
        
        # Clamp score to valid range
        final_score = self._clamp_score(
            state.priority_score, 
            state.min_priority, 
            state.max_priority
        )
        
        # Map to recommended handling
        handling = self._map_score_to_handling(final_score)
        
        # Apply overrides (e.g., SECURITY always urgent)
        handling = self._apply_overrides(handling, state.labels)
        
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
                "rulebook_version": self.version
            }
        )
        
        logger.info(
            f"Proposal {proposal.item_id}: "
            f"score={final_score}, handling={handling}, "
            f"labels={len(result.labels)}, rules_fired={len(result.reasons)}"
        )
        
        return result
    
    def _apply_rules_by_category(self, state: EvaluationState, category: str) -> EvaluationState:
        """Apply all rules in a category"""
        rules = [r for r in self.rulebook["rules"] if r.get("category") == category]
        
        # Sort by priority (higher first)
        rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)
        
        for rule in rules:
            if self._evaluate_condition(rule["when"], state.proposal):
                state = self._apply_actions(rule, state)
        
        return state
    
    def _evaluate_condition(self, condition: Dict, proposal: ProposalInput) -> bool:
        """
        Evaluate a condition against a proposal.
        
        Supported conditions:
        - any: [list of conditions] - OR logic
        - all: [list of conditions] - AND logic
        - keyword_group_hits: {group, gte}
        - keyword_contains: {keywords, min_hits}
        - field_equals: {field, value}
        - field_exists: {field}
        - field_not_exists: {field}
        - field_in: {field, values}
        - title_contains: {keywords, min_hits}
        - word_count: {gte, lt}
        - time_remaining: {max_hours, min_hours}
        - has_label: label
        - not_labeled: [labels]
        """
        # Handle composite conditions
        if "any" in condition:
            return any(self._evaluate_condition(c, proposal) for c in condition["any"])
        
        if "all" in condition:
            return all(self._evaluate_condition(c, proposal) for c in condition["all"])
        
        # Handle atomic conditions
        if "keyword_group_hits" in condition:
            return self._check_keyword_group_hits(condition["keyword_group_hits"], proposal)
        
        if "keyword_contains" in condition:
            return self._check_keyword_contains(condition["keyword_contains"], proposal)
        
        if "field_equals" in condition:
            return self._check_field_equals(condition["field_equals"], proposal)
        
        if "field_exists" in condition:
            return self._check_field_exists(condition["field_exists"], proposal)
        
        if "field_not_exists" in condition:
            return not self._check_field_exists(condition["field_not_exists"], proposal)
        
        if "field_in" in condition:
            return self._check_field_in(condition["field_in"], proposal)
        
        if "title_contains" in condition:
            return self._check_title_contains(condition["title_contains"], proposal)
        
        if "word_count" in condition:
            return self._check_word_count(condition["word_count"], proposal)
        
        if "time_remaining" in condition:
            return self._check_time_remaining(condition["time_remaining"], proposal)
        
        logger.warning(f"Unknown condition type: {list(condition.keys())}")
        return False
    
    def _check_keyword_group_hits(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check if keyword group has minimum hits"""
        group_name = params["group"]
        threshold = params.get("gte", 1)
        
        hits = proposal.keyword_hits.get(group_name, 0)
        return hits >= threshold
    
    def _check_keyword_contains(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check if text contains keywords"""
        keywords = params["keywords"]
        min_hits = params.get("min_hits", 1)
        
        text = (proposal.title + " " + proposal.body).lower()
        hits = sum(1 for kw in keywords if kw.lower() in text)
        
        return hits >= min_hits
    
    def _check_field_equals(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check if field equals value"""
        field = params["field"]
        expected = params["value"]
        
        actual = getattr(proposal, field, None)
        return actual == expected
    
    def _check_field_exists(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check if field exists and is not None"""
        field = params["field"]
        value = getattr(proposal, field, None)
        return value is not None
    
    def _check_field_in(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check if field value is in list"""
        field = params["field"]
        values = params["values"]
        
        actual = getattr(proposal, field, None)
        return actual in values
    
    def _check_title_contains(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check if title contains keywords"""
        keywords = params["keywords"]
        min_hits = params.get("min_hits", 1)
        
        title_lower = proposal.title.lower()
        hits = sum(1 for kw in keywords if kw.lower() in title_lower)
        
        return hits >= min_hits
    
    def _check_word_count(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check word count thresholds"""
        gte = params.get("gte")
        lt = params.get("lt")
        
        wc = proposal.word_count
        
        if gte is not None and wc < gte:
            return False
        if lt is not None and wc >= lt:
            return False
        
        return True
    
    def _check_time_remaining(self, params: Dict, proposal: ProposalInput) -> bool:
        """Check time remaining until end_at"""
        max_hours = params.get("max_hours")
        min_hours = params.get("min_hours", 0)
        
        now = datetime.now(timezone.utc).timestamp()
        remaining_seconds = proposal.end_at - now
        remaining_hours = remaining_seconds / 3600
        
        if remaining_hours < min_hours:
            return False
        if max_hours is not None and remaining_hours > max_hours:
            return False
        
        return True
    
    def _apply_actions(self, rule: Dict, state: EvaluationState) -> EvaluationState:
        """
        Apply rule actions to state.
        
        Supported actions:
        - add_labels: [labels]
        - set_min_priority: int
        - set_max_priority: int
        - add_priority: int
        - set_recommended_handling: str
        - apply_treasury_tiers_usd: bool
        """
        rule_id = rule["id"]
        actions = rule["then"]
        
        # Track that this rule fired
        state.reasons.append(rule_id)
        
        # Add labels
        if "add_labels" in actions:
            for label in actions["add_labels"]:
                state.labels.add(label)
        
        # Set min/max priority (conflict resolution via max/min)
        if "set_min_priority" in actions:
            new_min = actions["set_min_priority"]
            state.min_priority = max(state.min_priority, new_min)
        
        if "set_max_priority" in actions:
            new_max = actions["set_max_priority"]
            state.max_priority = min(state.max_priority, new_max)
        
        # Add priority points
        if "add_priority" in actions:
            delta = actions["add_priority"]
            state.priority_score += delta
            state.priority_adjustments.append({
                "rule": rule_id,
                "delta": delta,
                "reason": rule["name"]
            })
        
        # Apply treasury tiers
        if actions.get("apply_treasury_tiers_usd"):
            state = self._apply_treasury_tiers(state)
        
        return state
    
    def _apply_treasury_tiers(self, state: EvaluationState) -> EvaluationState:
        """Apply treasury magnitude tiers (Section 6.2)"""
        amount = state.proposal.requested_amount_usd
        if amount is None:
            return state
        
        tiers = self.rulebook.get("treasury_tiers_usd", [])
        
        # Find highest applicable tier
        for tier in sorted(tiers, key=lambda t: t["min_usd"], reverse=True):
            if amount >= tier["min_usd"]:
                state.priority_score += tier["add_priority"]
                state.min_priority = max(state.min_priority, tier["set_min_priority"])
                
                if "label" in tier:
                    state.labels.add(tier["label"])
                
                state.priority_adjustments.append({
                    "rule": "TREASURY_TIER",
                    "delta": tier["add_priority"],
                    "reason": f"Amount ${amount:,.0f} → tier {tier['min_usd']}"
                })
                
                break
        
        return state
    
    def _clamp_score(self, score: int, min_p: int, max_p: int) -> int:
        """Clamp score to valid range with conflict resolution"""
        # Ensure min <= max (conflict resolution: min wins if conflict)
        if min_p > max_p:
            logger.warning(f"Min priority {min_p} > max priority {max_p}, using min")
            return min_p
        
        return max(min_p, min(max_p, score))
    
    def _map_score_to_handling(self, score: int) -> str:
        """Map priority score to recommended handling (Section 6.5)"""
        score_mapping = self.rulebook["score_mapping"]
        
        for handling, ranges in score_mapping.items():
            if ranges["min"] <= score <= ranges["max"]:
                return handling
        
        # Fallback (should never happen)
        logger.warning(f"Score {score} not in any band, defaulting to standard_review")
        return "standard_review"
    
    def _apply_overrides(self, handling: str, labels: Set[str]) -> str:
        """Apply special overrides (e.g., SECURITY always urgent)"""
        overrides = self.rulebook.get("overrides", [])
        
        for override in overrides:
            # Check condition
            if "has_label" in override["condition"]:
                required_label = override["condition"]["has_label"]
                if required_label in labels:
                    # Apply forced handling
                    return override["force"]["recommended_handling"]
        
        return handling
    
    def _compute_keyword_hits(self, proposal: ProposalInput) -> Dict[str, int]:
        """Compute keyword hits for all groups (deterministic)"""
        keyword_groups = self.rulebook["keyword_groups"]
        text = (proposal.title + " " + proposal.body).lower()
        
        hits = {}
        for group_name, keywords in keyword_groups.items():
            count = sum(1 for kw in keywords if kw.lower() in text)
            hits[group_name] = count
        
        return hits
    
    def get_rulebook_info(self) -> Dict[str, Any]:
        """Get rulebook metadata"""
        return {
            "version": self.version,
            "path": str(self.rulebook_path),
            "num_rules": len(self.rulebook["rules"]),
            "num_keyword_groups": len(self.rulebook["keyword_groups"]),
            "metadata": self.rulebook.get("metadata", {})
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def proposal_from_db_model(db_proposal) -> ProposalInput:
    """Convert database Proposal model to ProposalInput"""
    # Compute word count
    body_text = db_proposal.body or ""
    word_count = len(body_text.split())
    
    return ProposalInput(
        item_id=db_proposal.id,
        title=db_proposal.title,
        body=body_text,
        author=db_proposal.author or "unknown",
        created_at=db_proposal.created_at.timestamp() if hasattr(db_proposal.created_at, 'timestamp') else 0,
        start_at=db_proposal.start or 0,
        end_at=db_proposal.end or 0,
        status=db_proposal.state or "unknown",
        word_count=word_count,
        # Add other fields as available in your DB model
    )


def create_test_proposal(**kwargs) -> ProposalInput:
    """Helper to create test proposals"""
    defaults = {
        "item_id": "test_001",
        "title": "Test Proposal",
        "body": "Test body content",
        "author": "0xtest",
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "start_at": int(datetime.now(timezone.utc).timestamp()),
        "end_at": int((datetime.now(timezone.utc).timestamp()) + 86400 * 7),  # 7 days
        "status": "active",
    }
    defaults.update(kwargs)
    return ProposalInput(**defaults)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Initialize engine
    engine = RuleEngine("rulebook.yaml")
    
    print("="*70)
    print("RULEBOOK INFO")
    print("="*70)
    info = engine.get_rulebook_info()
    for key, value in info.items():
        print(f"{key}: {value}")
    
    # Test case 1: Security incident
    print("\n" + "="*70)
    print("TEST CASE 1: Security Incident")
    print("="*70)
    
    security_proposal = create_test_proposal(
        item_id="sec_001",
        title="Emergency: Critical Vulnerability Discovered",
        body="A critical exploit was found in the bridge contract. Immediate action required.",
        status="active"
    )
    
    result = engine.evaluate_proposal(security_proposal)
    print(f"Score: {result.priority_score}")
    print(f"Handling: {result.recommended_handling}")
    print(f"Labels: {result.labels}")
    print(f"Reasons: {result.reasons}")
    
    # Test case 2: Large treasury allocation
    print("\n" + "="*70)
    print("TEST CASE 2: Large Treasury Allocation")
    print("="*70)
    
    treasury_proposal = create_test_proposal(
        item_id="tre_001",
        title="Q1 2026 Treasury Allocation",
        body="Requesting allocation of funds for operations budget and grants program.",
        requested_amount_usd=5_000_000,
        proposal_kind="treasury"
    )
    
    result = engine.evaluate_proposal(treasury_proposal)
    print(f"Score: {result.priority_score}")
    print(f"Handling: {result.recommended_handling}")
    print(f"Labels: {result.labels}")
    print(f"Reasons: {result.reasons}")
    print(f"Adjustments: {result.explain['priority_adjustments']}")
    
    # Test case 3: Routine operations
    print("\n" + "="*70)
    print("TEST CASE 3: Routine Operations")
    print("="*70)
    
    ops_proposal = create_test_proposal(
        item_id="ops_001",
        title="Monthly housekeeping and maintenance tasks",
        body="Routine admin procedures for the operational calendar.",
        proposal_kind="ops"
    )
    
    result = engine.evaluate_proposal(ops_proposal)
    print(f"Score: {result.priority_score}")
    print(f"Handling: {result.recommended_handling}")
    print(f"Labels: {result.labels}")
    print(f"Reasons: {result.reasons}")
