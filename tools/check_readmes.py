"""Check that the two readmes exist and cover the same ground.

The tool ships an English readme and a Chinese one. They must not drift
apart, so this script checks the few things that must be true in both.

Run it: python tools/check_readmes.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGLISH = os.path.join(ROOT, "README.md")
CHINESE = os.path.join(ROOT, "README.zh-CN.md")

# The commands that the readme must mention.
COMMANDS = (
    "search",
    "geocode",
    "reverse",
    "route",
    "matrix",
    "compare",
    "convert",
    "district",
    "weather",
    "providers",
    "config",
)

# The environment variables that the readme must name.
ENV_VARS = (
    "BAIDU_MAP_AK",
    "AMAP_API_KEY",
    "TENCENT_MAP_KEY",
)


def read(path: str) -> str:
    """Return the text of one file."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def main() -> int:
    """Check both readmes. Return the exit code."""
    problems = []

    for path in (ENGLISH, CHINESE):
        if not os.path.isfile(path):
            problems.append("missing file: " + path)
            continue
        text = read(path)
        for command in COMMANDS:
            if command not in text:
                problems.append("{0} does not mention the command {1}".format(path, command))
        for name in ENV_VARS:
            if name not in text:
                problems.append("{0} does not mention {1}".format(path, name))

    for problem in problems:
        print("Error: " + problem, file=sys.stderr)
    if problems:
        return 1

    print("Both readmes are there and they name every command and every key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
