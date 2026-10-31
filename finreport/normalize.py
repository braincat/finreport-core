"""純規則正規化：金額、日期、文字。不呼叫任何外部服務。"""
from __future__ import annotations
import re
import datetime as _dt
import unicodedata

__all__ = ["normalize_text", "normalize_amount", "normalize_date", "NormalizeError"]


class NormalizeError(ValueError):
    """無法依規則正規化時拋出，由引擎轉為 Audit 記錄。"""


_FULLWIDTH_MAP = str.maketrans("０１２３４５６７８９．，－（）", "0123456789.,-()")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def normalize_text(value) -> str:
    """全形轉半形、去除前後空白、壓縮連續空白。"""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value)).translate(_FULLWIDTH_MAP)
    s = s.replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()


def normalize_amount(value) -> float:
    """金額正規化：容忍 $ , 空白 全形 負號寫法（-100 / (100) / 100-），回傳 float。

    規則（可歸責、可測試）：
      - 空字串 / None            -> NormalizeError("EMPTY")
      - 千分位逗號               -> 移除
      - 前置或後置負號、括號     -> 負數
      - 任何非數字符號           -> NormalizeError("NOT_NUMERIC")
    """
    s = normalize_text(value)
    if s == "":
        raise NormalizeError("EMPTY")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    s = s.replace("$", "").replace("NT", "").replace("NTD", "").strip()
    if s.endswith("-"):
        neg, s = True, s[:-1].strip()
    s = _THOUSANDS.sub("", s)
    s = s.replace(",", "")
    if s.startswith("-"):
        neg, s = True, s[1:].strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        raise NormalizeError("NOT_NUMERIC")
    val = float(s)
    return -val if neg else val


_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$"), "ymd"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), "ymd"),
    (re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$"), "mdy"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$"), "ymd"),
    (re.compile(r"^(\d{3})[-/.](\d{1,2})[-/.](\d{1,2})$"), "roc"),
]
_ROC_OFFSET = 1911


def normalize_date(value) -> str:
    """日期正規化為 ISO YYYY-MM-DD。支援 2026-10-30 / 2026/10/30 / 20261030 /
    10/30/2026 / 2026年10月30日 / 民國 115/10/30 / Excel 序號。"""
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    s = normalize_text(value)
    if s == "":
        raise NormalizeError("EMPTY")
    if re.fullmatch(r"\d{5}(?:\.0+)?", s):
        n = int(float(s))
        if 20000 <= n <= 80000:
            base = _dt.date(1899, 12, 30)
            return (base + _dt.timedelta(days=n)).isoformat()
    for pat, kind in _DATE_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        if kind == "ymd":
            y, mo, d = a, b, c
        elif kind == "mdy":
            y, mo, d = c, a, b
        else:  # roc
            y, mo, d = a + _ROC_OFFSET, b, c
        try:
            return _dt.date(y, mo, d).isoformat()
        except ValueError:
            raise NormalizeError("INVALID_DATE")
    raise NormalizeError("UNRECOGNIZED_DATE")
