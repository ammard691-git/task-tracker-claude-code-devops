"""Allow ``python -m task_tracker``."""

import sys

from task_tracker.cli import main

if __name__ == "__main__":
    sys.exit(main())
