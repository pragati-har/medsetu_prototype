import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_PATH", "/tmp/medsetu.db")
os.environ.setdefault("UPLOAD_DIR", "/tmp/uploads")

from app import app

