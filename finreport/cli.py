"""命令列入口：python -m finreport.cli --config config/demo_config.json"""
from __future__ import annotations
import argparse
import json
import sys

from .engine import run
from .schema import load_config, SchemaError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finreport-core",
                                 description="純規則報表正規化與合併引擎（離線可用）")
    ap.add_argument("--config", required=True, help="Schema 設定檔路徑 (JSON)")
    ap.add_argument("--audit", default="output/Audit_Error_Log.csv", help="稽核記錄輸出路徑")
    ap.add_argument("--json", action="store_true", help="以 JSON 輸出執行結果")
    args = ap.parse_args(argv)
    try:
        config = load_config(args.config)
    except (SchemaError, OSError, json.JSONDecodeError) as exc:
        print(f"[設定錯誤] {exc}", file=sys.stderr)
        return 2
    result = run(config, audit_path=args.audit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"專案：{result['project']}")
        print(f"狀態：{result['status']}　合併列數：{result['merged_rows']}　"
              f"稽核：{result['audit_total']}（阻斷 {result['audit_blocking']}）　"
              f"耗時：{result['elapsed_sec']}s")
        if result.get("halted"):
            print("已阻斷：資料異常，未產出正式報表。請看稽核記錄：", result.get("audit_log"))
        elif result.get("output"):
            print("已產出：", result["output"])
    return 0 if result["status"] in ("OK", "WARN") else 3


if __name__ == "__main__":
    raise SystemExit(main())
