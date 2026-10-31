"""驗收測試：對應 RSAD 模組五的四項剛性驗收指標。

執行：python3 tests/test_acceptance.py
"""
from __future__ import annotations
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from finreport.engine import run          # noqa: E402
from finreport.schema import load_config  # noqa: E402
from tools.make_demo_data import build_broken  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  — {detail}" if detail else ""))


def load_output(path: str) -> list[dict]:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = list(rows[0])
    return [dict(zip(header, r)) for r in rows[1:]]


def test_accuracy_and_speed() -> None:
    cfg = load_config("config/demo_config.json")
    cfg.output["path"] = "output/_test_out.xlsx"
    result = run(cfg, audit_path="output/_test_audit.csv")
    check("A1 執行成功且未被阻斷", result["status"] == "OK", f"status={result['status']}")
    check("A2 合併筆數等於來源筆數 1000", result["merged_rows"] == 1000,
          f"merged={result['merged_rows']}")
    check("A3 1,000 筆執行時間 ≤ 15 秒", result["elapsed_sec"] <= 15,
          f"{result['elapsed_sec']}s")

    truth = json.loads(Path("samples/expected.json").read_text(encoding="utf-8"))
    goals = {t["業務代碼"]: t for t in truth["target"]}
    expected = []
    for t in truth["main"]:
        g = goals[t["業務代碼"]]
        expected.append({**t, "主管姓名": g["主管姓名"], "月目標額": g["月目標額"]})
    got = load_output("output/_test_out.xlsx")
    check("B1 輸出筆數與期望值一致", len(got) == len(expected),
          f"{len(got)} vs {len(expected)}")

    fields = ["業務代碼", "保單號碼", "業務員", "主管姓名", "出單日期", "通路",
              "保費金額", "月目標額"]
    total = len(expected) * len(fields)
    wrong = []
    for exp, act in zip(sorted(expected, key=lambda r: r["保單號碼"]),
                        sorted(got, key=lambda r: r["保單號碼"])):
        for f in fields:
            a, e = act.get(f), exp[f]
            same = (abs(float(a) - float(e)) < 0.005) if isinstance(e, float) else (a == e)
            if not same:
                wrong.append((exp["保單號碼"], f, e, a))
    rate = (total - len(wrong)) / total * 100
    check("B2 欄位計算正確率 100%", not wrong, f"{rate:.2f}%（{len(wrong)} 個不符）")
    for w in wrong[:5]:
        print("      不符：", w)


def test_blocking() -> None:
    base = json.loads(Path("config/demo_config.json").read_text(encoding="utf-8"))
    cases = [
        ("missing_key", "A01", "主鍵空白"),
        ("bad_amount", "A03", "金額為文字型態"),
        ("duplicate_key", "A02", "主鍵重複"),
    ]
    for kind, code, label in cases:
        path = build_broken(kind)
        cfg_raw = json.loads(json.dumps(base))
        cfg_raw["sources"][0]["path"] = str(path.relative_to(ROOT))
        outp = Path("output") / f"_blocked_{kind}.xlsx"
        audp = Path("output") / f"_blocked_{kind}_audit.csv"
        if outp.exists():
            outp.unlink()
        cfg_raw["output"]["path"] = str(outp)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(cfg_raw, fh, ensure_ascii=False)
            cfg_path = fh.name
        result = run(load_config(cfg_path), audit_path=str(audp))
        os.unlink(cfg_path)
        log = audp.read_text(encoding="utf-8-sig")
        check(f"C[{kind}] 立即停止並回報阻斷", result["status"] == "BLOCKED",
              f"status={result['status']}")
        check(f"C[{kind}] 未產出正式報表", not outp.exists(), str(outp))
        check(f"C[{kind}] Audit_Error_Log 含 {code}（{label}）", code in log,
              log.splitlines()[1][:60] if len(log.splitlines()) > 1 else "無記錄")
        check(f"C[{kind}] 程序未崩潰並回傳結果", isinstance(result, dict), "")


def test_offline() -> None:
    real_socket = socket.socket

    def _blocked(*a, **k):
        raise AssertionError("偵測到網路呼叫：本引擎必須可離線執行")

    socket.socket = _blocked
    socket.create_connection = _blocked
    try:
        cfg = load_config("config/demo_config.json")
        cfg.output["path"] = "output/_offline_out.xlsx"
        result = run(cfg, audit_path="output/_offline_audit.csv")
        check("D1 完全斷網環境仍可完成", result["status"] == "OK",
              f"status={result['status']}, rows={result['merged_rows']}")
    except AssertionError as exc:
        check("D1 完全斷網環境仍可完成", False, str(exc))
    finally:
        socket.socket = real_socket


def main() -> int:
    started = time.perf_counter()
    test_accuracy_and_speed()
    test_blocking()
    test_offline()
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n合計 {passed}/{total} 通過（總耗時 {time.perf_counter() - started:.2f}s）")
    for f in Path("output").glob("_test_*"):
        f.unlink()
    for f in Path("output").glob("_offline_*"):
        f.unlink()
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
