"""CSV / Excel exports that carry the institution name, report title and date."""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from openpyxl.styles import Font


def _heading(inst: dict, title: str) -> list[str]:
    return [inst["name"], title, f"Generated {datetime.now():%Y-%m-%d %H:%M}"]


def csv_bytes(inst: dict, title: str, df: pd.DataFrame) -> bytes:
    out = io.StringIO()
    for line in _heading(inst, title):
        out.write(f"\"{line.replace(chr(34), chr(39))}\"\n")
    out.write("\n")
    df.to_csv(out, index=False)
    return out.getvalue().encode("utf-8-sig")


def xlsx_bytes(inst: dict, title: str, df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, startrow=4, sheet_name="Report")
        ws = xw.sheets["Report"]
        for i, line in enumerate(_heading(inst, title), 1):
            ws.cell(row=i, column=1, value=line)
        ws.cell(row=1, column=1).font = Font(bold=True, size=14)
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col[4:]) if len(col) > 4 else 10
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 48)
    return buf.getvalue()


def safe_filename(text: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text.strip())
    return "_".join(filter(None, keep.split("_")))[:80] or "export"
