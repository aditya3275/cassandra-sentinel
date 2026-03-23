import requests
import json
import time
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
PROMETHEUS_URL = "http://localhost:9090"
LOG_FILE = "actor/injection_log.json"
SCORE_FILE = "quantifier/score_history.json"
HEAL_THRESHOLD = 0.6

# Score weights — must sum to 1.0
W1_MTTR = 0.30
W2_BLAST_RADIUS = 0.25
W3_SLO = 0.25
W4_RECOVERY_COST = 0.20


# ── Prometheus helpers ────────────────────────────────────────────────────────
def query_prometheus(promql: str) -> float:
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=5
        )
        r.raise_for_status()
        results = r.json()["data"]["result"]
        if not results:
            return 0.0
        return float(results[0]["value"][1])
    except Exception as e:
        print(f"  [WARN] Prometheus query failed: {e}")
        return 0.0


def query_prometheus_range(
    promql: str, start: float, end: float, step: str = "15s"
) -> list:
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": promql, "start": start, "end": end, "step": step},
            timeout=5,
        )
        r.raise_for_status()
        results = r.json()["data"]["result"]
        if not results:
            return []
        return results[0]["values"]
    except Exception as e:
        print(f"  [WARN] Prometheus range query failed: {e}")
        return []


# ── Metric collectors ─────────────────────────────────────────────────────────
def measure_mttr(injection_time: float, target_node: str) -> float:
    print(f"  [Quantifier] Measuring MTTR for {target_node}...")
    # Poll nodetool status via Prometheus until node is back UN
    # We measure time from injection to node showing UP in Prometheus
    check_interval = 5
    max_wait = 300  # 5 minutes max
    elapsed = 0

    while elapsed < max_wait:
        nodes_down = query_prometheus(
            "count(up{job=~'cassandra-node.*'} == 0) or vector(0)"
        )
        if nodes_down == 0:
            mttr = elapsed if elapsed > 0 else 10
            print(f"  [Quantifier] MTTR = {mttr}s")
            return float(mttr)
        time.sleep(check_interval)
        elapsed += check_interval

    print(f"  [Quantifier] MTTR = {max_wait}s (timeout)")
    return float(max_wait)


def measure_blast_radius(injection_time: float, window_seconds: int = 60) -> float:
    print(f"  [Quantifier] Measuring blast radius...")
    # Count how many nodes showed elevated error rates during fault
    end = injection_time + window_seconds
    start = injection_time

    unavailables = query_prometheus_range(
        "sum(increase(cassandra_client_request_unavailables[1m]))", start, end
    )

    if not unavailables:
        blast = 1.0
    else:
        values = [float(v[1]) for v in unavailables]
        max_val = max(values) if values else 0
        # normalize — 1 node affected = 1, 3 nodes = 3
        blast = min(max(max_val / 10, 1.0), 3.0)

    print(f"  [Quantifier] Blast radius = {blast} nodes affected")
    return blast


def measure_slo_compliance(
    injection_time: float, window_seconds: int = 60, slo_latency_ms: float = 100.0
) -> float:
    print(f"  [Quantifier] Measuring SLO compliance...")
    end = injection_time + window_seconds
    start = injection_time

    # Get p99 read latency during fault window
    latency_values = query_prometheus_range(
        "cassandra_client_read_latency{quantile='0.99'}", start, end
    )

    if not latency_values:
        print(f"  [Quantifier] No latency data — assuming 80% SLO compliance")
        return 0.80

    values = [float(v[1]) for v in latency_values]
    # latency from JMX is in microseconds — convert to ms
    values_ms = [v / 1000 for v in values]
    within_slo = sum(1 for v in values_ms if v <= slo_latency_ms)
    compliance = within_slo / len(values_ms) if values_ms else 0.8

    print(f"  [Quantifier] SLO compliance = {compliance:.2%}")
    return round(compliance, 4)


def measure_recovery_cost(recovery_time: float, window_seconds: int = 120) -> float:
    print(f"  [Quantifier] Measuring recovery cost (★ novel metric)...")
    end = recovery_time + window_seconds
    start = recovery_time

    # Compaction overhead post-recovery
    compaction_values = query_prometheus_range(
        "sum(cassandra_table_pending_compactions)", start, end
    )

    # Hinted handoff drain time
    hints_values = query_prometheus_range(
        "sum(cassandra_storage_hints_in_progress)", start, end
    )

    compaction_cost = 0.0
    hints_cost = 0.0

    if compaction_values:
        vals = [float(v[1]) for v in compaction_values]
        compaction_cost = sum(vals) * 15  # each scrape = 15s window

    if hints_values:
        vals = [float(v[1]) for v in hints_values]
        hints_cost = sum(vals) * 15

    total_cost = compaction_cost + hints_cost
    # normalize to seconds — minimum 1 to avoid division by zero
    total_cost = max(total_cost, 1.0)

    print(f"  [Quantifier] Compaction cost : {compaction_cost:.1f}s")
    print(f"  [Quantifier] Hints drain cost: {hints_cost:.1f}s")
    print(f"  [Quantifier] Total recovery cost = {total_cost:.1f}s")
    return total_cost


# ── Score formula ─────────────────────────────────────────────────────────────
def compute_score(
    mttr: float, blast_radius: float, slo_compliance: float, recovery_cost: float
) -> float:

    # Normalize each component to 0-1 range
    # MTTR: 10s = perfect (1.0), 300s = terrible (0.033)
    mttr_score = min(10.0 / max(mttr, 1.0), 1.0)

    # Blast radius: 1 node = perfect (1.0), 3 nodes = terrible (0.33)
    blast_score = min(1.0 / max(blast_radius, 1.0), 1.0)

    # SLO: already 0-1
    slo_score = slo_compliance

    # Recovery cost: 1s = perfect (1.0), 300s = terrible (0.003)
    cost_score = min(10.0 / max(recovery_cost, 1.0), 1.0)

    # Weighted sum
    score = (
        W1_MTTR * mttr_score
        + W2_BLAST_RADIUS * blast_score
        + W3_SLO * slo_score
        + W4_RECOVERY_COST * cost_score
    )

    return round(score, 4)


# ── Save score ────────────────────────────────────────────────────────────────
def save_score(record: dict):
    try:
        try:
            with open(SCORE_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []
        history.append(record)
        with open(SCORE_FILE, "w") as f:
            json.dump(history, f, indent=2)
        print(f"  [Quantifier] Score saved to {SCORE_FILE}")
    except Exception as e:
        print(f"  [WARN] Could not save score: {e}")


def load_score_history() -> list:
    try:
        with open(SCORE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


# ── Main scorer ───────────────────────────────────────────────────────────────
def run_scoring(
    fault_type: str, target_node: str, injection_time: float, recovery_time: float
) -> dict:

    print("\n" + "=" * 60)
    print(f"  CASSANDRA SENTINEL — QUANTIFIER")
    print(f"  Fault type  : {fault_type}")
    print(f"  Target node : {target_node}")
    print(f"  Time        : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    print("\n[Quantifier] Computing resilience score...")

    # Collect all 4 components
    mttr = measure_mttr(injection_time, target_node)
    blast_radius = measure_blast_radius(injection_time)
    slo_compliance = measure_slo_compliance(injection_time)
    recovery_cost = measure_recovery_cost(recovery_time)

    # Compute final score
    score = compute_score(mttr, blast_radius, slo_compliance, recovery_cost)

    print(f"\n[Quantifier] ── Score Breakdown ──────────────────────")
    print(f"  MTTR            : {mttr}s")
    print(f"  Blast radius    : {blast_radius} nodes")
    print(f"  SLO compliance  : {slo_compliance:.2%}")
    print(f"  Recovery cost   : {recovery_cost:.1f}s")
    print(f"  ──────────────────────────────────────────────────")
    print(f"  RESILIENCE SCORE: {score}")

    if score >= HEAL_THRESHOLD:
        verdict = "HEALTHY"
        print(f"  VERDICT         : ✅ {verdict} (score ≥ {HEAL_THRESHOLD})")
    else:
        verdict = "NEEDS HEALING"
        print(f"  VERDICT         : ❌ {verdict} (score < {HEAL_THRESHOLD})")

    # Build record
    record = {
        "fault_type": fault_type,
        "target_node": target_node,
        "score": score,
        "verdict": verdict,
        "components": {
            "mttr_seconds": mttr,
            "blast_radius": blast_radius,
            "slo_compliance": slo_compliance,
            "recovery_cost_s": recovery_cost,
        },
        "weights": {
            "w1_mttr": W1_MTTR,
            "w2_blast_radius": W2_BLAST_RADIUS,
            "w3_slo": W3_SLO,
            "w4_recovery_cost": W4_RECOVERY_COST,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    save_score(record)
    return record


# ── Trend report ──────────────────────────────────────────────────────────────
def print_trend():
    history = load_score_history()
    if not history:
        print("No score history yet.")
        return

    print("\n[Quantifier] ── Resilience Score Trend ───────────────")
    for i, r in enumerate(history):
        bar_len = int(r["score"] * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)
        verdict = "✅" if r["score"] >= HEAL_THRESHOLD else "❌"
        print(
            f"  #{i+1} [{bar}] {r['score']} {verdict} {r['fault_type']} → {r['target_node']}"
        )
    print()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from judge.preflight_engine import run_preflight
    from actor.chaos_engine import execute_fault, recover_node

    print("\n" + "=" * 60)
    print("  FULL PIPELINE — Judge → Actor → Quantifier")
    print("=" * 60)

    # Step 1 — pre-flight
    preflight = run_preflight(
        fault_type="node-kill",
        target_node="cassandra-node3",
        target_replica_percentage=20,
    )

    if preflight["status"] != "APPROVED":
        print("\n❌ Pre-flight vetoed — pipeline stopped")
        exit(0)

    # Step 2 — inject fault
    injection_time = time.time()
    result = execute_fault(
        fault_type="node-kill", target_node="cassandra-node3", token=preflight["token"]
    )

    # Step 3 — wait and recover
    print("\n[Pipeline] Waiting 15s before recovery...")
    time.sleep(15)

    recovery_time = time.time()
    recover_node("cassandra-node3")

    # Step 4 — score
    print("\n[Pipeline] Waiting 30s for metrics to stabilize...")
    time.sleep(30)

    score_record = run_scoring(
        fault_type="node-kill",
        target_node="cassandra-node3",
        injection_time=injection_time,
        recovery_time=recovery_time,
    )

    # Step 5 — trend
    print_trend()

    # Step 6 — healer decision
    print("\n[Pipeline] Healer decision:")
    if score_record["score"] < HEAL_THRESHOLD:
        print(f"  ❌ Score {score_record['score']} < {HEAL_THRESHOLD}")
        print(f"  → Triggering Healer (Phase 5)")
    else:
        print(f"  ✅ Score {score_record['score']} ≥ {HEAL_THRESHOLD}")
        print(f"  → Cluster healthy, no healing needed")
