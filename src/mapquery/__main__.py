"""Allow the tool to be run with "python -m mapquery"."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
