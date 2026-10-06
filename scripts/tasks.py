"""Cross-platform task runner (works on Windows without `make`).

    python scripts/tasks.py install   # backend venv + deps, frontend npm install
    python scripts/tasks.py test      # backend tests (mock mode)
    python scripts/tasks.py dev       # backend :8000 + frontend :3000
    python scripts/tasks.py backend   # backend only
    python scripts/tasks.py frontend  # frontend only
    python scripts/tasks.py sample    # run samples/stories/*.txt -> samples/output/
    python scripts/tasks.py comfyui   # start the in-project ComfyUI (comfyui/, see SETUP_COMFYUI.md)
    python scripts/tasks.py demo      # final 2-chapter run -> samples/demo (add --train-lora by hand)

Ports: BACKEND_PORT (default 8000) and FRONTEND_PORT (default 3000) env vars.
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
BACKEND_PORT = os.environ.get("BACKEND_PORT", "8000")
FRONTEND_PORT = os.environ.get("FRONTEND_PORT", "3000")


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
    return [python(), "-m", "uvicorn", "app.main:app", "--reload", "--port", BACKEND_PORT]


def frontend_cmd() -> list:
    return [NPM, "run", "dev", "--", "-p", FRONTEND_PORT]


def frontend_env() -> dict:
    # Point the browser at the backend port unless NEXT_PUBLIC_API_URL is already set.
    env = dict(os.environ)
    env.setdefault("NEXT_PUBLIC_API_URL", f"http://localhost:{BACKEND_PORT}")
    return env


def dev() -> None:
    procs = [subprocess.Popen([str(c) for c in backend_cmd()], cwd=BACKEND),
             subprocess.Popen(frontend_cmd(), cwd=FRONTEND, env=frontend_env())]
    print(f"Backend: http://localhost:{BACKEND_PORT}/docs   "
          f"Frontend: http://localhost:{FRONTEND_PORT}   (Ctrl+C to stop)")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            stop_tree(p)


def stop_tree(proc: subprocess.Popen) -> None:
    """Stop a process AND its children (uvicorn --reload / next dev spawn workers).

    On Windows, terminate() only kills the direct child, leaving workers that keep the
    port open and serve stale code — so kill the whole tree with taskkill /T.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()


def sample() -> None:
    """Run every story in samples/stories/ end to end (uses whatever providers .env selects;
    set LLM_PROVIDER=mock IMAGE_PROVIDER=mock to force mock mode)."""
    for story in sorted((ROOT / "samples" / "stories").glob("*.txt")):
        out = ROOT / "samples" / "output" / story.stem
        if out.exists():
            shutil.rmtree(out)  # fresh run, not a resume
        run([python(), "-m", "app.cli", story, "--out", out], BACKEND)


def comfyui() -> None:
    """Start the ComfyUI installed inside the project. --disable-pinned-memory keeps ~6 GB of RAM free
    for LoRA training on 16 GB machines (DECISIONS #66)."""
    folder = ROOT / "comfyui"
    py = folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        print("No ComfyUI in comfyui/ - see SETUP_COMFYUI.md (Option B).")
        sys.exit(1)
    run([py, "ComfyUI/main.py", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch",
         "--disable-pinned-memory"], folder)


TASKS = {
    "install": install,
    "test": test,
    "dev": dev,
    "backend": lambda: run(backend_cmd(), BACKEND),
    "frontend": lambda: run(frontend_cmd(), FRONTEND, env=frontend_env()),
    "sample": sample,
    "comfyui": comfyui,
    "demo": lambda: run([python(), ROOT / "scripts" / "make_demo.py"], ROOT),
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(1)
    try:
        TASKS[sys.argv[1]]()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
