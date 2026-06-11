#!/usr/bin/env python3
"""
NCAA Scouting Dashboard — entry point.

The actual application lives in the web/ package (see web/__init__.py for the
module map). This file exists so `python app.py` keeps working.
"""

import os

from web import app

if __name__ == "__main__":
    # debug defaults OFF; opt in with SCOUT_DEBUG=1 for local dev only.
    # (debug=True exposes the Werkzeug console — never run it exposed.)
    debug = os.environ.get("SCOUT_DEBUG", "").lower() in ("1", "true", "yes")
    port = int(os.environ.get("SCOUT_PORT", "5001"))
    app.run(debug=debug, port=port)
