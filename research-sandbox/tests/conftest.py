from pathlib import Path
import sys


SANDBOX_ROOT = Path(__file__).resolve().parents[1]
if str(SANDBOX_ROOT) not in sys.path:
    sys.path.insert(0, str(SANDBOX_ROOT))

RUNTIME_ROOT = SANDBOX_ROOT / "sandbox_runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))
