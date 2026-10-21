"""
Vercel Serverless ASGI Entrypoint for Fadfada Psychiatric Agent.
Enables deployment of REST APIs and Static Gateway on Vercel Python Runtime.
"""

import os
import sys
from pathlib import Path

# Ensure root directory is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Set temporary database path for serverless environment if read-only filesystem
if "VERCEL" in os.environ:
    os.environ.setdefault("DATABASE_PATH", "/tmp/fadfada.db")

from backend.app import app
