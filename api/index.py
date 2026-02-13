"""
Vercel serverless entry: expose Flask app for Vercel deploy.
All routes are handled by the backend_server app.
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root / "src") not in sys.path:
    sys.path.insert(0, str(root / "src"))
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend_server import create_app

app = create_app()
