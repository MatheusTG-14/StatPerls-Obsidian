import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor"))  # Rich, shipped inside the .pyz

from src.installer.app import main

sys.exit(main(sys.argv[1:]))
