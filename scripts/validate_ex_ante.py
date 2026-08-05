#!/usr/bin/env python3
"""
Ex Ante Validation Script for Rule Engine
==========================================

Runs the rule engine on the full historical dataset of Arbitrum DAO proposals
and generates a validation report analyzing False Positives / False Negatives.

Research objectives:
- SEC-001: Do security rules incorrectly flag normal proposals as critical?
- OPS-050: Do noise filters incorrectly suppress important decisions?
- ALL RULES: Validate firing frequency and detect potential issues.

Usage:
    python scripts/validate_ex_ante.py
    python scripts/validate_ex_ante.py --months 12
    python scripts/validate_ex_ante.py --output report.json
"""

import sys
import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import asdict
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.rule_engine import RuleEngine, ProposalInput


def load_proposals_from_db(db_path: str, months: int = None) -> list:
    """Load proposals from SQLite database"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if months:
        cutoff = (datetime.now() - timedelta(days=months * 30)).timestamp()
        cur.execute("""
            SELECT id, title, body, state, author, start, votes, scores_total
            FROM proposals
            WHERE start >= ?
            ORDER BY start DESC
        """, (cutoff,))
    else:
        cur.execute("""
            SELECT id, title, body, state, author, start, votes, scores_total
            FROM proposals
            ORDER BY start DESC
        """)

    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def convert_to_proposal_input(row: dict) -> ProposalInput:
    """Convert database row to ProposalInput"""
    return ProposalInput(
        item_id=row['id'],
        title=row['title'] or '',
        body=row['body'] or '',
        author=row['author'] or 'unknown',
        status=row['state'] or 'unknown',
        created_at=row['start'] or 0,
        start_at=row['start'],
    )


def analyze_results(results: list) -> dict:
    """Analyze triage results for potential issues across ALL rules"""

    analysis = {
        # Z10: sklad korpusu i ILE PROPOZYCJI W OGOLE MOGLO uruchomic dana regule.
        #
        # Do v0.1.0 raport podawal, ile razy regula odpalila, i nie mowil, ile razy
        # MOGLA. Korpus pochodzil z pobierania ograniczonego do propozycji
        # zamknietych, a SEC-001-STRICT wymaga `not_flag: STATE_CLOSED` - zero
        # odpalen bylo wiec wynikiem konstrukcji, nie pomiarem. Skrypt sam pisal
        # "expected for historical data" i mimo to zero szlo do raportu jako
        # dowod trafnosci.
        'coverage': {
            'by_state': defaultdict(int),
            'sec_001_eligible': 0,      # propozycje NIE zamkniete - tylko te moga odpalic
            'note': ('Zero firings on a corpus that cannot trigger a rule is a '
                     'property of the corpus, not evidence about the rule.'),
        },
        'summary': {
            'total_proposals': len(results),
            'by_handling': defaultdict(int),
            'by_label': defaultdict(int),
            'by_rule': defaultdict(int),  # Count how many times each rule fired
            'score_distribution': {
                '90-100 (urgent)': 0,
                '70-89 (deep_review)': 0,
                '40-69 (standard)': 0,
                '25-39 (fast_track)': 0,
                '0-24 (informational)': 0,
            }
        },
        # ========== PHASE 0: CONTEXT ==========
        'ctx_001_analysis': {
            'rule_id': 'CTX-001',
            'description': 'Detect Closed State - ustawia flagę STATE_CLOSED',
            'count': 0,
            'sample': []
        },
        'ctx_002_analysis': {
            'rule_id': 'CTX-002',
            'description': 'Detect Election Context - ustawia flagę CONTEXT_ELECTION',
            'count': 0,
            'sample': [],
            'potential_issues': []  # Proposals with "election" in title but flag not set
        },
        'ctx_003_analysis': {
            'rule_id': 'CTX-003',
            'description': 'Detect HR Context (compensation, salary)',
            'count': 0,
            'sample': []
        },
        'ctx_004_analysis': {
            'rule_id': 'CTX-004',
            'description': 'Detect Sponsorship Context',
            'count': 0,
            'sample': []
        },
        # ========== PHASE 1: CRITICAL ==========
        'sec_001_analysis': {
            'rule_id': 'SEC-001-STRICT',
            'description': 'Active Security Incident - oznacza INCIDENT/EMERGENCY',
            'count': 0,
            'proposals': [],
            'potential_false_positives': []
        },
        'tech_001_analysis': {
            'rule_id': 'TECH-001-STRICT',
            'description': 'Protocol Upgrade - oznacza PROTOCOL_UPGRADE, min_priority=80',
            'count': 0,
            'proposals': [],
            'potential_false_positives': []  # Czy zwykłe propozycje są oznaczone jako upgrade?
        },
        # ========== PHASE 2: STANDARD ==========
        'prog_001_analysis': {
            'rule_id': 'PROG-001',
            'description': 'New Program Creation - oznacza NEW_PROGRAM/STRATEGY',
            'count': 0,
            'sample': []
        },
        'tech_002_analysis': {
            'rule_id': 'TECH-002',
            'description': 'Parameter Change',
            'count': 0,
            'sample': []
        },
        'tre_010_analysis': {
            'rule_id': 'TRE-010',
            'description': 'Treasury Spend (z known amount)',
            'count': 0,
            'sample': []
        },
        'tre_021_analysis': {
            'rule_id': 'TRE-021',
            'description': 'Treasury Cues (unknown amount) - oznacza BUDGET_UNCLEAR',
            'count': 0,
            'sample': [],
            'potential_issues': []  # Proposals with large amounts but missing TREASURY label
        },
        'gov_030_analysis': {
            'rule_id': 'GOV-030',
            'description': 'Constitutional Change - min_priority=75',
            'count': 0,
            'proposals': [],
            'potential_false_negatives': []  # Proposals with "constitutional" but GOV-030 did not fire
        },
        'meta_001_analysis': {
            'rule_id': 'META-001',
            'description': 'Meta Governance / RFC - max_priority=50',
            'count': 0,
            'sample': []
        },
        'spon_001_analysis': {
            'rule_id': 'SPON-001',
            'description': 'Sponsorship Request - max_priority=60',
            'count': 0,
            'sample': []
        },
        'ops_050_analysis': {
            'rule_id': 'OPS-050',
            'description': 'Operational / Administrative - max_priority=45',
            'count': 0,
            'proposals': [],
            'potential_false_negatives': []
        },
        'rep_001_analysis': {
            'rule_id': 'REP-001-STRICT',
            'description': 'Reporting - max_priority=35',
            'count': 0,
            'sample': []
        },
        'res_001_analysis': {
            'rule_id': 'RES-001',
            'description': 'Research',
            'count': 0,
            'sample': []
        },
        # ========== PHASE 4: OVERRIDES ==========
        'override_analysis': {
            'description': 'Kill Switches dla zamkniętych propozycji',
            'by_override_rule': defaultdict(int),
            'high_priority_closed': [],  # Zamknięte z score > 60
            'sample': []
        },
        # ========== PHASE 5: DEFAULT ==========
        'uncategorized': {
            'rule_id': 'DEFAULT-001',
            'description': 'Proposals without categorization',
            'count': 0,
            'proposals': []
        }
    }

    for r in results:
        item_id = r['item_id']
        title = r['title']
        score = r['priority_score']
        labels = r['labels']
        reasons = r['reasons']
        handling = r['recommended_handling']
        title_lower = title.lower()

        # Z10: sklad korpusu i kwalifikowalnosc do reguly bezpieczenstwa
        stan = (r.get('state') or 'unknown')
        analysis['coverage']['by_state'][stan] += 1
        if stan != 'closed':
            analysis['coverage']['sec_001_eligible'] += 1

        # Summary stats
        analysis['summary']['by_handling'][handling] += 1
        for label in labels:
            analysis['summary']['by_label'][label] += 1
        for rule in reasons:
            analysis['summary']['by_rule'][rule] += 1

        # Score distribution
        if score >= 90:
            analysis['summary']['score_distribution']['90-100 (urgent)'] += 1
        elif score >= 70:
            analysis['summary']['score_distribution']['70-89 (deep_review)'] += 1
        elif score >= 40:
            analysis['summary']['score_distribution']['40-69 (standard)'] += 1
        elif score >= 25:
            analysis['summary']['score_distribution']['25-39 (fast_track)'] += 1
        else:
            analysis['summary']['score_distribution']['0-24 (informational)'] += 1

        entry = {
            'id': item_id,
            'title': title[:100],
            'score': score,
            'labels': labels,
            'reasons': reasons
        }

        # ========== PHASE 0: CONTEXT RULES ==========
        if 'CTX-001' in reasons:
            analysis['ctx_001_analysis']['count'] += 1
            if len(analysis['ctx_001_analysis']['sample']) < 5:
                analysis['ctx_001_analysis']['sample'].append(entry)

        if 'CTX-002' in reasons:
            analysis['ctx_002_analysis']['count'] += 1
            if len(analysis['ctx_002_analysis']['sample']) < 5:
                analysis['ctx_002_analysis']['sample'].append(entry)
        elif any(kw in title_lower for kw in ['election', 'nomination', 'candidate']):
            # Potential missed election detection
            analysis['ctx_002_analysis']['potential_issues'].append({
                **entry,
                'flag': 'Contains election keywords but CTX-002 did not fire'
            })

        if 'CTX-003' in reasons:
            analysis['ctx_003_analysis']['count'] += 1
            if len(analysis['ctx_003_analysis']['sample']) < 5:
                analysis['ctx_003_analysis']['sample'].append(entry)

        if 'CTX-004' in reasons:
            analysis['ctx_004_analysis']['count'] += 1
            if len(analysis['ctx_004_analysis']['sample']) < 5:
                analysis['ctx_004_analysis']['sample'].append(entry)

        # ========== PHASE 1: CRITICAL RULES ==========

        # SEC-001: Security incidents
        if 'SEC-001-STRICT' in reasons or 'INCIDENT' in labels or 'EMERGENCY' in labels:
            analysis['sec_001_analysis']['count'] += 1
            analysis['sec_001_analysis']['proposals'].append(entry)

            false_positive_indicators = [
                'grant', 'budget', 'election', 'vote', 'report',
                'update', 'summary', 'council', 'delegate'
            ]
            if any(ind in title_lower for ind in false_positive_indicators):
                entry_copy = {**entry, 'flag': 'POTENTIAL_FALSE_POSITIVE: Contains non-security keywords'}
                analysis['sec_001_analysis']['potential_false_positives'].append(entry_copy)

        # TECH-001: Protocol upgrades
        if 'TECH-001-STRICT' in reasons:
            analysis['tech_001_analysis']['count'] += 1
            analysis['tech_001_analysis']['proposals'].append(entry)

            # Check for potential false positives - generic updates marked as protocol upgrade
            non_protocol_indicators = ['report', 'summary', 'election', 'council', 'delegate']
            if any(ind in title_lower for ind in non_protocol_indicators) and 'upgrade' not in title_lower:
                entry_copy = {**entry, 'flag': 'POTENTIAL_FALSE_POSITIVE: May not be actual protocol upgrade'}
                analysis['tech_001_analysis']['potential_false_positives'].append(entry_copy)

        # ========== PHASE 2: STANDARD RULES ==========

        if 'PROG-001' in reasons:
            analysis['prog_001_analysis']['count'] += 1
            if len(analysis['prog_001_analysis']['sample']) < 10:
                analysis['prog_001_analysis']['sample'].append(entry)

        if 'TECH-002' in reasons:
            analysis['tech_002_analysis']['count'] += 1
            if len(analysis['tech_002_analysis']['sample']) < 10:
                analysis['tech_002_analysis']['sample'].append(entry)

        if 'TRE-010' in reasons:
            analysis['tre_010_analysis']['count'] += 1
            if len(analysis['tre_010_analysis']['sample']) < 10:
                analysis['tre_010_analysis']['sample'].append(entry)

        if 'TRE-021' in reasons:
            analysis['tre_021_analysis']['count'] += 1
            if len(analysis['tre_021_analysis']['sample']) < 10:
                analysis['tre_021_analysis']['sample'].append(entry)

        # GOV-030: Constitutional changes
        if 'GOV-030' in reasons:
            analysis['gov_030_analysis']['count'] += 1
            analysis['gov_030_analysis']['proposals'].append(entry)
        elif 'constitutional' in title_lower:
            # Missed constitutional detection
            entry_copy = {**entry, 'flag': 'POTENTIAL_FALSE_NEGATIVE: Has "constitutional" but GOV-030 did not fire'}
            analysis['gov_030_analysis']['potential_false_negatives'].append(entry_copy)

        if 'META-001' in reasons:
            analysis['meta_001_analysis']['count'] += 1
            if len(analysis['meta_001_analysis']['sample']) < 10:
                analysis['meta_001_analysis']['sample'].append(entry)

        if 'SPON-001' in reasons:
            analysis['spon_001_analysis']['count'] += 1
            if len(analysis['spon_001_analysis']['sample']) < 10:
                analysis['spon_001_analysis']['sample'].append(entry)

        # OPS-050: Operational filter
        if 'OPS-050' in reasons:
            analysis['ops_050_analysis']['count'] += 1
            analysis['ops_050_analysis']['proposals'].append(entry)

            important_keywords = [
                'constitutional', 'protocol', 'security', 'emergency',
                'upgrade', 'critical', 'treasury', 'million'
            ]
            if any(kw in title_lower for kw in important_keywords):
                entry_copy = {**entry, 'flag': 'POTENTIAL_FALSE_NEGATIVE: Contains important keywords but marked operational'}
                analysis['ops_050_analysis']['potential_false_negatives'].append(entry_copy)

        if 'REP-001-STRICT' in reasons:
            analysis['rep_001_analysis']['count'] += 1
            if len(analysis['rep_001_analysis']['sample']) < 10:
                analysis['rep_001_analysis']['sample'].append(entry)

        if 'RES-001' in reasons:
            analysis['res_001_analysis']['count'] += 1
            if len(analysis['res_001_analysis']['sample']) < 10:
                analysis['res_001_analysis']['sample'].append(entry)

        # ========== PHASE 4: OVERRIDES ==========
        override_rules = [r for r in reasons if r.startswith('OVERRIDE-')]
        for override in override_rules:
            analysis['override_analysis']['by_override_rule'][override] += 1

        if override_rules and score >= 60:
            analysis['override_analysis']['high_priority_closed'].append(entry)

        # ========== PHASE 5: DEFAULT ==========
        if 'DEFAULT-001' in reasons:
            analysis['uncategorized']['count'] += 1
            analysis['uncategorized']['proposals'].append({
                'id': item_id,
                'title': title[:100],
                'score': score
            })

    # Convert defaultdicts to regular dicts for JSON serialization
    analysis['summary']['by_handling'] = dict(analysis['summary']['by_handling'])
    analysis['summary']['by_label'] = dict(analysis['summary']['by_label'])
    analysis['summary']['by_rule'] = dict(analysis['summary']['by_rule'])
    analysis['override_analysis']['by_override_rule'] = dict(analysis['override_analysis']['by_override_rule'])

    return analysis


def print_report(analysis: dict, verbose: bool = False):
    """Print formatted validation report for ALL rules"""

    total = analysis['summary']['total_proposals']

    print("\n" + "="*80)
    print("  EX ANTE VALIDATION REPORT - Rule Engine & Rulebook.yaml")
    print("  >>> FULL RULEBOOK COVERAGE ANALYSIS <<<")
    print("="*80)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Summary
    print("\n📊 SUMMARY")
    print("-"*40)
    print(f"Total proposals evaluated: {total}")

    print("\nScore Distribution:")
    for bucket, count in analysis['summary']['score_distribution'].items():
        pct = count / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {bucket:25} {count:4} ({pct:5.1f}%) {bar}")

    print("\nHandling Recommendations:")
    for handling, count in sorted(analysis['summary']['by_handling'].items(), key=lambda x: -x[1]):
        print(f"  {handling:25} {count:4}")

    # ========== PHASE 0: CONTEXT RULES ==========
    print("\n" + "="*80)
    print("📋 PHASE 0: CONTEXT DETECTION RULES")
    print("="*80)

    ctx_rules = [
        ('ctx_001_analysis', 'CTX-001', 'STATE_CLOSED detection'),
        ('ctx_002_analysis', 'CTX-002', 'CONTEXT_ELECTION detection'),
        ('ctx_003_analysis', 'CTX-003', 'CONTEXT_HR detection'),
        ('ctx_004_analysis', 'CTX-004', 'CONTEXT_SPONSORSHIP detection'),
    ]

    for key, rule_id, desc in ctx_rules:
        data = analysis[key]
        count = data['count']
        pct = count / total * 100 if total > 0 else 0
        status = "✅" if count > 0 else "⚪"
        print(f"  {status} {rule_id:12} {count:4} ({pct:5.1f}%)  {desc}")

        if 'potential_issues' in data and data['potential_issues']:
            print(f"     ⚠️  {len(data['potential_issues'])} potential missed detections")
            for issue in data['potential_issues'][:3]:
                print(f"        - [{issue['score']}] {issue['title'][:50]}")

    # ========== PHASE 1: CRITICAL RULES ==========
    print("\n" + "="*80)
    print("🔴 PHASE 1: CRITICAL RULES (Security & Protocol)")
    print("="*80)

    # SEC-001
    sec = analysis['sec_001_analysis']
    print(f"\n  SEC-001-STRICT: Active Security Incident")
    print(f"  Fired: {sec['count']} times")
    kwalifikujace = analysis['coverage']['sec_001_eligible']
    print(f"  Eligible proposals (not closed): {kwalifikujace}")
    if kwalifikujace == 0:
        print("  ⚠️  NIE DA SIE NIC ORZEC: zaden element korpusu nie mogl uruchomic")
        print("     tej reguly (wymaga not_flag STATE_CLOSED). Zero odpalen jest")
        print("     wlasnoscia korpusu, nie wynikiem o regule.")
    elif sec['count'] == 0:
        print(f"  Brak odpalen przy {kwalifikujace} propozycjach kwalifikujacych sie.")
        print("     To wynik. Wczesniej korpus nie zawieral zadnej takiej propozycji.")
    else:
        print(f"  Proposals: {[p['title'][:40] for p in sec['proposals'][:3]]}")

    if sec['potential_false_positives']:
        print(f"  ⚠️  POTENTIAL FALSE POSITIVES: {len(sec['potential_false_positives'])}")
        for p in sec['potential_false_positives'][:5]:
            print(f"      [{p['score']:3}] {p['title'][:50]}")
    else:
        print("  ✅ No obvious false positives")

    # TECH-001
    tech1 = analysis['tech_001_analysis']
    print(f"\n  TECH-001-STRICT: Protocol Upgrade")
    print(f"  Fired: {tech1['count']} times ({tech1['count']/total*100:.1f}%)")

    if tech1['potential_false_positives']:
        print(f"  ⚠️  POTENTIAL FALSE POSITIVES: {len(tech1['potential_false_positives'])}")
        for p in tech1['potential_false_positives'][:5]:
            print(f"      [{p['score']:3}] {p['title'][:50]}")
    else:
        print("  ✅ No obvious false positives")

    # ========== PHASE 2: STANDARD RULES ==========
    print("\n" + "="*80)
    print("🟢 PHASE 2: STANDARD CLASSIFICATION RULES")
    print("="*80)

    std_rules = [
        ('prog_001_analysis', 'PROG-001', 'New Program Creation'),
        ('tech_002_analysis', 'TECH-002', 'Parameter Change'),
        ('tre_010_analysis', 'TRE-010', 'Treasury (known amount)'),
        ('tre_021_analysis', 'TRE-021', 'Treasury (unknown amount)'),
        ('gov_030_analysis', 'GOV-030', 'Constitutional Change'),
        ('meta_001_analysis', 'META-001', 'Meta Governance / RFC'),
        ('spon_001_analysis', 'SPON-001', 'Sponsorship'),
        ('ops_050_analysis', 'OPS-050', 'Operational / Administrative'),
        ('rep_001_analysis', 'REP-001', 'Reporting'),
        ('res_001_analysis', 'RES-001', 'Research'),
    ]

    for key, rule_id, desc in std_rules:
        data = analysis[key]
        count = data['count']
        pct = count / total * 100 if total > 0 else 0
        status = "✅" if count > 0 else "⚪"
        print(f"  {status} {rule_id:12} {count:4} ({pct:5.1f}%)  {desc}")

    # GOV-030 false negatives
    gov = analysis['gov_030_analysis']
    if gov['potential_false_negatives']:
        print(f"\n  ⚠️  GOV-030 POTENTIAL FALSE NEGATIVES: {len(gov['potential_false_negatives'])}")
        for p in gov['potential_false_negatives'][:5]:
            print(f"      [{p['score']:3}] {p['title'][:50]}")

    # OPS-050 false negatives
    ops = analysis['ops_050_analysis']
    if ops['potential_false_negatives']:
        print(f"\n  ⚠️  OPS-050 POTENTIAL FALSE NEGATIVES: {len(ops['potential_false_negatives'])}")
        print("      (Important proposals marked as operational)")
        for p in ops['potential_false_negatives'][:5]:
            print(f"      [{p['score']:3}] {p['title'][:50]}")
    else:
        print("\n  ✅ OPS-050: No obvious false negatives")

    # ========== PHASE 4: OVERRIDES ==========
    print("\n" + "="*80)
    print("🔄 PHASE 4: OVERRIDE RULES (Kill Switches)")
    print("="*80)

    override_stats = analysis['override_analysis']['by_override_rule']
    if override_stats:
        for rule, count in sorted(override_stats.items(), key=lambda x: -x[1]):
            pct = count / total * 100 if total > 0 else 0
            print(f"  {rule:30} {count:4} ({pct:5.1f}%)")

        high_prio = analysis['override_analysis']['high_priority_closed']
        if high_prio:
            print(f"\n  High-priority closed items (score >= 60): {len(high_prio)}")
            print("  ✅ Historical weight preserved correctly")
    else:
        print("  ⚪ No override rules fired")

    # ========== PHASE 5: DEFAULT ==========
    print("\n" + "="*80)
    print("⚪ PHASE 5: DEFAULT RULE (Uncategorized)")
    print("="*80)

    uncat = analysis['uncategorized']
    pct = uncat['count'] / total * 100 if total > 0 else 0

    if pct > 15:
        print(f"  🔴 DEFAULT-001: {uncat['count']} ({pct:.1f}%) - TOO HIGH!")
        print("     Recommendation: Add more keyword groups")
    elif pct > 10:
        print(f"  ⚠️  DEFAULT-001: {uncat['count']} ({pct:.1f}%) - Needs improvement")
    else:
        print(f"  ✅ DEFAULT-001: {uncat['count']} ({pct:.1f}%) - Acceptable")

    if verbose and uncat['proposals']:
        print("\n  Sample uncategorized:")
        for p in uncat['proposals'][:10]:
            print(f"      [{p['score']:3}] {p['title'][:60]}")

    # ========== RULES FIRING FREQUENCY ==========
    print("\n" + "="*80)
    print("📊 RULES FIRING FREQUENCY (Top 20)")
    print("="*80)
    sorted_rules = sorted(analysis['summary']['by_rule'].items(), key=lambda x: -x[1])
    for rule, count in sorted_rules[:20]:
        pct = count / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 5)
        print(f"  {rule:25} {count:4} ({pct:5.1f}%) {bar}")

    # Labels distribution
    print("\n" + "="*80)
    print("📏 LABELS DISTRIBUTION (Top 15)")
    print("="*80)
    sorted_labels = sorted(analysis['summary']['by_label'].items(), key=lambda x: -x[1])
    for label, count in sorted_labels[:15]:
        pct = count / total * 100
        print(f"  {label:30} {count:4} ({pct:5.1f}%)")

    # Recommendations
    print("\n" + "="*80)
    print("📋 RECOMMENDATIONS FOR RULEBOOK.YAML TUNING")
    print("="*80)

    total = analysis['summary']['total_proposals']
    issues_found = False

    # SEC-001 analysis
    sec_fp = len(analysis['sec_001_analysis']['potential_false_positives'])
    if sec_fp > 0:
        issues_found = True
        print(f"""
🔧 SEC-001-STRICT ({sec_fp} potential false positives):
   - Add exclusions (not_flag) for: CONTEXT_ELECTION, CONTEXT_HR
   - Check ACTIVE_INCIDENT_CUES keywords - may be too generic
   - Consider increasing keyword_group_hits threshold from gte:1 to gte:2
""")

    # TECH-001 analysis
    tech_fp = len(analysis['tech_001_analysis']['potential_false_positives'])
    if tech_fp > 0:
        issues_found = True
        print(f"""
🔧 TECH-001-STRICT ({tech_fp} potential false positives):
   - Some proposals may be incorrectly marked as protocol upgrade
   - Consider adding exclusions for: report, summary, election
""")

    # CTX-002 analysis
    ctx_issues = len(analysis['ctx_002_analysis']['potential_issues'])
    if ctx_issues > 0:
        issues_found = True
        print(f"""
🔧 CTX-002 Election Detection ({ctx_issues} potential misses):
   - Proposals with "election" in title are not being detected
   - Add more keywords to ELECTION_CUES
""")

    # GOV-030 analysis
    gov_fn = len(analysis['gov_030_analysis']['potential_false_negatives'])
    if gov_fn > 0:
        issues_found = True
        print(f"""
🔧 GOV-030 Constitutional ({gov_fn} potential false negatives):
   - Proposals with "constitutional" are not being detected
   - Check GOV_FRAMEWORK_CUES keywords
""")

    # OPS-050 analysis
    ops_fn = len(analysis['ops_050_analysis']['potential_false_negatives'])
    if ops_fn > 0:
        issues_found = True
        print(f"""
🔧 OPS-050 Operational ({ops_fn} potential false negatives):
   - Important proposals may be capped by max_priority=45
   - Consider increasing max_priority or adding exclusions
""")

    # Uncategorized analysis
    uncat_pct = analysis['uncategorized']['count'] / max(1, total) * 100
    if uncat_pct > 15:
        issues_found = True
        print(f"""
🔧 Coverage ({uncat_pct:.1f}% uncategorized - TARGET: <15%):
   - Analyze titles of UNCATEGORIZED proposals
   - Add new keyword groups for missing patterns
""")

    # Rules never fired
    all_expected_rules = [
        'CTX-001', 'CTX-002', 'CTX-003', 'CTX-004',
        'SEC-001-STRICT', 'TECH-001-STRICT', 'TECH-002',
        'PROG-001', 'TRE-010', 'TRE-021', 'GOV-030',
        'META-001', 'SPON-001', 'OPS-050', 'REP-001-STRICT', 'RES-001',
        'DEFAULT-001'
    ]
    fired_rules = set(analysis['summary']['by_rule'].keys())
    never_fired = [r for r in all_expected_rules if r not in fired_rules]

    if never_fired:
        issues_found = True
        print(f"""
⚠️  RULES NEVER FIRED: {', '.join(never_fired)}
   - These rules may have overly restrictive conditions
   - Or historical data does not contain matching proposals
""")

    if not issues_found:
        print("""
✅ ALL RULES VALIDATED SUCCESSFULLY
   - No significant false positives detected
   - No significant false negatives detected
   - Coverage is acceptable
""")

    print("\n" + "="*80)
    print("  END OF REPORT")
    print("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Ex Ante Validation of Rule Engine')
    parser.add_argument('--months', type=int, default=None,
                       help='Limit to last N months (default: all data)')
    parser.add_argument('--output', type=str, default=None,
                       help='Save JSON report to file')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed lists')
    parser.add_argument('--db', type=str, default='participation.db',
                       help='Path to SQLite database')
    parser.add_argument('--rulebook', type=str, default='rulebook.yaml',
                       help='Path to rulebook YAML')
    args = parser.parse_args()

    # Initialize engine
    print(f"Loading rulebook from: {args.rulebook}")
    engine = RuleEngine(args.rulebook)
    print(f"Rulebook version: {engine.version}")

    # Load proposals
    print(f"\nLoading proposals from: {args.db}")
    if args.months:
        print(f"Filtering to last {args.months} months")

    proposals_data = load_proposals_from_db(args.db, args.months)
    print(f"Loaded {len(proposals_data)} proposals")

    if not proposals_data:
        print("No proposals found. Exiting.")
        return

    # Evaluate all proposals
    print("\nEvaluating proposals...")
    results = []
    for i, row in enumerate(proposals_data):
        proposal = convert_to_proposal_input(row)
        result = engine.evaluate_proposal(proposal)

        results.append({
            'item_id': result.item_id,
            'title': row['title'],
            # Z10: stan propozycji musi wejsc do wyniku, inaczej nie da sie
            # policzyc, ile elementow korpusu W OGOLE moglo uruchomic regule
            # wymagajaca `not_flag: STATE_CLOSED`.
            'state': row['state'] or 'unknown',
            'priority_score': result.priority_score,
            'labels': result.labels,
            'reasons': result.reasons,
            'recommended_handling': result.recommended_handling,
            'explain': result.explain
        })

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(proposals_data)}...")

    print(f"Evaluation complete: {len(results)} proposals processed")

    # Analyze results
    analysis = analyze_results(results)

    # Print report
    print_report(analysis, verbose=args.verbose)

    # Save JSON if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump({
                'meta': {
                    'generated_at': datetime.now().isoformat(),
                    'rulebook_version': engine.version,
                    'proposals_count': len(results),
                    'months_filter': args.months
                },
                'analysis': analysis,
                'detailed_results': results if args.verbose else results[:50]
            }, f, indent=2, default=str)
        print(f"\n📄 JSON report saved to: {args.output}")


if __name__ == '__main__':
    main()
