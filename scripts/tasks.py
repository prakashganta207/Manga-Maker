"""Cross-platform task runner (works on Windows without `make`).

    python scripts/tasks.py install   # backend venv + deps, frontend npm install
    python scripts/tasks.py test      # backend tests (mock mode)
    python scripts/tasks.py dev       # backend :8000 + frontend :3000
    python scripts/tasks.py backend   # backend only
    python scripts/tasks.py frontend  # frontend only
    python scripts/tasks.py sample    # regenerate samples/ output
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
NPM = "npm.cmd" if os.name == "nt" else "npm"


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print(f"$ {' '.join(map(str, cmd))}   (in {cwd.name}/)")
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True, env=env)


def python() -> Path | str:
    return VENV_PY if VENV_PY.exists() else sys.executable


def install() -> None:
    if not VENV_PY.exists():
        run([sys.executable, "-m", "venv", VENV], BACKEND)
    run([VENV_PY, "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
    if FRONTEND.exists() and shutil.which(NPM):
        run([NPM, "install"], FRONTEND)
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy(ROOT / ".env.example", env_file)
        print("Created .env from .env.example (mock mode until you add keys).")


def test() -> None:
    env = {**os.environ, "LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "mock"}
    run([python(), "-m", "pytest"], BACKEND, env=env)


def backend_cmd() -> list:
    return [python(), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"]


def frontend_cmd() -> list:
    return [NPM, "run", "dev"]


def dev() -> None:
    procs = [subprocess.Popen([str(c) for c in backend_cmd()], cwd=BACKEND),
             subprocess.Popen(frontend_cmd(), cwd=FRONTEND)]
    print("Backend: http://localhost:8000/docs   Frontend: http://localhost:3000   (Ctrl+C to stop)")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


def sample() -> None:
    env = {**os.environ, "LLM_PROVIDER": "mock", "IMAGE_PROVIDER": "mock"}
    run([python(), "-m", "app.cli", "../samples/rooftop_glow.txt", "--out", "../samples/rooftop_glow_output"],
        BACKEND, env=env)


TASKS = {
    "install": install,
    "test": test,
    "dev": dev,
    "backend": lambda: run(backend_cmd(), BACKEND),
    "frontend": lambda: run(frontend_cmd(), FRONTEND),
    "sample": sample,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(1)
    try:
        TASKS[sys.argv[1]]()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
