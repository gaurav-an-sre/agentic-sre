# Runbook: red button — stop all agent actuation NOW

Use when the agent system itself is behaving badly, or during a change freeze you didn't declare.

## Local
```
make red-button            # touches audit/RED_BUTTON
```
`remediation-mcp` denies every `shift_traffic` while the file exists. Remove the file to resume.

## Cloud
```
system/scripts/80_red_button.sh            # sets AGENT_ACTUATION_PAUSED=1 on remediation-mcp
```
Same effect via env var. Re-run with `AGENT_ACTUATION_PAUSED=` unset to resume.

## What the red button does NOT do
- It does not stop *read-only* investigation — collectors still run, proposals still form; only production writes are denied. That's deliberate: you want the evidence gathering to continue while humans decide.
- It does not roll back anything already applied. Use `payments-pool-exhaustion.md` §3.

## After pressing it
1. Post in the incident channel that actuation is paused and who pressed it.
2. Check the audit log for the last `Apply`/`PolicyDeny` events — was anything mid-flight?
3. Only unpause after the triggering condition is understood.
