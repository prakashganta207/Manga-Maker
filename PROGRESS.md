# Progress

## Done
- **M1** Skeleton, settings (`backend/app/config.py`), script schema (`models.py`),
  provider interfaces (`providers/base.py`), mock LLM + mock image providers,
  provider factory, task runner (`scripts/tasks.py`) + Makefile. 7 tests passing.

## Next
- M2 story → script stage with validation + retry.

## Known issues
- `make` and Docker are not installed on the build machine; use `python scripts/tasks.py …`.
