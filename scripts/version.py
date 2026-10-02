import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version():
    value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", value):
        raise ValueError("VERSION must contain a semantic version")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["show", "check", "set", "major", "minor", "patch"])
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    value = read_version()
    if args.action == "set":
        if not args.value or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", args.value):
            parser.error("Provide a semantic version")
        value = args.value
    elif args.action in {"major", "minor", "patch"}:
        parts = list(map(int, value.split("-")[0].split(".")))
        index = ["major", "minor", "patch"].index(args.action)
        parts[index] += 1
        for position in range(index + 1, 3):
            parts[position] = 0
        value = ".".join(map(str, parts))
    if args.action not in {"show", "check"}:
        (ROOT / "VERSION").write_text(value + "\n", encoding="utf-8")
    print(value)
