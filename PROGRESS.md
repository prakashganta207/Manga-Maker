# Progress

## Done
- **M1** Skeleton, settings (`backend/app/config.py`), script schema (`models.py`),
  provider interfaces (`providers/base.py`), mock LLM + mock image providers,
  provider factory, task runner (`scripts/tasks.py`) + Makefile. 7 tests passing.

## Next
- M2 story → script stage with validation + retry.

## Known issues
- Ports 8000/3000 were busy on the build machine (other apps), so the UI was tested on
  8100/3100. Use `BACKEND_PORT` / `FRONTEND_PORT` with `scripts/tasks.py` if you hit the same.
- `NEXT_PUBLIC_API_URL` is baked in at frontend build time (Next.js rule): rebuild after changing it.
- `make` and Docker are not installed on the build machine; use `python scripts/tasks.py …`.
