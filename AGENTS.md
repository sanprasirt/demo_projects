# Agents

This repository is a monorepo of tech demos. Each demo is one app under `apps/<slug>/`.

- Apps are self-contained. From the app directory, `bun install && bun run dev` is enough to run it.
- Use Bun by default.
- Every Bun project has a `bunfig.toml` with `[install] minimumReleaseAge = 259200` in place before any `bun install`.
- Only touch files under `apps/` and `tracking/`, plus the monorepo docs named by the task (`AGENTS.md`, `README.md`, `skills/`).
- Plan a new app with `skills/project-planning/` before writing it. Put the plan in `apps/<slug>/PLAN.md`.
- Every pull request must include at least one screenshot and at least one video of the running app.
