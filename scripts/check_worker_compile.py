import py_compile
import sys

files = [
    "apps/worker/enqueue_server.py",
    "apps/worker/retrieval.py",
    "apps/worker/embed.py",
    "apps/worker/metrics.py",
    "apps/worker/pipeline.py",
    "apps/worker/parse.py",
    "apps/worker/download.py",
    "apps/worker/config.py",
    "apps/worker/db.py",
]
errs = 0
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"OK   {f}")
    except py_compile.PyCompileError as e:
        print(f"FAIL {f}: {e}")
        errs += 1
print(f"--- {len(files) - errs}/{len(files)} compiled ---")
sys.exit(errs)