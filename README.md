# PersonalAi

A private, self-hosted personal AI agent. It reads mail, calendar, Google Classroom, Drive, local files, bank-SMS transactions and account balances, and you talk to it from an Android app.

- **Approval-gated writes.** The agent proposes; you approve each action with a fingerprint check.
- **Local-first.** It runs on your own laptop and is reachable only over Tailscale.
- **Redaction.** Personal identifiers are masked before any text reaches the cloud LLM (NVIDIA Build).

See [`docs/PLAN.md`](docs/PLAN.md) for the design and build phases.

> Status: under construction (phase M2 — mail).
