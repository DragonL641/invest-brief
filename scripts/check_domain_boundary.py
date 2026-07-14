#!/usr/bin/env python
"""域边界 lint: 五域(market/holdings/risk/regime/mail)互不 import; core/** 不得 import 任何域包。

CLAUDE.md: "domains have ZERO 横向 dependencies, collaborate only through pipelines/"
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


# 五域互不引用; core 不得引用任何域包
DOMAINS = ["market", "holdings", "risk", "regime", "mail"]

root = Path("investbrief")
for domain in DOMAINS:
    forbidden = [d for d in DOMAINS if d != domain]
    for p in root.glob(f"{domain}/**/*.py"):
        for other in forbidden:
            check(p, f"investbrief.{other}", domain)

for p in root.glob("core/**/*.py"):
    for domain in DOMAINS:
        check(p, f"investbrief.{domain}", "core")

if VIOLATIONS:
    print("\n".join(VIOLATIONS))
    sys.exit(1)
print("domain boundary OK")
