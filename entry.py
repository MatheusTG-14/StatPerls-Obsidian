import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor"))  # Rich, shipped inside the .pyz

if getattr(sys, "frozen", False):  # built-in Python has no system certificate store on macOS: use the bundled one
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass

from src.installer.app import main

sys.exit(main(sys.argv[1:]))
