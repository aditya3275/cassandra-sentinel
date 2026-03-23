import sys
import time
import json
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, ".")
from judge.preflight_engine import run_preflight
from actor.chaos_engine import execute_fault, recover_node
from quantifier.quantifier import run_scoring, load_score_history, print_trend
from healer.healer import run_healer, detect_drift, load_gold_standard

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Cassandra Sentinel API",
    description="Policy-Gated Entropy-Aware Fault Tolerance Platform",
    version="1.0.0",
)


# ── Request models ────────────────────────────────────────────────────────────
class ExperimentRequest(BaseModel):
    fault_type: str
    target_node: str
    target_replica_percentage: Optional[int] = 20
    auto_recover: Optional[bool] = True
    auto_heal: Optional[bool] = True


# ── Log helpers ───────────────────────────────────────────────────────────────
def load_json(path: str) -> list:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/")
def root():
    return {
        "name": "Cassandra Sentinel",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoints": [
            "GET  /status",
            "GET  /scores",
            "GET  /heals",
            "GET  /vetoes",
            "POST /experiment",
        ],
    }


@app.get("/status")
def get_status():
    import docker
    import requests as req

    client = docker.from_env()
    nodes = {}
    overall = "HEALTHY"

    for node_name in ["cassandra-node1", "cassandra-node2", "cassandra-node3"]:
        try:
            container = client.containers.get(node_name)
            nodes[node_name] = container.status.upper()
            if container.status != "running":
                overall = "DEGRADED"
        except Exception:
            nodes[node_name] = "MISSING"
            overall = "DEGRADED"

    # Get latest resilience score
    history = load_score_history()
    last_score = history[-1]["score"] if history else None

    # Get entropy signals
    def prom_query(q):
        try:
            r = req.get(
                "http://localhost:9090/api/v1/query", params={"query": q}, timeout=5
            )
            results = r.json()["data"]["result"]
            return float(results[0]["value"][1]) if results else 0.0
        except Exception:
            return 0.0

    return {
        "overall": overall,
        "nodes": nodes,
        "last_resilience_score": last_score,
        "entropy_signals": {
            "pending_compactions": prom_query(
                "sum(cassandra_table_pending_compactions)"
            ),
            "hints_in_progress": prom_query("sum(cassandra_storage_hints_in_progress)"),
            "nodes_down": prom_query(
                "count(up{job=~'cassandra-node.*'} == 0) or vector(0)"
            ),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/scores")
def get_scores():
    history = load_score_history()
    if not history:
        return {"scores": [], "total": 0, "message": "No experiments run yet"}
    return {
        "scores": history,
        "total": len(history),
        "latest_score": history[-1]["score"],
        "average": round(sum(r["score"] for r in history) / len(history), 4),
        "min": min(r["score"] for r in history),
        "max": max(r["score"] for r in history),
    }


@app.get("/heals")
def get_heals():
    heals = load_json("healer/heal_log.json")
    if not heals:
        return {"heals": [], "total": 0, "message": "No healing events yet"}
    return {"heals": heals, "total": len(heals)}


@app.get("/vetoes")
def get_vetoes():
    injections = load_json("actor/injection_log.json")
    vetoes = [i for i in injections if i.get("status") == "BLOCKED"]
    return {"vetoes": vetoes, "total": len(vetoes)}


@app.get("/injections")
def get_injections():
    injections = load_json("actor/injection_log.json")
    return {"injections": injections, "total": len(injections)}


@app.post("/experiment")
def run_experiment(req: ExperimentRequest):

    valid_faults = [
        "node-kill",
        "network-partition",
        "cpu-stress",
        "disk-pressure",
        "latency-inject",
    ]
    valid_nodes = ["cassandra-node1", "cassandra-node2", "cassandra-node3"]

    if req.fault_type not in valid_faults:
        raise HTTPException(
            status_code=400, detail=f"Invalid fault_type. Choose from: {valid_faults}"
        )

    if req.target_node not in valid_nodes:
        raise HTTPException(
            status_code=400, detail=f"Invalid target_node. Choose from: {valid_nodes}"
        )

    experiment_id = f"exp-{int(time.time())}"
    result = {
        "experiment_id": experiment_id,
        "fault_type": req.fault_type,
        "target_node": req.target_node,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Step 1 — pre-flight
    preflight = run_preflight(
        fault_type=req.fault_type,
        target_node=req.target_node,
        target_replica_percentage=req.target_replica_percentage,
    )
    result["preflight"] = {
        "status": preflight["status"],
        "reasons": preflight.get("reasons", []),
        "signals": preflight.get("signals", {}),
    }

    if preflight["status"] != "APPROVED":
        result["outcome"] = "VETOED"
        return result

    # Step 2 — inject fault
    injection_time = time.time()
    fault_result = execute_fault(
        fault_type=req.fault_type, target_node=req.target_node, token=preflight["token"]
    )
    result["injection"] = fault_result

    if not fault_result.get("result", {}).get("success", False):
        result["outcome"] = "INJECTION_FAILED"
        return result

    # Step 3 — recover
    recovery_time = injection_time
    if req.auto_recover and req.fault_type == "node-kill":
        print(f"[API] Waiting 15s before recovery...")
        time.sleep(15)
        recovery_time = time.time()
        recover_result = recover_node(req.target_node)
        result["recovery"] = recover_result
        print(f"[API] Waiting 30s for metrics to stabilize...")
        time.sleep(30)

    # Step 4 — score
    score_record = run_scoring(
        fault_type=req.fault_type,
        target_node=req.target_node,
        injection_time=injection_time,
        recovery_time=recovery_time,
    )
    result["resilience_score"] = score_record

    # Step 5 — heal if needed
    result["healing"] = None
    if req.auto_heal and score_record["score"] < 0.6:
        heal_record = run_healer(
            score=score_record["score"],
            fault_type=req.fault_type,
            target_node=req.target_node,
        )
        result["healing"] = heal_record

    result["outcome"] = "COMPLETE"
    return result
