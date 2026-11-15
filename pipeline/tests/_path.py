"""Put pipeline/ on the import path for the tests (imported first by each test file)."""
import sys
from pathlib import Path

PIPELINE = str(Path(__file__).resolve().parents[1])
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)
