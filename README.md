# Cassandra Sentinel 🛡️

> A Policy-Gated, Entropy-Aware Observability and Self-Healing Platform for Apache Cassandra

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![Cassandra](https://img.shields.io/badge/Cassandra-4.1-blue.svg)](https://cassandra.apache.org)
[![OPA](https://img.shields.io/badge/OPA-1.13-purple.svg)](https://openpolicyagent.org)
[![Prometheus](https://img.shields.io/badge/Prometheus-latest-orange.svg)](https://prometheus.io)
[![Grafana](https://img.shields.io/badge/Grafana-latest-orange.svg)](https://grafana.com)
[![Terraform](https://img.shields.io/badge/Terraform-1.14-purple.svg)](https://terraform.io)
[![License](https://img.shields.io/badge/License-Research--Only-red.svg)](LICENSE)

---

## What is Cassandra Sentinel?

Cassandra Sentinel is a chaos engineering and observability platform built
specifically for Apache Cassandra. It solves three critical gaps in existing
chaos engineering tools like Chaos Mesh and LitmusChaos:

| Problem | How Cassandra Sentinel Solves It |
|---|---|
| Blind fault injection | OPA pre-flight entropy veto checks cluster state before every injection |
| No resilience quantification | Novel cost-of-recovery scoring formula captures post-fault operational burden |
| No self-healing loop | ArgoCD GitOps sync restores cluster to Gold Standard automatically |

---

## Architecture
```
Cassandra Cluster (3 nodes · RF=3 · NetworkTopologyStrategy)
        │
        ▼
[Observer] Prometheus + jmx_exporter
SSTable count · Hinted Handoff · Disk · Compaction · Latency
        │
        ▼
[Judge] OPA Pre-Flight Engine
Entropy signals → VETO or Signed Token
        │
        ▼ (Signed Token)
[Actor] Chaos Engine
Node kill · Network partition · CPU stress · Disk pressure · Latency
        │
        ▼
[Quantifier] Resilience Scoring Engine
score = w1×(1/MTTR) + w2×(1/blast_radius) + w3×SLO + w4×(1/recovery_cost)
        │
        ▼ (score < 0.6)
[Healer] GitOps Self-Healing
Gold Standard sync · nodetool repair · pod restart
        │
        ▼
[Dashboard] Grafana
Node health · Resilience trend · OPA veto log
```

---

## ⚠️ Note on Missing Files

Two files are intentionally not included in this repository:
```
quantifier/quantifier.py       ← withheld
judge/policies/preflight.rego  ← withheld
```

These files contain the core novel contributions of this project:

1. **The resilience scoring formula** — including the cost-of-recovery
   metric which is the primary research contribution. This formula
   captures compaction overhead and hinted handoff drain time
   post-recovery — a metric that does not exist in any existing
   chaos engineering platform or academic paper.

2. **The entropy-aware OPA veto policies** — the pre-flight evaluation
   logic that reads real-time Cassandra entropy signals and vetoes
   unsafe injections before they execute.

These are withheld because this project is the reference implementation
for a research paper currently in preparation:

> **"Entropy-Aware Pre-Flight Veto for Policy-Gated Chaos Engineering
> in Distributed Database Clusters"**
> — Muthyala Aditya, SRM IST Kattankulathur (2026)

Once the paper is submitted to arXiv, both files will be made public
and this repository will be updated with the paper DOI.

**For academic review, collaboration, or interview purposes:**
Contact → [your email here]

---

## Novel Contributions

### 1. Entropy-Aware Pre-Flight Veto
No existing chaos platform checks cluster entropy state before injecting.
Cassandra Sentinel reads real-time stress signals (SSTable count, hinted
handoff lag, compaction status) and vetoes unsafe injections — preventing
cascading failures during chaos experiments.

### 2. Signed Token Handshake
The Judge issues a cryptographically signed HMAC-SHA256 token that the Actor
must present to execute. Every injection is authorized, scoped, and auditable.
Tokens expire after 5 minutes and are scoped to one fault on one node.

### 3. Cost-of-Recovery Metric ★ (withheld pending paper)
```
score = w1×(1/MTTR)
      + w2×(1/blast_radius)
      + w3×SLO_compliance
      + w4×(1/recovery_cost)

recovery_cost = compaction_overhead + hinted_handoff_drain_time
```
No existing resilience metric captures the operational burden of recovery.
MTTR tells you when the cluster came back. Recovery cost tells you what it took.
This is the novel contribution. Full derivation in the paper.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Database | Apache Cassandra 4.1 (3 nodes, RF=3) |
| Infra Provisioning | Terraform (AWS EC2, VPC, IAM) |
| Metrics Collection | Prometheus + jmx_exporter |
| Policy Engine | OPA (Open Policy Agent) |
| Chaos Execution | Python + stress-ng + tc netem |
| Resilience Scoring | Python (formula withheld) |
| Visualization | Grafana |
| REST API | FastAPI |
| Container Runtime | Docker Compose (local) / AWS EC2 (production) |

---

## Project Structure
```
cassandra-sentinel/
├── docker-compose.yml          # 3-node Cassandra + Prometheus + Grafana
├── prometheus.yml              # Prometheus scrape config
├── jmx/
│   └── cassandra-jmx-config.yml  # JMX metric collection rules
├── judge/
│   ├── policies/
│   │   └── preflight.rego      # ⚠️ withheld — see Note on Missing Files
│   └── preflight_engine.py     # Pre-flight engine + signed token
├── actor/
│   └── chaos_engine.py         # Fault injection engine
├── quantifier/
│   └── quantifier.py           # ⚠️ withheld — see Note on Missing Files
├── healer/
│   ├── gold_standard.json      # Desired cluster state
│   └── healer.py               # Self-healing engine
├── grafana/
│   └── provisioning/           # Auto-provisioned dashboards
├── api/
│   └── main.py                 # FastAPI REST interface
├── terraform/
│   ├── main.tf                 # AWS infrastructure
│   ├── variables.tf
│   └── outputs.tf
└── docs/
    └── concept.md              # Architecture flowchart
```

---

## Quick Start (Local)

### Prerequisites
- Docker Desktop
- Python 3.9+
- OPA CLI (`brew install opa`)

### 1. Start the cluster
```bash
docker compose up -d
```

### 2. Verify all 3 nodes are UN
```bash
docker exec cassandra-node1 nodetool status
```

### 3. Create keyspace
```bash
docker exec -it cassandra-node1 cqlsh
CREATE KEYSPACE sentinel WITH replication = {'class': 'NetworkTopologyStrategy', 'dc1': 3};
EXIT;
```

### 4. Set up Python environment
```bash
python3 -m venv judge/venv
source judge/venv/bin/activate
pip install requests docker fastapi uvicorn
```

### 5. Start the API
```bash
judge/venv/bin/python -m uvicorn api.main:app --reload --port 8000
```

### 6. Run a chaos experiment
```bash
curl -X POST http://localhost:8000/experiment \
  -H "Content-Type: application/json" \
  -d '{
    "fault_type": "node-kill",
    "target_node": "cassandra-node2",
    "target_replica_percentage": 20,
    "auto_recover": true,
    "auto_heal": true
  }'
```

### 7. Open Grafana
```
http://localhost:3000
Username: admin
Password: sentinel
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | API info |
| GET | `/status` | Live cluster health + entropy signals |
| GET | `/scores` | Resilience score history + stats |
| GET | `/heals` | Heal event audit log |
| GET | `/vetoes` | OPA-vetoed injection log |
| GET | `/injections` | All injection records |
| POST | `/experiment` | Trigger full chaos pipeline |

---

## AWS Deployment
```bash
cd terraform
terraform init
terraform apply
```

Provisions: 3 × t3.medium Cassandra nodes + 1 × t3.large platform node
on AWS ap-south-1 (Mumbai)
```bash
terraform destroy  # when done — stops all billing instantly
```

---

## Results

| Metric | Local (Docker) | AWS (EC2 t3.medium) |
|---|---|---|
| MTTR | 10s | 25s |
| Blast Radius | 1.0 node | 1.0 node |
| SLO Compliance | 80% | 80% |
| Recovery Cost | 1.0s | 1.0s |
| **Resilience Score** | **0.95** | **0.77** |

AWS score is lower than local — real distributed systems behavior.
Network latency and actual hardware recovery time make the difference.
This validates the scoring formula works correctly across environments.

---

## Research Paper (In Progress)

**"Entropy-Aware Pre-Flight Veto for Policy-Gated Chaos Engineering
in Distributed Database Clusters"**

This repository is the reference implementation for a research paper
currently in preparation. The paper describes the full theoretical
methodology behind the entropy-aware veto mechanism and the
cost-of-recovery resilience scoring formula.

**Target venues:** IEEE CLOUD · ICAC · SRDS · arXiv

Once submitted to arXiv, this repository will be updated with
the paper DOI and the withheld files will be made public.

---

## Author

**Muthyala Aditya**
MTech Cloud Computing · SRM IST Kattankulathur · 2026
[GitHub](https://github.com/aditya3275)

---

## License

Copyright (c) 2026 Muthyala Aditya

This repository is made available for academic review and
reproducibility purposes only.

The resilience scoring formula, entropy-aware veto mechanism,
and cost-of-recovery metric are the original research contributions
of the author and are pending publication.

Reproduction of the methodology in academic work requires
citation of the original paper. Commercial use is prohibited
without written permission.