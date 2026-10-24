#!/usr/bin/env python3
"""Generate the game C from the owner input; keep all derived files gitignored."""
import json
from pathlib import Path
import subprocess
import sys

def run(*args):
    subprocess.run([sys.executable, *args], check=True)

Path("work").mkdir(exist_ok=True)
run("scripts/normalize_exe.py", "work/SPEED2.EXE", "work/SPEED2.analysis.exe")
run("../pcrecomp/tools/cpp/vtable_scan.py", "work/SPEED2.analysis.exe",
    "--seeds", "work/vtable_seeds.json")
run("../pcrecomp/tools/cpp/rtti.py", "work/SPEED2.analysis.exe",
    "--seeds", "work/rtti_seeds.json")
seeds = set()
for name in ("vtable_seeds", "rtti_seeds"):
    for item in json.loads(Path("work/" + name + ".json").read_text()):
        value = item["address"]
        seeds.add(int(value, 0) if isinstance(value, str) else value)
Path("work/seeds_all.json").write_text(json.dumps(sorted(seeds)))
run("scripts/run_lift.py", "catalog", "work/SPEED2.analysis.exe",
    "work/seeds_all.json", "work/catalog.json")
run("scripts/run_lift.py", "lift", "work/SPEED2.analysis.exe",
    "work/catalog.json", "src/recomp/gen")
stats = json.loads(Path("src/recomp/gen/lift_stats.json").read_text())
if stats["lift_failures"]:
    raise RuntimeError("Game lifting failed: " + str(stats["lift_failures"]))
print("Game C generated: " + str(stats["functions"]) + " functions", flush=True)
