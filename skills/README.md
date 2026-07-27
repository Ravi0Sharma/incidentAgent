# Incident Response Skills

Portable Agent Skills distilled from [PagerDuty's Incident Response documentation](https://response.pagerduty.com/). Each skill is a plain markdown folder that can be loaded by Cursor, Claude Code, or any other agent runtime that supports the Anthropic Agent Skills format (YAML frontmatter + markdown body).

## Skills in this collection

| Skill | Purpose |
| --- | --- |
| `severity-classification/` | Classify incidents as SEV-1 through SEV-5 using PagerDuty's rubric. |
| `alerting-principles/` | Design alerts that are actionable (High/Medium/Low/Notification) with useful content. |
| `incident-runbook/` | Coordinate a live incident — roles, mentality shift, per-role playbooks. |
| `postmortem-writer/` | Produce blameless postmortems using the PagerDuty template. |
| `security-incident/` | Follow the 14-step security incident response checklist. |
| `anti-patterns/` | Recognize and avoid the anti-patterns PagerDuty learned to reject. |
| `agent-incident-responder/` | Agent-operational principles: human-in-the-loop, transparency, graceful degradation, alert chronology, confidence thresholds, deploy-window correlation, PR conventions. |
| `caveman/` | Ultra-compressed communication style. Terse fragments, no filler, technical terms exact. Levels: `lite` / `full` / `ultra`. |

The first six describe **what humans do** during incident response. The seventh describes **how an AI agent should behave** while doing the same job. The eighth (`caveman`) is a communication-style skill — orthogonal, can be composed with any of the others.

## How to load these into an agent

**Cursor:** symlink or copy individual skills into `~/.cursor/skills/` or `<repo>/.cursor/skills/`.

**Claude Code:** symlink into `~/.claude/skills/` or `<repo>/.claude/skills/`.

**Custom runtime:** read `SKILL.md` from any skill folder — the YAML frontmatter carries `name` and `description`, everything below is the skill body.

## Source

Skills 1–6 are derived from https://response.pagerduty.com/ (CC BY 4.0). Severity thresholds and role hierarchies are generic and should be tightened for your specific organization.

Skill 7 (`agent-incident-responder`) distills agent-operational patterns from https://github.com/rootlyhq/rootly-mcp-server/blob/main/examples/skills/rootly-incident-responder.md (human-in-the-loop, transparency, graceful degradation, confidence-scored hypotheses with alternatives) generalized away from any specific product, with additions tuned to a LangGraph + Loki + Prometheus + GitHub + Slack architecture.
