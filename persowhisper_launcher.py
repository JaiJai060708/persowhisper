"""py2app entry point.

py2app exec's the entry script at top level, which breaks `src/__main__.py`'s
relative imports. This thin launcher imports `src` as a real package so its
relative imports resolve normally.
"""

import sys

from src.app import main


if __name__ == "__main__":
    sys.exit(main())
