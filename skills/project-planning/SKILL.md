---
name: project-planning
description: Plan a single tech-demo app before writing it. Use when adding a demo under apps/<slug>/.
---

# Project planning

Write a short plan before coding. Save it as `apps/<slug>/PLAN.md`.

1. Clarify the goal and the single-user MVP boundary. Say what the demo does for one person on one machine, and list explicit outs.
2. Break the work into vertical slices (a thin path that runs end to end before extra features).
3. Prefer a prebuilt solution or an official scaffold (`bunx create-*`) over hand-rolled tooling.
4. Use Bun. Create `bunfig.toml` with `[install] minimumReleaseAge = 259200` before the first `bun install`.
5. For UI, use the shadcn/ui minimalist preset when the app has a JavaScript interface.
6. Test only critical logic. Skip UI snapshots and broad integration suites.
7. Keep git hooks small (a format or a single critical test), or defer them.

The plan stays short:

- Goal
- MVP, with explicit outs
- Task list
- Stack, each choice with a one-line rationale
- Deferred items
