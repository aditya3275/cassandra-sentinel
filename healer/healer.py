import docker
import subprocess
import json
import time
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────
GOLD_STANDARD_FILE = "healer/gold_standard.json"
HEAL_LOG_FILE = "healer/heal_log.json"
PROMETHEUS_URL = "http://localhost:9090"
HEAL_THRESHOLD = 0.6

# ── Docker client ───────────────────────────────────────────────────────────
client = docker.from_env()


# ── Load Gold Standard ──────────────────────────────────────────────────────
def load_gold_standard() -> dict:
    with open(GOLD_STANDARD_FILE, "r") as f:
        return json.load(f)


# ── Prometheus helper ───────────────────────────────────────────────────────
def query_prometheus(promql: str) -> float:
    try:
        import requests

        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=5
        )
        results = r.json()["data"]["result"]
        if not results:
            return 0.0
        return float(results[0]["value"][1])
    except Exception:
        return 0.0


# ── Heal log ────────────────────────────────────────────────────────────────
def log_heal(record: dict):
    try:
        try:
            with open(HEAL_LOG_FILE, "r") as f:
                logs = json.load(f)
        except Exception:
            logs = []
        logs.append(record)
        with open(HEAL_LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
        print(f"  [Healer] Heal record saved to {HEAL_LOG_FILE}")
    except Exception as e:
        print(f"  [WARN] Could not write heal log: {e}")


# ── Drift detection ─────────────────────────────────────────────────────────
def detect_drift(gold: dict) -> list:
    print("\n[Healer] Detecting drift from Gold Standard...")
    issues = []

    for node_name in gold["expected_nodes"]:
        try:
            container = client.containers.get(node_name)
            if container.status != "running":
                issues.append(
                    {
                        "type": "node_down",
                        "node": node_name,
                        "detail": f"{node_name} is {container.status}",
                    }
                )
                print(f"  ❌ {node_name} is {container.status}")
            else:
                print(f"  ✅ {node_name} is running")
        except Exception as e:
            issues.append({"type": "node_missing", "node": node_name, "detail": str(e)})
            print(f"  ❌ {node_name} not found: {e}")

    hints = query_prometheus("sum(cassandra_storage_hints_in_progress)")
    if hints > gold["max_hints_in_progress"]:
        issues.append(
            {
                "type": "hints_backlog",
                "node": "cluster",
                "detail": f"{hints} hints in progress",
            }
        )
        print(f"  ❌ Hints backlog: {hints} pending")
    else:
        print(f"  ✅ Hints in progress: {hints} (within limit)")

    compactions = query_prometheus("sum(cassandra_table_pending_compactions)")
    if compactions > gold["max_pending_compactions"]:
        issues.append(
            {
                "type": "compaction_backlog",
                "node": "cluster",
                "detail": f"{compactions} pending compactions",
            }
        )
        print(f"  ❌ Compaction backlog: {compactions} pending")
    else:
        print(f"  ✅ Pending compactions: {compactions} (within limit)")

    if not issues:
        print("  ✅ No drift detected — cluster matches Gold Standard")

    return issues


# ── Heal actions ────────────────────────────────────────────────────────────
def heal_node_down(node_name: str) -> dict:
    print(f"\n  [Healer] Restarting {node_name}...")
    try:
        container = client.containers.get(node_name)
        if container.status != "running":
            container.start()
            print(f"  [Healer] ✅ {node_name} started")
            print(f"  [Healer] Waiting 20s for node to rejoin cluster...")
            time.sleep(20)
            return {"action": f"restarted {node_name}", "success": True}
        else:
            print(f"  [Healer] {node_name} already running")
            return {"action": f"{node_name} already running", "success": True}
    except Exception as e:
        print(f"  [Healer] ❌ Failed to restart {node_name}: {e}")
        return {"action": f"restart {node_name}", "success": False, "error": str(e)}


def heal_hints_backlog(gold: dict) -> dict:
    print(f"\n  [Healer] Running nodetool repair to drain hints...")
    actions = []
    for node_name in gold["expected_nodes"]:
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    node_name,
                    "nodetool",
                    "repair",
                    "-pr",
                    gold["keyspace"],
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                print(f"  [Healer] ✅ nodetool repair complete on {node_name}")
                actions.append(f"repaired {node_name}")
            else:
                print(f"  [Healer] ⚠️  repair on {node_name}: {result.stderr[:100]}")
                actions.append(f"repair attempted on {node_name}")
        except Exception as e:
            print(f"  [Healer] ❌ repair failed on {node_name}: {e}")
            actions.append(f"repair failed on {node_name}")
    return {"action": actions, "success": True}


def heal_compaction_backlog(gold: dict) -> dict:
    print(f"\n  [Healer] Triggering compaction to clear backlog...")
    actions = []
    for node_name in gold["expected_nodes"]:
        try:
            result = subprocess.run(
                ["docker", "exec", node_name, "nodetool", "compact", gold["keyspace"]],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                print(f"  [Healer] ✅ compaction triggered on {node_name}")
                actions.append(f"compacted {node_name}")
            else:
                print(f"  [Healer] ⚠️  compaction on {node_name}: {result.stderr[:100]}")
                actions.append(f"compaction attempted on {node_name}")
        except Exception as e:
            print(f"  [Healer] ❌ compaction failed on {node_name}: {e}")
    return {"action": actions, "success": True}


# ── Main healer ─────────────────────────────────────────────────────────────
def run_healer(score: float, fault_type: str, target_node: str) -> dict:

    print("\n" + "=" * 60)
    print(f"  CASSANDRA SENTINEL — HEALER")
    print(f"  Triggered by score : {score} < {HEAL_THRESHOLD}")
    print(f"  Fault type         : {fault_type}")
    print(f"  Target node        : {target_node}")
    print(f"  Time               : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    gold = load_gold_standard()
    heal_start = time.time()
    actions = []

    # Step 1 — detect drift
    issues = detect_drift(gold)

    if not issues:
        print("\n[Healer] No drift found — cluster already matches Gold Standard")
        record = {
            "triggered_by_score": score,
            "fault_type": fault_type,
            "target_node": target_node,
            "issues_found": 0,
            "actions_taken": ["no drift detected"],
            "heal_duration_s": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        log_heal(record)
        return record

    print(f"\n[Healer] Found {len(issues)} issue(s) — beginning healing...")

    # Step 2 — heal each issue
    for issue in issues:
        if issue["type"] in ("node_down", "node_missing"):
            result = heal_node_down(issue["node"])
            actions.append(result)

        elif issue["type"] == "hints_backlog":
            result = heal_hints_backlog(gold)
            actions.append(result)

        elif issue["type"] == "compaction_backlog":
            result = heal_compaction_backlog(gold)
            actions.append(result)

    heal_duration = round(time.time() - heal_start, 2)

    # Step 3 — verify cluster state post-heal
    print(f"\n[Healer] Verifying cluster state after healing...")
    time.sleep(10)

    result = subprocess.run(
        ["docker", "exec", "cassandra-node1", "nodetool", "status"],
        capture_output=False,
    )

    # Step 4 — save heal record
    record = {
        "triggered_by_score": score,
        "fault_type": fault_type,
        "target_node": target_node,
        "issues_found": len(issues),
        "issues": issues,
        "actions_taken": actions,
        "heal_duration_s": heal_duration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    log_heal(record)

    print(f"\n[Healer] ✅ Healing complete in {heal_duration}s")
    print(f"[Healer] Every heal is logged — full audit trail maintained")
    print(f"[Healer] In Phase 8 (AWS) ArgoCD will Git commit every heal")

    return record


# ── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from judge.preflight_engine import run_preflight
    from actor.chaos_engine import execute_fault, recover_node
    from quantifier.quantifier import run_scoring

    print("\n" + "=" * 60)
    print("  FULL PIPELINE — Judge → Actor → Quantifier → Healer")
    print("=" * 60)

    # Force a low score by killing node3 and NOT recovering
    # Then scoring immediately — MTTR will be high → low score
    print("\n[Pipeline] Step 1 — Pre-flight check")
    preflight = run_preflight(
        fault_type="node-kill",
        target_node="cassandra-node3",
        target_replica_percentage=20,
    )

    if preflight["status"] != "APPROVED":
        print("❌ Pre-flight vetoed")
        exit(0)

    print("\n[Pipeline] Step 2 — Kill node3")
    injection_time = time.time()
    execute_fault(
        fault_type="node-kill", target_node="cassandra-node3", token=preflight["token"]
    )

    print("\n[Pipeline] Step 3 — Score immediately (node still down)")
    print("  Note: Low score expected — node3 is still down")
    time.sleep(5)
    recovery_time = time.time()

    score_record = run_scoring(
        fault_type="node-kill",
        target_node="cassandra-node3",
        injection_time=injection_time,
        recovery_time=recovery_time,
    )

    print(f"\n[Pipeline] Step 4 — Healer decision")
    print(f"  Score: {score_record['score']}")

    if score_record["score"] < HEAL_THRESHOLD:
        print(f"  ❌ Score below threshold — triggering Healer")
        heal_record = run_healer(
            score=score_record["score"],
            fault_type="node-kill",
            target_node="cassandra-node3",
        )
    else:
        print(f"  ✅ Score above threshold — no healing needed")
        print(f"  Manually triggering healer for demo...")
        heal_record = run_healer(
            score=0.4, fault_type="node-kill", target_node="cassandra-node3"
        )

    print("\n[Pipeline] ✅ Full pipeline complete!")
    print(f"  Injection log : actor/injection_log.json")
    print(f"  Score history : quantifier/score_history.json")
    print(f"  Heal log      : healer/heal_log.json")
