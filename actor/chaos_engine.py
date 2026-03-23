import docker
import subprocess
import json
import hmac
import hashlib
import time
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN_SECRET = "sentinel-secret-key"
LOG_FILE = "actor/injection_log.json"

# ── Docker client ─────────────────────────────────────────────────────────────
client = docker.from_env()


# ── Token verification ────────────────────────────────────────────────────────
def verify_token(token: str) -> bool:
    try:
        parts = token.rsplit(":", 1)
        payload = parts[0]
        signature = parts[1]
        expected = hmac.new(
            TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        timestamp = int(payload.split(":")[2])
        if time.time() - timestamp > 300:
            print("  [BLOCKED] Token expired")
            return False
        return hmac.compare_digest(signature, expected)
    except Exception as e:
        print(f"  [BLOCKED] Token verification failed: {e}")
        return False


# ── Logging ───────────────────────────────────────────────────────────────────
def log_injection(record: dict):
    try:
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except Exception:
            logs = []
        logs.append(record)
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Could not write log: {e}")


# ── Fault types ───────────────────────────────────────────────────────────────


def node_kill(target_node: str) -> dict:
    print(f"  [Actor] Executing node-kill on {target_node}...")
    try:
        container = client.containers.get(target_node)
        container.stop(timeout=5)
        print(f"  [Actor] ✅ {target_node} stopped successfully")
        return {"success": True, "action": f"stopped {target_node}"}
    except Exception as e:
        print(f"  [Actor] ❌ node-kill failed: {e}")
        return {"success": False, "error": str(e)}


def network_partition(target_node: str, duration_seconds: int = 30) -> dict:
    print(
        f"  [Actor] Executing network-partition on {target_node} for {duration_seconds}s..."
    )
    try:
        # Add network delay + packet loss to simulate partition
        cmd = [
            "docker",
            "exec",
            "--privileged",
            target_node,
            "tc",
            "qdisc",
            "add",
            "dev",
            "eth0",
            "root",
            "netem",
            "loss",
            "100%",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)
        print(f"  [Actor] ✅ Network partition applied to {target_node}")
        print(f"  [Actor] Will auto-heal in {duration_seconds}s")

        # Schedule auto-heal
        time.sleep(duration_seconds)
        heal_network(target_node)

        return {"success": True, "action": f"network partition on {target_node}"}
    except Exception as e:
        print(f"  [Actor] ❌ network-partition failed: {e}")
        print(f"  [Actor] Note: tc netem requires NET_ADMIN capability")
        return {"success": False, "error": str(e)}


def heal_network(target_node: str):
    print(f"  [Actor] Healing network on {target_node}...")
    cmd = [
        "docker",
        "exec",
        "--privileged",
        target_node,
        "tc",
        "qdisc",
        "del",
        "dev",
        "eth0",
        "root",
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    print(f"  [Actor] ✅ Network healed on {target_node}")


def cpu_stress(target_node: str, duration_seconds: int = 30) -> dict:
    print(f"  [Actor] Executing cpu-stress on {target_node} for {duration_seconds}s...")
    try:
        cmd = [
            "docker",
            "exec",
            "-d",
            target_node,
            "bash",
            "-c",
            f"apt-get install -y stress-ng -qq 2>/dev/null; stress-ng --cpu 2 --timeout {duration_seconds}s",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)
        print(
            f"  [Actor] ✅ CPU stress started on {target_node} for {duration_seconds}s"
        )
        return {"success": True, "action": f"cpu stress on {target_node}"}
    except Exception as e:
        print(f"  [Actor] ❌ cpu-stress failed: {e}")
        return {"success": False, "error": str(e)}


def disk_pressure(target_node: str, size_mb: int = 500) -> dict:
    print(f"  [Actor] Executing disk-pressure on {target_node} ({size_mb}MB)...")
    try:
        cmd = [
            "docker",
            "exec",
            target_node,
            "bash",
            "-c",
            f"dd if=/dev/zero of=/tmp/sentinel_fill bs=1M count={size_mb} 2>&1",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print(f"  [Actor] ✅ Disk pressure applied: {size_mb}MB written")
        return {
            "success": True,
            "action": f"disk pressure {size_mb}MB on {target_node}",
        }
    except Exception as e:
        print(f"  [Actor] ❌ disk-pressure failed: {e}")
        return {"success": False, "error": str(e)}


def heal_disk(target_node: str):
    print(f"  [Actor] Cleaning disk pressure on {target_node}...")
    subprocess.run(
        ["docker", "exec", target_node, "rm", "-f", "/tmp/sentinel_fill"],
        capture_output=True,
    )
    print(f"  [Actor] ✅ Disk pressure cleaned on {target_node}")


def latency_inject(
    target_node: str, delay_ms: int = 200, duration_seconds: int = 30
) -> dict:
    print(
        f"  [Actor] Injecting {delay_ms}ms latency on {target_node} for {duration_seconds}s..."
    )
    try:
        cmd = [
            "docker",
            "exec",
            "--privileged",
            target_node,
            "tc",
            "qdisc",
            "add",
            "dev",
            "eth0",
            "root",
            "netem",
            "delay",
            f"{delay_ms}ms",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)
        print(f"  [Actor] ✅ Latency injected on {target_node}")

        time.sleep(duration_seconds)
        heal_network(target_node)

        return {"success": True, "action": f"{delay_ms}ms latency on {target_node}"}
    except Exception as e:
        print(f"  [Actor] ❌ latency-inject failed: {e}")
        return {"success": False, "error": str(e)}


# ── Fault recovery ─────────────────────────────────────────────────────────────
def recover_node(target_node: str) -> dict:
    print(f"\n[Actor] Recovering {target_node}...")
    try:
        container = client.containers.get(target_node)
        if container.status != "running":
            container.start()
            print(f"  [Actor] ✅ {target_node} restarted")
            # Wait for node to rejoin
            time.sleep(15)
            return {"success": True, "action": f"restarted {target_node}"}
        else:
            print(f"  [Actor] {target_node} already running")
            return {"success": True, "action": "node already running"}
    except Exception as e:
        print(f"  [Actor] ❌ recovery failed: {e}")
        return {"success": False, "error": str(e)}


# ── Main executor ─────────────────────────────────────────────────────────────
FAULT_MAP = {
    "node-kill": node_kill,
    "network-partition": network_partition,
    "cpu-stress": cpu_stress,
    "disk-pressure": disk_pressure,
    "latency-inject": latency_inject,
}


def execute_fault(fault_type: str, target_node: str, token: str, **kwargs) -> dict:

    print("=" * 60)
    print(f"  CASSANDRA SENTINEL — ACTOR")
    print(f"  Fault type  : {fault_type}")
    print(f"  Target node : {target_node}")
    print(f"  Time        : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # Step 1 — verify token
    print("\n[Actor] Verifying signed token...")
    if not verify_token(token):
        print("  [BLOCKED] ❌ Invalid or expired token — injection refused")
        record = {
            "status": "BLOCKED",
            "fault_type": fault_type,
            "target_node": target_node,
            "reason": "invalid token",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        log_injection(record)
        return record

    print("  ✅ Token verified")

    # Step 2 — execute fault
    if fault_type not in FAULT_MAP:
        print(f"  [BLOCKED] ❌ Unknown fault type: {fault_type}")
        return {"status": "BLOCKED", "reason": f"unknown fault: {fault_type}"}

    start_time = time.time()
    result = FAULT_MAP[fault_type](target_node, **kwargs)
    duration = round(time.time() - start_time, 2)

    # Step 3 — log the injection
    record = {
        "status": "EXECUTED" if result["success"] else "FAILED",
        "fault_type": fault_type,
        "target_node": target_node,
        "result": result,
        "duration_s": duration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    log_injection(record)

    print(f"\n  Injection duration : {duration}s")
    print(f"  Status             : {record['status']}")

    return record


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from judge.preflight_engine import run_preflight

    print("\n" + "=" * 60)
    print("  FULL PIPELINE TEST — Judge → Actor")
    print("=" * 60)

    # Step 1 — run pre-flight
    preflight = run_preflight(
        fault_type="node-kill",
        target_node="cassandra-node3",
        target_replica_percentage=20,
    )

    if preflight["status"] != "APPROVED":
        print("\n❌ Pre-flight vetoed — Actor will not execute")
        exit(0)

    # Step 2 — execute fault with token
    print("\n[Pipeline] Pre-flight approved — handing token to Actor...")
    result = execute_fault(
        fault_type="node-kill", target_node="cassandra-node3", token=preflight["token"]
    )

    # Step 3 — verify node is down
    print("\n[Pipeline] Checking cluster state after fault...")
    time.sleep(5)
    subprocess.run(
        ["docker", "exec", "cassandra-node1", "nodetool", "status"],
        capture_output=False,
    )

    # Step 4 — recover node
    print("\n[Pipeline] Recovering node3...")
    recover_node("cassandra-node3")

    # Step 5 — verify recovery
    print("\n[Pipeline] Checking cluster state after recovery...")
    time.sleep(10)
    subprocess.run(
        ["docker", "exec", "cassandra-node1", "nodetool", "status"],
        capture_output=False,
    )

    print(f"\n✅ Full pipeline complete. Log saved to {LOG_FILE}")
