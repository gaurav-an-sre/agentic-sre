#!/usr/bin/env bash
# The incident: ship v2.14.3 with the pool shrunk 50 -> 5 ("cost optimisation", change CHG-88213).
set -euo pipefail
"$(dirname "$0")/20_deploy.sh" v2.14.3 5 1500
echo "bad revision live. start traffic:  ./50_loadgen.sh   then watch the dashboard go red (~2 min)."
