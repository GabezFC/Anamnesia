"""Turn pytest junit failures into GitHub `::error::` annotations (readable via the public API)."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def main(path: str) -> int:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"::error::junit unreadable: {exc}")
        return 0
    n = 0
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                n += 1
                msg = " | ".join((node.get("message") or node.text or "").split())[:480]
                print(f"::error title={case.get('classname')}.{case.get('name')}::{msg}")
    print(f"{n} failing tests")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "junit.xml"))
