╔══════════════════════════════════════════════════════════════╗
║                    CASSANDRA SENTINEL                        ║
║         Policy-Gated · Entropy-Aware · Self-Healing          ║
╚══════════════════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────────────────┐
│                    CASSANDRA CLUSTER                         │
│         3 Nodes · Replication Factor = 3 · RF=3             │
│              [ N1 ] ──── [ N2 ] ──── [ N3 ]                 │
└──────────────────────┬───────────────────────────────────────┘
                       │ JMX scrape
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                  THE OBSERVER                                │
│              Prometheus + MCAC                               │
│                                                              │
│  [SSTable count] [Hinted Handoff] [Disk util]                │
│  [Compaction]    [R/W Latency]    [Replication violations]   │
└──────────────────────┬───────────────────────────────────────┘
                       │ entropy signals
                       ▼
              ┌────────────────────┐
   VETO ◄─── │   THE JUDGE        │
  (logged)    │   OPA Pre-Flight   │
              │                   │
              │ • compaction?      │
              │ • node down?       │
              │ • hints > 100?     │
              │ • blast > 30%?     │
              └────────┬───────────┘
                       │ signed token ✓
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                  THE ACTOR                                   │
│              Argo Workflows DAG                              │
│                                                              │
│   Observe → Judge → Inject → Score → Heal                   │
│                                                              │
│  [Node kill] [Net partition] [CPU stress]                    │
│  [Disk pressure]             [Latency inject]                │
└──────────────────────┬───────────────────────────────────────┘
                       │ post-fault metrics
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                  THE QUANTIFIER                              │
│              Resilience Scoring Engine                       │
│                                                              │
│  score = w1×(1/MTTR)                                        │
│        + w2×(1/blast_radius)                                 │
│        + w3×(SLO_compliance)                                 │
│        + w4×(1/recovery_cost)  ← novel contribution ★       │
└───────────┬──────────────────────────┬───────────────────────┘
            │                          │
       score ≥ 0.6                score < 0.6
            │                          │
            ▼                          ▼
┌───────────────────┐     ┌────────────────────────────────────┐
│  CLUSTER HEALTHY  │     │         THE HEALER                 │
│                   │     │         ArgoCD GitOps              │
│  Score stored     │     │                                    │
│  Keep monitoring  │     │  • Detects drift from Git          │
└───────────────────┘     │  • Syncs to Gold Standard          │
                          │  • nodetool repair                 │
                          │  • Pod restart                     │
                          │  • Every heal = Git commit         │
                          └──────────────┬─────────────────────┘
                                         │ re-evaluate score
                                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  GRAFANA DASHBOARD                           │
│                                                              │
│  [Node health heatmap]  [Resilience score trend]             │
│  [OPA veto log]         [Argo DAG history]                   │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                  FASTAPI — REST Interface                    │
│         Trigger experiments · Fetch resilience scores        │
└──────────────────────────────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Prometheus feeds Grafana continuously (background loop)
  Feedback loop: Score history → improves next chaos cycle
  ★ recovery_cost = compaction overhead + hinted handoff drain
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━