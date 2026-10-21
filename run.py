"""
One-Click Production Launcher for Fadfada (فضفضة) AI Psychiatric Agent Demo.
Auto-detects free ports to avoid port collision with other local services.
Safe UTF-8 and cp1252 Windows console handling.
"""

import socket
import sys
import uvicorn

# Configure UTF-8 safe stdout for Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend import config


def find_free_port(preferred_port: int, max_tries: int = 30) -> int:
    """Finds an available TCP port starting from preferred_port."""
    for p in range(preferred_port, preferred_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((config.HOST, p))
                return p
            except OSError:
                continue
    return preferred_port


def main():
    port = find_free_port(config.PORT)

    banner = f"""
========================================================================
  FADFADA - AI Psychiatric Voice Companion Demo Launcher
  Egyptian Colloquial Arabic (Al-Aamiya)
========================================================================
  * Host: {config.HOST}
  * Active Port: {port}
  * Mode: {'Google Gemini Live Cloud' if config.GEMINI_API_KEY else 'Smart Local Simulation Engine'}
  * Model: {config.MODEL_LIVE}
  * Voice: {config.DEFAULT_VOICE}
------------------------------------------------------------------------
  -> Web Application:               http://localhost:{port}/
  -> 4 Design Variants Comparison:  http://localhost:{port}/design-variants-static/index.html
  -> Interactive OpenAPI Docs:       http://localhost:{port}/docs
  -> Health Check:                  http://localhost:{port}/health
========================================================================
"""
    try:
        print(banner)
    except UnicodeEncodeError:
        print(f"Fadfada server running at http://localhost:{port}/")

    uvicorn.run(
        "backend.app:app",
        host=config.HOST,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
