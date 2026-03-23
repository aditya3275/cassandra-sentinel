package sentinel.preflight

import rego.v1

# Default decision — allow injection
default allow := false
default veto_reasons := []

# Allow only if no veto reasons exist
allow if {
    count(veto_reasons) == 0
}

# Collect all veto reasons
veto_reasons := reasons if {
    reasons := [r |
        some check in veto_checks
        check.vetoed == true
        r := check.reason
    ]
}

# All veto checks
veto_checks := [
    {
        "name": "compaction_check",
        "vetoed": input.pending_compactions > 0,
        "reason": sprintf("Compaction in progress: %v pending tasks", [input.pending_compactions])
    },
    {
        "name": "hints_check",
        "vetoed": input.hints_in_progress > 100,
        "reason": sprintf("Hinted handoff drain in progress: %v hints pending", [input.hints_in_progress])
    },
    {
        "name": "nodes_down_check",
        "vetoed": input.nodes_down > 0,
        "reason": sprintf("Cluster already degraded: %v node(s) down", [input.nodes_down])
    },
    {
        "name": "blast_radius_check",
        "vetoed": input.target_replica_percentage > 30,
        "reason": sprintf("Blast radius too high: %v%% exceeds 30%% limit", [input.target_replica_percentage])
    },
    {
        "name": "concurrent_faults_check",
        "vetoed": input.active_faults > 1,
        "reason": sprintf("Too many concurrent faults: %v active", [input.active_faults])
    }
]