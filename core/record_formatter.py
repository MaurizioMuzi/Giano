# core/record_formatter.py
import json
from pathlib import Path
from decimal import Decimal
from datetime import date, datetime


class RecordFormatter:
    def __init__(self, records_dir: str | Path):
        self.records_dir = Path(records_dir)
        self.layouts: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        for json_file in self.records_dir.glob("*.json"):
            with open(json_file, "r", encoding="utf-8") as f:
                schema = json.load(f)

            rec_type = schema.get("record_type") or json_file.stem
            expected_len = schema["record_length"]
            fields = schema["fields"]

            total_len = sum(meta["len"] for meta in fields.values())
            if total_len != expected_len:
                raise ValueError(f"[{json_file.name}] Lunghezza campi {total_len} != {expected_len}")

            self.layouts[rec_type] = {"record_length": expected_len, "fields": fields}

    def format(self, rec_type: str, data: dict) -> str:
        if rec_type not in self.layouts:
            raise KeyError(f"Tipo record '{rec_type}' non trovato in {self.records_dir}")

        layout = self.layouts[rec_type]
        parts = []

        for field_name, meta in layout["fields"].items():
            length = meta["len"]
            ltype = meta.get("logical_type", "string").lower()
            padding = meta.get("padding", True)
            val = data.get(field_name, meta.get("default"))

            parts.append(self._format_field(field_name, val, length, ltype, padding, meta))

        line = "".join(parts)
        if len(line) != layout["record_length"]:
            raise ValueError(f"Riga {rec_type} lunga {len(line)}, attesa {layout['record_length']}")
        return line

    def _format_field(self, name: str, val, length: int, ltype: str, padding: bool, meta: dict) -> str:
        if ltype in ("string", "char"):
            s = "" if val is None else str(val)[:length]
            return s.ljust(length, " ") if padding else s

        if ltype in ("int", "integer", "smallint", "bigint"):
            if isinstance(val, (date, datetime)):
                s = val.strftime("%Y%m%d")
            else:
                n = 0 if val is None or val == "" else int(val)
                s = str(abs(n))
            if len(s) > length:
                raise OverflowError(f"Campo '{name}': {val} supera {length} caratteri")
            return s.zfill(length) if padding else s

        if ltype in ("decimal", "numeric", "float"):
            decimals = meta.get("decimals", 2)
            d = Decimal("0") if val is None or val == "" else Decimal(str(val))
            s = str(abs(int(round(d * (10 ** decimals)))))
            if len(s) > length:
                raise OverflowError(f"Campo '{name}': {d} supera {length} caratteri")
            return s.zfill(length) if padding else s

        if ltype == "date":
            if not val or str(val) in ("01.01.0001", "0001-01-01"):
                return "0" * length if padding else ""
            s = val.strftime("%d%m%Y") if isinstance(val, (date, datetime)) else str(val).replace(".", "").replace("-", "").replace("/", "")
            s = s[:length]
            return s.zfill(length) if padding else s

        raise ValueError(f"Tipo non supportato '{ltype}' su campo '{name}'")