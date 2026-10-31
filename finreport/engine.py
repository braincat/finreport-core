"""FinReport-Core 引擎：讀取 -> 正規化 -> 主鍵合併 -> 阻斷式稽核 -> 輸出。

設計約束（合約級）：
  1. 純規則，零網路、零 LLM 呼叫。
  2. 任何阻斷級稽核項目成立時，不產生正式輸出報表，只產生 Audit_Error_Log.csv。
  3. 不因資料異常而崩潰（例外一律轉為稽核記錄）。
"""
from __future__ import annotations
import csv
import os
import time
from dataclasses import dataclass
from typing import Any

from .normalize import normalize_amount, normalize_date, normalize_text, NormalizeError
from .schema import Config, Column, SourceSpec

AUDIT_COLUMNS = ["來源", "資料列", "欄位", "錯誤代碼", "原始值", "說明", "等級"]
BLOCKING = {"A01", "A02", "A03", "A04", "A05"}


@dataclass
class Audit:
    source: str
    row_no: int
    column: str
    code: str
    raw: Any
    message: str

    @property
    def blocking(self) -> bool:
        return self.code in BLOCKING

    def as_row(self) -> list[str]:
        return [
            self.source, str(self.row_no), self.column, self.code,
            "" if self.raw is None else str(self.raw), self.message,
            "阻斷" if self.blocking else "警告",
        ]


def _read_rows(spec: SourceSpec) -> list[dict]:
    """讀取來源為 list[dict]，保留原始資料列號（含表頭偏移）。"""
    path = spec.path
    ext = os.path.splitext(path)[1].lower()
    rows: list[dict] = []
    if ext in (".csv", ".txt"):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            for i, rec in enumerate(reader, start=1):
                if i < spec.header_row:
                    continue
                if i == spec.header_row:
                    header = [normalize_text(h) for h in rec]
                    continue
                rows.append({"_row": i, **{header[j]: (rec[j] if j < len(rec) else "")
                                           for j in range(len(header))}})
    elif ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True, read_only=True)
        ws = wb[spec.sheet] if spec.sheet else wb[wb.sheetnames[0]]
        header: list[str] = []
        for i, rec in enumerate(ws.iter_rows(values_only=True), start=1):
            if i < spec.header_row:
                continue
            if i == spec.header_row:
                header = [normalize_text(h) for h in rec]
                continue
            rows.append({"_row": i, **{header[j]: (rec[j] if j < len(rec) else None)
                                       for j in range(len(header))}})
        wb.close()
    else:
        raise ValueError(f"不支援的來源格式：{ext}")
    return rows


def _convert(col: Column, raw: Any, source: str, row_no: int, audits: list[Audit]):
    """依欄位型別正規化；錯誤轉為稽核記錄並回傳 None。"""
    try:
        if col.type == "amount":
            return normalize_amount(raw)
        if col.type == "date":
            return normalize_date(raw)
        if col.type == "int":
            v = normalize_amount(raw)
            if v != int(v):
                raise NormalizeError("NOT_INTEGER")
            return int(v)
        return normalize_text(raw)
    except NormalizeError as exc:
        code = {
            "amount": {"EMPTY": "A04", "NOT_NUMERIC": "A03"},
            "date": {"EMPTY": "A04"},
            "int": {"EMPTY": "A04", "NOT_NUMERIC": "A03", "NOT_INTEGER": "A03"},
        }.get(col.type, {}).get(str(exc), "A03" if col.type in ("amount", "int") else "A05")
        if col.type == "text":
            code = "A06"
        audits.append(Audit(source, row_no, col.source, code, raw,
                            f"{col.type} 正規化失敗：{exc}"))
        return None


def _normalize_source(spec: SourceSpec, audits: list[Audit]) -> list[dict]:
    out: list[dict] = []
    seen: dict[str, int] = {}
    for rec in _read_rows(spec):
        row_no = rec["_row"]
        item: dict[str, Any] = {"_row": row_no, "_source": spec.name}
        row_ok = True
        for col in spec.columns:
            raw = rec.get(col.source)
            val = _convert(col, raw, spec.name, row_no, audits)
            if val is None:
                row_ok = False
                if col.required or col.role == "key" or col.type == "amount":
                    pass  # 已記錄稽核
            item[col.target] = val
            if col.role == "join" and val in (None, ""):
                audits.append(Audit(spec.name, row_no, col.source, "A01", raw,
                                    "對應鍵空白，無法與其他報表合併"))
                row_ok = False
            if col.role == "key":
                if val in (None, ""):
                    if not any(a.source == spec.name and a.row_no == row_no and a.column == col.source
                               for a in audits):
                        audits.append(Audit(spec.name, row_no, col.source, "A01", raw, "主鍵空白"))
                    row_ok = False
                elif val in seen:
                    audits.append(Audit(spec.name, row_no, col.source, "A02", raw,
                                        f"主鍵重複（首次出現於第 {seen[val]} 列）"))
                    row_ok = False
                else:
                    seen[val] = row_no
        if row_ok:
            out.append(item)
    return out


def run(config: Config, audit_path: str | None = None) -> dict:
    started = time.perf_counter()
    audits: list[Audit] = []
    merged: list[dict] = []
    primary = config.source(config.primary_source)
    primary_rows = _normalize_source(primary, audits)
    join_target = (primary.join or primary.key).target
    others = {}
    for s in config.sources:
        if s.name == primary.name:
            continue
        index: dict = {}
        for r in _normalize_source(s, audits):
            jk = r.get(join_target)
            if jk in (None, ""):
                audits.append(Audit(s.name, r["_row"], join_target, "A01", jk,
                                    f"對應鍵空白，無法與 {primary.name} 合併"))
                continue
            if jk in index:
                audits.append(Audit(s.name, r["_row"], join_target, "A02", jk,
                                    f"對應鍵重複（首次出現於第 {index[jk]['_row']} 列），"
                                    "無法判定應取哪一筆"))
                continue
            index[jk] = r
        others[s.name] = index

    key_target = primary.key.target
    for row in primary_rows:
        combined = {f"{primary.name}.{k}": v for k, v in row.items() if not k.startswith("_")}
        missing = []
        for name, index in others.items():
            match = index.get(row[join_target])
            if match is None:
                missing.append(name)
            else:
                combined.update({f"{name}.{k}": v for k, v in match.items()
                                 if not k.startswith("_")})
        if missing:
            audits.append(Audit(primary.name, row["_row"], join_target, "A07",
                                row[join_target], "對方報表查無此對應鍵：" + "、".join(missing)))
        combined["_key"] = row[key_target]
        combined["_row"] = row["_row"]
        merged.append(combined)

    blocked = [a for a in audits if a.blocking]
    result = {
        "project": config.project,
        "merged_rows": len(merged),
        "audit_total": len(audits),
        "audit_blocking": len(blocked),
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "status": "BLOCKED" if blocked else "OK",
    }

    workbook_written = None
    if blocked:
        result["halted"] = True
    else:
        merged.sort(key=lambda r: str(r["_key"]))
        balance = config.output.get("balance", {})
        dcol, ccol = balance.get("debit"), balance.get("credit")
        if dcol and ccol:
            accounts = [r for r in merged if r.get(dcol) is not None or r.get(ccol) is not None]
            debit = sum(r.get(dcol) or 0 for r in accounts)
            credit = sum(r.get(ccol) or 0 for r in accounts)
            if accounts and round(debit - credit, 2) != 0:
                audits.append(Audit("merged", 0, f"{dcol}/{ccol}", "A08",
                                    f"{debit}-{credit}",
                                    f"借貸不平衡，差額 {round(debit - credit, 2)}"))
                result["status"] = "WARN"
            result["debit_total"] = round(debit, 2)
            result["credit_total"] = round(credit, 2)
        result["audit_total"] = len(audits)
        workbook_written = _write_output(config, merged, primary.name)
        result["output"] = workbook_written

    if audit_path:
        _write_audit(audits, audit_path)
        result["audit_log"] = audit_path
    return result


def _resolve(name: str, keys: set[str], primary: str) -> str | None:
    """把客戶設定的欄位名解析為內部鍵（優先主來源，其次任一來源）。"""
    if name in keys:
        return name
    cand = f"{primary}.{name}"
    if cand in keys:
        return cand
    for k in sorted(keys):
        if k.endswith("." + name):
            return k
    return None


def _write_output(config: Config, merged: list[dict], primary: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    keys = {k for r in merged for k in r if not k.startswith("_")}
    requested = list(config.output.get("columns", []))
    pairs: list[tuple[str, str]] = []
    for name in requested:
        src = _resolve(name, keys, primary)
        if src:
            pairs.append((name, src))
    if not pairs:
        seen: list[str] = []
        for k in sorted(keys, key=lambda x: (not x.startswith(primary + "."), x)):
            short = k.split(".", 1)[1] if "." in k else k
            if short not in seen:
                seen.append(short)
                pairs.append((short, k))
    columns = [short for short, _ in pairs]
    wb = Workbook()
    ws = wb.active
    ws.title = str(config.output.get("sheet", "彙整總表"))[:31]
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(horizontal="center")
    for r in merged:
        ws.append([r.get(src) for _, src in pairs])
    for idx, col in enumerate(columns, start=1):
        if "日期" in col:
            for cell in ws[get_column_letter_safe(idx)][1:]:
                cell.number_format = "yyyy-mm-dd"
        if "金額" in col or "合計" in col:
            for cell in ws[get_column_letter_safe(idx)][1:]:
                cell.number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    for idx in range(1, len(columns) + 1):
        width = max(10, min(28, len(str(columns[idx - 1])) * 2 + 6))
        ws.column_dimensions[get_column_letter_safe(idx)].width = width
    out = config.output.get("path", "output/FinReport_彙整總表.xlsx")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    wb.save(out)
    wb.close()
    return out


def get_column_letter_safe(idx: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(idx)


def _write_audit(audits: list[Audit], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(AUDIT_COLUMNS)
        for a in audits:
            w.writerow(a.as_row())
