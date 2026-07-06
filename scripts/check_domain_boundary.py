#!/usr/bin/env python
"""域边界 lint: market/** 不得 import risk/**; risk/** 不得 import market/**。

CI 可调用: python scripts/check_domain_boundary.py
"""
import ast
import sys
from pathlib import Path

VIOLATIONS = []


def check(path: Path, forbidden_prefix: str, domain_name: str):
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        for m in mods:
            if m.startswith(forbidden_prefix):
                VIOLATIONS.append(f"{path}: {domain_name} 禁止 import {m}")


root = Path("investbrief")
for p in root.glob("market/**/*.py"):
    check(p, "investbrief.risk", "market")
for p in root.glob("risk/**/*.py"):
    check(p, "investbrief.market", "risk")

if VIOLATIONS:
    print("\n".join(VIOLATIONS))
    sys.exit(1)
print("domain boundary OK")
