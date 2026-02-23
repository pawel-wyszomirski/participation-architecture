/**
 * TypeScript Integration Example - Participation Architecture API
 * ===============================================================
 *
 * Demonstrates common integration patterns:
 *   - Health check
 *   - High-priority proposals feed
 *   - Delegate Fatigue Index with component breakdown
 *   - Status-based action routing
 *   - Notification bot integration pattern
 *
 * Requirements:
 *   No extra dependencies - uses native fetch (Node 18+ / browser)
 *
 * Usage:
 *   # Make sure the API is running first:
 *   # python3 -m uvicorn app.main:app --port 8000
 *
 *   # Compile and run with ts-node:
 *   npx ts-node docs/examples/typescript_example.ts
 *
 *   # Or compile manually:
 *   npx tsc docs/examples/typescript_example.ts && node docs/examples/typescript_example.js
 */

const BASE_URL = "http://localhost:8000";

interface HealthCheck {
  status: string;
  version: string;
  database: string;
  proposals_count: number;
  rule_engine: string;
  rulebook_version: string | null;
  fatigue_engine: string;
  fatigue_config_version: string | null;
}

interface ProposalMetadata {
  author: string;
  state: string;
  votes: number;
  scores_total: number;
  created_at: string;
  start_at: string;
  end_at: string;
}

interface ProposalTriage {
  id: string;
  title: string;
  priority_score: number;
  labels: string[];
  reasons: string[];
  recommended_handling: string;
  metadata: ProposalMetadata;
}

interface ProposalsFeedResponse {
  proposals: ProposalTriage[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
}

interface FatigueComponents {
  volume: number;
  concurrency: number;
  burstiness: number;
  reading_time: number;
  novelty: number;
}

interface FatigueMetrics {
  proposals_7d: number;
  proposals_30d: number;
  concurrent_active: number;
  avg_word_count: number;
  weekly_avg: number;
  novelty_ratio: number;
}

type FatigueStatus = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";

interface FatigueResponse {
  address: string;
  fatigue_score: number;
  status: FatigueStatus;
  components: FatigueComponents;
  metrics: FatigueMetrics;
  weights: FatigueComponents;
  config_version: string;
  computed_at: string;
  formula: string;
}

async function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.append(key, String(value));
    }
  }
  const resp = await fetch(url.toString());
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`HTTP ${resp.status} ${resp.statusText}: ${body}`);
  }
  return resp.json() as Promise<T>;
}

async function exampleHealthCheck(): Promise<HealthCheck> {
  console.log("\n--- Health Check ---");
  const health = await apiGet<HealthCheck>("/health");
  console.log(`  Status:           ${health.status}`);
  console.log(`  API version:      ${health.version}`);
  console.log(`  Database:         ${health.database}`);
  console.log(`  Proposals in DB:  ${health.proposals_count}`);
  console.log(`  Rule Engine:      ${health.rule_engine} (rulebook v${health.rulebook_version})`);
  console.log(`  Fatigue Engine:   ${health.fatigue_engine} (config v${health.fatigue_config_version})`);
  return health;
}

async function exampleProposalsFeed(minPriority: number = 80, label?: string): Promise<ProposalsFeedResponse> {
  const params: Record<string, string | number> = { min_priority: minPriority, limit: 20 };
  if (label) params.label = label;

  const description = label ? `min_priority=${minPriority}, label=${label}` : `min_priority=${minPriority}`;
  console.log(`\n--- Proposals Feed (${description}) ---`);

  const data = await apiGet<ProposalsFeedResponse>("/proposals/feed", params);
  console.log(`  Total in DB:   ${data.total}`);
  console.log(`  Returned:      ${data.proposals.length}`);
  console.log();

  for (const p of data.proposals) {
    console.log(`  [${String(p.priority_score).padStart(3)}] ${p.recommended_handling.padEnd(22)} ${p.title.slice(0, 55)}`);
    console.log(`         Labels: ${p.labels.join(", ")}`);
    console.log();
  }
  return data;
}

async function exampleDelegateFatigue(
  address: string = "0x0000000000000000000000000000000000000001"
): Promise<FatigueResponse> {
  console.log(`\n--- Delegate Fatigue Index ---`);
  const dfi = await apiGet<FatigueResponse>(`/delegates/${address}/fatigue`);

  console.log(`  Score:   ${dfi.fatigue_score.toFixed(1)} / 100`);
  console.log(`  Status:  ${dfi.status}`);
  console.log(`  Formula: ${dfi.formula}`);
  console.log();

  console.log("  Components (each 0.0-1.0):");
  for (const [name, value] of Object.entries(dfi.components) as [keyof FatigueComponents, number][]) {
    const weight = dfi.weights[name];
    const contribution = value * weight * 100;
    const bar = "=".repeat(Math.floor(value * 20));
    console.log(
      `    ${name.padEnd(15)} ${value.toFixed(3)}  (w=${weight.toFixed(2)}, contrib=${contribution.toFixed(1)})  [${bar.padEnd(20)}]`
    );
  }
  return dfi;
}

function exampleStatusRouting(dfi: FatigueResponse): void {
  console.log(`\n--- Status-based Action Routing ---`);
  const actions: Record<FatigueStatus, string[]> = {
    CRITICAL: [
      "Pause non-urgent proposals or batch them",
      "Extend voting windows if possible",
      "Alert delegates: high cognitive load period",
    ],
    HIGH: [
      "Prioritize triage: process deep_review items first",
      "Defer fast_track items if possible",
    ],
    MODERATE: ["Normal operation - all handling modes applicable"],
    LOW: ["Healthy load - process all item types"],
  };

  console.log(`  DFI = ${dfi.fatigue_score.toFixed(1)} (${dfi.status})`);
  console.log(`\n  Suggested actions for ${dfi.status}:`);
  for (const action of actions[dfi.status] ?? []) {
    console.log(`    - ${action}`);
  }
}

async function exampleNotificationBotPattern(): Promise<void> {
  console.log("\n--- Notification Bot Pattern ---");

  const dfi = await apiGet<FatigueResponse>("/delegates/0x0000000000000000000000000000000000000001/fatigue");
  const notifications: string[] = [];

  if (dfi.status === "CRITICAL") {
    notifications.push(
      `[CRITICAL] Governance overload: DFI = ${dfi.fatigue_score.toFixed(1)} ` +
      `(${dfi.metrics.concurrent_active} concurrent, ${dfi.metrics.proposals_7d} this week)`
    );
  }

  const feed = await apiGet<ProposalsFeedResponse>("/proposals/feed", {
    min_priority: 90,
    handling: "urgent_deep_review",
    status: "active",
    limit: 5,
  });

  for (const p of feed.proposals) {
    notifications.push(
      `[URGENT] ${p.title.slice(0, 60)} (score: ${p.priority_score}, rules: ${p.reasons.join(", ")})`
    );
  }

  if (notifications.length === 0) {
    console.log("  No notifications to send. All quiet.");
  } else {
    console.log(`  Would send ${notifications.length} notification(s):`);
    for (const n of notifications) console.log(`    > ${n}`);
  }
}

async function main(): Promise<void> {
  console.log("=".repeat(60));
  console.log("Participation Architecture API - TypeScript Integration Demo");
  console.log("=".repeat(60));

  try {
    await exampleHealthCheck();
  } catch (err) {
    console.error(`\nERROR: Could not connect to ${BASE_URL}`);
    console.error("Make sure the API is running:");
    console.error("  python3 -m uvicorn app.main:app --port 8000");
    process.exit(1);
  }

  await exampleProposalsFeed(80);
  const dfi = await exampleDelegateFatigue();
  exampleStatusRouting(dfi);
  await exampleNotificationBotPattern();

  console.log("\n" + "=".repeat(60));
  console.log("Done. Open http://localhost:8000/docs for interactive API explorer.");
  console.log("=".repeat(60));
}

main().catch(console.error);
