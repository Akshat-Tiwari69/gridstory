# Lap comparison implementation boundary

2026-10-31 · CTO · Phase 2

Keep comparison mathematics and deterministic findings in Python, using the existing
NumPy stack and F1DataService fallback. Add an independent A/B lap selection contract:
the current multi-driver response is keyed by driver and accepts one shared lap,
so it cannot represent two different laps from the same driver. Preserve that endpoint
for existing telemetry consumers. React renders the comparison result and persists
both selections in the URL.

Reason: one tested analysis implementation can serve both the API and Python-generated
Pages snapshots without adding dependencies or duplicating analysis in TypeScript.
Never delete or rebuild `apps/api/app/f1_cache`. A hosted API is a separate release
decision requiring CEO review of cost, hosting and cache handling; the existing Pages
demo has no backend and cannot provide arbitrary archive sessions by itself.

2026-11-01 · CTO review

Keep discrete gear/brake channels on the nearest recorded sample and absorb gaps
shorter than the 5 m grid into the following corner segment. Reason: interpolation
must not invent gears, and segment gains must account for every part of the lap.
