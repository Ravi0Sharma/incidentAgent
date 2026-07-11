# POC Data Inventory

| Data | Purpose | Store | Access | Retention/deletion status |
| --- | --- | --- | --- | --- |
| Normalized alert/event | Incident reconstruction and idempotency | MySQL `incident_events` | API/worker DB role | Retention/deletion automation not implemented. |
| Analysis/checkpoint | Resume review workflow | MySQL checkpoint tables | Worker DB role | Retention/deletion automation not implemented. |
| Review decision | Human audit and workflow transition | MySQL pending/lifecycle/event tables | Reviewer API + worker DB role | Retention/deletion automation not implemented. |
| Dead letter | Failure diagnosis and authorized replay | MySQL dead-letter table | Operator API + DB role | Redacted; retention automation not implemented. |
| Local reports | Reviewer/postmortem draft | Local `output/` folder | Local reviewer process | POC-only; no object-store retention policy. |

The POC is local and defines no region, external processor, legal-hold, or
production retention policy. Do not enter customer secrets or raw production
telemetry until those controls exist.
