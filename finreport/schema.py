"""Schema 設定檔載入與驗證（Tier 2 客戶配置層，JSON 可交付客戶自行修改）。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field

VALID_TYPES = {"text", "amount", "date", "int"}
VALID_ROLES = {"key", "join", "amount", "date", "output", "ignore"}


class SchemaError(ValueError):
    pass


@dataclass
class Column:
    source: str
    target: str
    type: str = "text"
    role: str = "output"
    required: bool = False


@dataclass
class SourceSpec:
    name: str
    path: str
    sheet: str | None = None
    header_row: int = 1
    columns: list[Column] = field(default_factory=list)

    @property
    def key(self) -> Column | None:
        """唯一性主鍵；未宣告 key 時，以 join 欄位作為唯一性判斷依據。"""
        for c in self.columns:
            if c.role == "key":
                return c
        for c in self.columns:
            if c.role == "join":
                return c
        return None

    @property
    def join(self) -> Column | None:
        for c in self.columns:
            if c.role == "join":
                return c
        return None


@dataclass
class Config:
    project: str
    primary_source: str
    sources: list[SourceSpec]
    output: dict

    def source(self, name: str) -> SourceSpec:
        for s in self.sources:
            if s.name == name:
                return s
        raise SchemaError(f"找不到來源設定：{name}")


def _column(raw: dict) -> Column:
    if "source" not in raw:
        raise SchemaError("欄位設定缺少 source")
    col = Column(
        source=str(raw["source"]),
        target=str(raw.get("target", raw["source"])),
        type=str(raw.get("type", "text")),
        role=str(raw.get("role", "output")),
        required=bool(raw.get("required", False)),
    )
    if col.type not in VALID_TYPES:
        raise SchemaError(f"未知型別 {col.type}（欄位 {col.source}）")
    if col.role not in VALID_ROLES:
        raise SchemaError(f"未知角色 {col.role}（欄位 {col.source}）")
    return col


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    sources = []
    for s in raw.get("sources", []):
        spec = SourceSpec(
            name=str(s["name"]),
            path=str(s["path"]),
            sheet=s.get("sheet"),
            header_row=int(s.get("header_row", 1)),
            columns=[_column(c) for c in s.get("columns", [])],
        )
        if spec.key is None:
            raise SchemaError(f"來源 {spec.name} 未定義 key 欄位，無法合併")
        if not spec.columns:
            raise SchemaError(f"來源 {spec.name} 沒有任何欄位設定")
        sources.append(spec)
    if not sources:
        raise SchemaError("設定檔沒有任何來源")
    primary = str(raw.get("primary_source", sources[0].name))
    if primary not in {s.name for s in sources}:
        raise SchemaError(f"primary_source 不存在：{primary}")
    return Config(
        project=str(raw.get("project", "未命名專案")),
        primary_source=primary,
        sources=sources,
        output=dict(raw.get("output", {})),
    )
