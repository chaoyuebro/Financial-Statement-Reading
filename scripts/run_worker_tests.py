"""Run worker unit tests via pytest (preferred — uses pytest fixtures like monkeypatch)."""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)

env = os.environ.copy()
env["PYTHONPATH"] = (
    os.path.join(ROOT, "apps", "worker")
    + os.pathsep
    + env.get("PYTHONPATH", "")
)

cmd = [sys.executable, "-m", "pytest", "apps/worker/tests/", "-v"]
print(">>", " ".join(cmd))
res = subprocess.run(cmd, env=env)
sys.exit(res.returncode)