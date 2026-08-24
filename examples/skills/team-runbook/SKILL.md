---
name: team-runbook
description: Walks through this team's on-call incident checklist - acknowledge, assess severity, mitigate, then write up a postmortem. Use when asked to handle an incident, page, or on-call alert for this team.
---

# Team Runbook

Given an `incidentSummary` (and optionally a `severity`), work through this
team's checklist in order:

1. **Acknowledge.** State clearly that you're on it, and restate the
   incident summary back so there's no ambiguity about what's being
   worked.
2. **Assess severity**, if not already given: sev1 (customer-facing
   outage), sev2 (degraded but usable), sev3 (internal-only/low impact).
3. **Mitigate first, root-cause later.** Prefer the fastest safe action
   that stops customer impact (rollback, feature flag, failover) over
   immediately diagnosing the underlying cause.
4. **Communicate.** Note what was done and its effect, in plain language
   a non-engineer stakeholder could follow.
5. **Postmortem.** Once mitigated, write a short summary: what happened,
   what was done, and one concrete follow-up action — not a full
   retrospective, just enough for the next person to pick up.

This is example content for a private, tenant-owned demo skill — adapt
the checklist to your own team's actual on-call process before relying
on it.
