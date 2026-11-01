"""產生給 Instinct 交叉核查的機器副本（JSON）。

機器副本只放可被獨立重跑的客觀事實：檔案雜湊、測試案例、實測數值、環境版本。
不放主觀結論，結論留給 Instinct。
"""
from __future__ import annotations
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "instinct_package_機器副本.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests() -> dict:
    proc = subprocess.run([sys.executable, "tests/test_acceptance.py"], cwd=ROOT,
                          capture_output=True, text=True)
    cases = []
    for line in proc.stdout.splitlines():
        if line.startswith(("PASS", "FAIL")):
            status, rest = line.split(None, 1)
            name, _, detail = rest.partition("  — ")
            cases.append({"case": name.strip(), "result": status, "detail": detail.strip()})
    total = len(cases)
    passed = sum(1 for c in cases if c["result"] == "PASS")
    return {
        "exit_code": proc.returncode,
        "benchmark_sec": None if "耗時" not in proc.stdout else None,
        "cases_total": total,
        "cases_passed": passed,
        "cases": cases,
        "raw_tail": proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "",
    }


def main() -> None:
    files = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if any(x in rel for x in ("__pycache__", ".git/", "instinct_package")):
            continue
        if rel.startswith("output/_"):
            continue
        files.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha256(p)})
    payload = {
        "artifact": "FinReport-Core MVP",
        "version": "1.0.0",
        "case": "TK26102311QJVC85",
        "builder": "bizast_bot (Base44 runtime)",
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "purpose": "提交 Instinct 交叉核查",
        "environment": {
            "python": platform.python_version(),
            "openpyxl": __import__("openpyxl").__version__,
            "platform": platform.platform(),
            "network_access_during_tests": "blocked (socket monkeypatched)",
        },
        "files": files,
        "file_count": len(files),
        "tests": run_tests(),
        "reproduce": [
            "pip install openpyxl",
            "python3 tools/make_demo_data.py",
            "python3 -m finreport.cli --config config/demo_config.json --audit output/Audit_Error_Log.csv",
            "python3 tests/test_acceptance.py",
        ],
        "declared_constraints": [
            "無任何網路呼叫（含 LLM API）",
            "無資料庫、無常駐服務，單機可執行",
            "阻斷級稽核成立時不產出正式報表",
        ],
        "not_claimed": [
            "未經 Tasker 登入牆驗證案主真實需求",
            "未與案主聯絡",
            "未做資安滲透測試或效能壓力測試（僅 1,000 筆基準集）",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("寫出", OUT.name, OUT.stat().st_size, "bytes")
    print("測試:", payload["tests"]["cases_passed"], "/", payload["tests"]["cases_total"])


if __name__ == "__main__":
    main()
