"""產生去識別化測試資料 + 獨立期望值（ground truth）。

刻意讓「渲染」與「解析」走不同程式路徑：本檔只負責把標準值寫成各種雜亂格式，
引擎必須自行還原成標準值，因此正確率比對不是循環驗證。
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import random
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
SURNAMES = "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾"
GIVEN = "志明文淑雅宏佳怡欣彥宇美信豪"

DATE_FORMATS = ["iso", "slash", "roc", "compact", "us", "cn", "fullwidth"]


def render_date(d: dt.date, fmt: str) -> str:
    if fmt == "iso":
        return d.isoformat()
    if fmt == "slash":
        return f"{d.year}/{d.month}/{d.day}"
    if fmt == "roc":
        return f"{d.year - 1911}/{d.month}/{d.day}"
    if fmt == "compact":
        return f"{d.year}{d.month:02d}{d.day:02d}"
    if fmt == "us":
        return f"{d.month}/{d.day}/{d.year}"
    return f"{d.year}年{d.month}月{d.day}日"


def render_amount(v: Decimal, style: str) -> str:
    if style == "plain":
        return f"{v:.2f}"
    if style == "comma":
        return f"{v:,.0f}" if v == v.to_integral_value() else f"{v:,.2f}"
    if style == "dollar":
        return f"NT${v:,.0f}"
    if style == "paren":
        return f"({abs(v):,.0f})"
    if style == "minus_suffix":
        return f"{abs(v):,.0f}-"
    if style == "fullwidth":
        return "".join(chr(ord(c) + 0xFEE0) if c.isdigit() else c for c in f"{v:,.0f}")
    return str(v)


def build(n_main: int = 1000, n_target: int = 200, seed: int = 20261030):
    rnd = random.Random(seed)
    SAMPLES.mkdir(parents=True, exist_ok=True)
    truth = {"main": [], "target": []}

    codes = [f"B{i:04d}" for i in range(1, n_target + 1)]
    names = {}
    target_rows = []
    for code in codes:
        name = rnd.choice(SURNAMES) + "".join(rnd.sample(GIVEN, 2))
        names[code] = name
        goal = Decimal(rnd.randrange(200_000, 1_200_000, 1000))
        style = rnd.choice(["comma", "plain", "dollar"])
        target_rows.append({"代碼": code, "姓名": name, "月目標額": render_amount(goal, style)})
        truth["target"].append({"業務代碼": code, "主管姓名": name, "月目標額": float(goal)})

    main_rows = []
    channels = ["直營", "銀行保代", "保經", "網路"]
    for i in range(n_main):
        code = codes[i % n_target]
        policy = f"P{rnd.randrange(10**8, 10**9)}"
        agent = names[code].replace("", " ") if False else names[code]
        if i % 50 == 0:  # 前後夾雜全形/半形空白，測文字正規化
            agent = "\u3000" + names[code] + "  "
        d = dt.date(2026, 1, 1) + dt.timedelta(days=rnd.randrange(0, 300))
        amount = Decimal(rnd.randrange(10_000, 500_000, 50)) + Decimal("0.00")
        style = rnd.choice(["comma", "plain", "dollar", "paren", "minus_suffix", "fullwidth"])
        fmt = rnd.choice(DATE_FORMATS)
        channel = channels[i % len(channels)]
        main_rows.append({
            "業務代碼": code,
            "保單號碼": policy,
            "業務員": agent,
            "出單日期": render_date(d, fmt),
            "保費金額": render_amount(amount, style),
            "通路": channel,
        })
        truth["main"].append({
            "業務代碼": code,
            "保單號碼": policy,
            "業務員": names[code],
            "出單日期": d.isoformat(),
            "保費金額": float(-amount if style in ("paren", "minus_suffix") else amount),
            "通路": channel,
        })

    with open(SAMPLES / "出單明細_demo.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(main_rows[0]))
        w.writeheader(); w.writerows(main_rows)
    with open(SAMPLES / "業績目標_demo.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(target_rows[0]))
        w.writeheader(); w.writerows(target_rows)
    (SAMPLES / "expected.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(main_rows), len(target_rows)


def build_broken(kind: str) -> Path:
    """產生單一缺陷的來源檔，用來驗證阻斷機制。"""
    rows = [
        {"業務代碼": "B0001", "保單號碼": "P100000001", "業務員": "陳志明",
         "出單日期": "2026-03-05", "保費金額": "12,000", "通路": "直營"},
        {"業務代碼": "B0002", "保單號碼": "P100000002", "業務員": "林雅文",
         "出單日期": "2026/04/07", "保費金額": "8,500", "通路": "銀行保代"},
    ]
    if kind == "missing_key":
        rows[1]["業務代碼"] = ""
    elif kind == "bad_amount":
        rows[0]["保費金額"] = "十二萬"
    elif kind == "duplicate_key":
        rows[1]["保單號碼"] = rows[0]["保單號碼"]
    out = SAMPLES / f"broken_{kind}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    return out


if __name__ == "__main__":
    print(build())
