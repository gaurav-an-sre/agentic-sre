"""python -m mcp_servers <observability|release|incident|remediation>"""

import importlib
import sys

from mcp_servers.common import serve

name = sys.argv[1] if len(sys.argv) > 1 else "observability"
serve(importlib.import_module(f"mcp_servers.{name}").server)
