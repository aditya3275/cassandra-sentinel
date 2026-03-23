import requests
import subprocess
import json
import hashlib
import hmac
import time
import os
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
PROMETHEUS_URL = "http://localhost:9090"
OPA_POLICY = "judge/policies/preflight.rego"
TOKEN_SECRET = "sentinel-secret-key"  # in prod this would be an env secret


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
        print(f"  [WARN] Prometheus query failed: {promql} → {e}")
        return 0.0


def get_entropy_signals(target_replica_percentage: int = 20) -> dict:
    print("\n[Observer] Querying Prometheus for entropy signals...")

    signals = {
        "pending_compactions": query_prometheus(
            "sum(cassandra_table_pending_compactions)"
        ),
        "hints_in_progress": query_prometheus(
            "sum(cassandra_storage_hints_in_progress)"
        ),
        "nodes_down": query_prometheus(
            "count(up{job=~'cassandra-node.*'} == 0) or vector(0)"
        ),
        "target_replica_percentage": target_replica_percentage,
        "active_faults": 0,  # updated by Actor in Phase 3
    }

    print(f"  pending_compactions : {signals['pending_compactions']}")
    print(f"  hints_in_progress   : {signals['hints_in_progress']}")
    print(f"  nodes_down          : {signals['nodes_down']}")
    print(f"  target_replica_%    : {signals['target_replica_percentage']}")
    print(f"  active_faults       : {signals['active_faults']}")

    return signals


# ── OPA evaluation ────────────────────────────────────────────────────────────
def evaluate_opa(signals: dict) -> dict:
    print("\n[Judge] Evaluating entropy signals against OPA policies...")

    result = subprocess.run(
        ["opa", "eval", "-I", "-d", OPA_POLICY, "data.sentinel.preflight"],
        input=json.dumps(signals),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  [ERROR] OPA evaluation failed: {result.stderr}")
        return {"allow": False, "veto_reasons": ["OPA evaluation error"]}

    output = json.loads(result.stdout)
    decision = output["result"][0]["expressions"][0]["value"]
    return decision


# ── Signed Token ──────────────────────────────────────────────────────────────
def generate_token(fault_type: str, target_node: str) -> str:
    timestamp = str(int(time.time()))
    payload = f"{fault_type}:{target_node}:{timestamp}"
    signature = hmac.new(
        TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    token = f"{payload}:{signature}"
    return token


def verify_token(token: str) -> bool:
    try:
        parts = token.rsplit(":", 1)
        payload = parts[0]
        signature = parts[1]
        expected = hmac.new(
            TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        # token expires after 5 minutes
        timestamp = int(payload.split(":")[2])
        if time.time() - timestamp > 300:
            return False
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


# ── Main pre-flight check ─────────────────────────────────────────────────────
def run_preflight(
    fault_type: str, target_node: str, target_replica_percentage: int = 20
) -> dict:

    print("=" * 60)
    print(f"  CASSANDRA SENTINEL — PRE-FLIGHT CHECK")
    print(f"  Fault type  : {fault_type}")
    print(f"  Target node : {target_node}")
    print(f"  Time        : {datetime.utcnow().isoformat()}Z")
    print("=" * 60)

    # Step 1 — collect entropy signals from Prometheus
    signals = get_entropy_signals(target_replica_percentage)

    # Step 2 — evaluate against OPA policies
    decision = evaluate_opa(signals)

    # Step 3 — VETO or issue signed token
    if not decision["allow"]:
        print("\n[Judge] ❌ INJECTION VETOED")
        for reason in decision["veto_reasons"]:
            print(f"  → {reason}")
        return {
            "status": "VETOED",
            "reasons": decision["veto_reasons"],
            "token": None,
            "signals": signals,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # All checks passed — issue signed token
    token = generate_token(fault_type, target_node)
    print("\n[Judge] ✅ INJECTION APPROVED")
    print(f"  Signed token issued for {fault_type} on {target_node}")
    print(f"  Token: {token[:40]}...")

    return {
        "status": "APPROVED",
        "reasons": [],
        "token": token,
        "signals": signals,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test 1 — should pass (healthy cluster)
    print("\n>>> TEST 1 — Normal cluster (expect APPROVED)")
    result1 = run_preflight(
        fault_type="node-kill",
        target_node="cassandra-node2",
        target_replica_percentage=20,
    )
    print(f"\n  Final status: {result1['status']}")

    # Test 2 — verify the token
    if result1["token"]:
        valid = verify_token(result1["token"])
        print(f"  Token valid : {valid}")

    print("\n" + "─" * 60)

    # Test 2 — blast radius too high (should veto)
    print("\n>>> TEST 2 — Blast radius too high (expect VETOED)")
    result2 = run_preflight(
        fault_type="node-kill",
        target_node="cassandra-node2",
        target_replica_percentage=50,
    )
    print(f"\n  Final status: {result2['status']}")
