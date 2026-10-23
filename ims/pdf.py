"""Printable PDFs branded with the institution name and logo (ReportLab)."""
from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import MAKER_LINE, branding
from .profiles import ACCENTS, PROFILES

_styles = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=9.5, leading=13)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontSize=13, spaceBefore=4, spaceAfter=6)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.5, leading=10.5)


def _txt(value) -> str:
    """Escape for ReportLab markup and drop characters the base fonts can't draw."""
    s = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    s = s.replace("→", "->").replace("×", "x").replace("—", "-").replace("–", "-")
    return escape(s.encode("cp1252", "replace").decode("cp1252"))


def _fmt_date(value, settings) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime(settings["date_format"])
    except ValueError:
        return str(value)


class Brand:
    def __init__(self, inst: dict, settings: dict):
        self.inst = inst
        self.settings = settings
        self.name = inst["name"]
        self.kind = PROFILES[inst["institution_type"]]["title"]
        self.accent = colors.HexColor(ACCENTS.get(settings.get("accent"), ACCENTS["Indigo"])[0])
        self.logo = branding.logo_bytes(inst, settings.get("accent", "Indigo"))
        bits = [inst.get("address"), inst.get("phone"), inst.get("email"), inst.get("website")]
        self.contact = "  |  ".join(b for b in bits if b)

    def header_footer(self, canvas, doc):
        w, h = doc.pagesize
        canvas.saveState()
        top = h - 14 * mm
        canvas.drawImage(ImageReader(io.BytesIO(self.logo)), 14 * mm, top - 14 * mm, 16 * mm, 16 * mm,
                         mask="auto", preserveAspectRatio=True)
        canvas.setFillColor(colors.HexColor("#111827"))
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(34 * mm, top - 4 * mm, _plain(self.name))
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#4b5563"))
        canvas.drawString(34 * mm, top - 9 * mm, _plain(self.kind + (f"  |  {self.inst['motto']}" if self.inst.get("motto") else "")))
        if self.contact:
            canvas.drawString(34 * mm, top - 13 * mm, _plain(self.contact)[:140])
        canvas.setStrokeColor(self.accent)
        canvas.setLineWidth(2)
        canvas.line(14 * mm, top - 17 * mm, w - 14 * mm, top - 17 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(14 * mm, 9 * mm, _plain(f"{self.name}  |  Generated {datetime.now().strftime(self.settings['date_format'] + ' %H:%M')}"))
        canvas.drawRightString(w - 14 * mm, 9 * mm, f"Page {doc.page}")
        canvas.drawCentredString(w / 2, 5 * mm, _plain(MAKER_LINE))
        canvas.restoreState()


def _plain(s: str) -> str:
    return str(s).encode("cp1252", "replace").decode("cp1252")


def _build(brand: Brand, story: list, pagesize=A4, title="Document") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, topMargin=38 * mm, bottomMargin=16 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm, title=title, author=brand.name, creator=MAKER_LINE)
    doc.build(story, onFirstPage=brand.header_footer, onLaterPages=brand.header_footer)
    return buf.getvalue()


def _grid(data, widths=None, header=True, accent=colors.HexColor("#4f46e5"), zebra=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("FONTSIZE", (0, 0), (-1, -1), 8.5),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), accent), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        if zebra:
            for i in range(1, len(data)):
                if i % 2 == 0:
                    style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f4f6")))
    t.setStyle(TableStyle(style))
    return t


def _kv(pairs, widths=(38 * mm, 52 * mm, 38 * mm, 52 * mm)):
    """Two key/value pairs per row."""
    rows = []
    for i in range(0, len(pairs), 2):
        row = []
        for k, v in pairs[i:i + 2]:
            row += [Paragraph(f"<b>{_txt(k)}</b>", CELL), Paragraph(_txt(v), CELL)]
        while len(row) < 4:
            row.append("")
        rows.append(row)
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                           ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9fafb")),
                           ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f9fafb")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _title(text: str, sub: str = "") -> list:
    out = [Paragraph(_txt(text), H2)]
    if sub:
        out.append(Paragraph(_txt(sub), SMALL))
    out.append(Spacer(1, 4 * mm))
    return out


def _money(v, cur) -> str:
    return f"{cur} {float(v):,.2f}"


# --------------------------------------------------------------------------- #
# Generic table report
# --------------------------------------------------------------------------- #
def table_pdf(inst, settings, title: str, df: pd.DataFrame, subtitle: str = "") -> bytes:
    brand = Brand(inst, settings)
    df = df.copy()
    wide = len(df.columns) > 7
    size = landscape(A4) if wide else A4
    usable = size[0] - 28 * mm
    head = [Paragraph(f"<b>{_txt(c)}</b>", ParagraphStyle("hc", parent=CELL, textColor=colors.white))
            for c in df.columns]
    body = [[Paragraph(_txt(v), CELL) for v in row] for row in df.itertuples(index=False)]
    story = _title(title, subtitle or f"{len(df)} record(s)")
    if body:
        story.append(_grid([head] + body, [usable / max(len(df.columns), 1)] * len(df.columns),
                           accent=brand.accent))
    else:
        story.append(Paragraph("No records.", BODY))
    return _build(brand, story, size, title)


# --------------------------------------------------------------------------- #
# Finance documents
# --------------------------------------------------------------------------- #
def invoice_pdf(T, inst, settings, inv: dict, student: dict, class_name: str) -> bytes:
    brand = Brand(inst, settings)
    cur = settings["currency"]
    items = T.all("invoice_items", "invoice_id=?", (inv["id"],))
    pays = T.all("payments", "invoice_id=?", (inv["id"],), order="payment_date, id")
    story = _title(f"Fee invoice {inv['invoice_no']}",
                   "CANCELLED - " + (inv["cancelled_reason"] or "") if inv["status"] == "cancelled" else "")
    story.append(_kv([("Student", f"{student['first_name']} {student['last_name'] or ''}"),
                      ("Admission no", student["admission_no"]),
                      ("Class / program", class_name), ("Period", inv["period_label"] or "-"),
                      ("Issue date", _fmt_date(inv["issue_date"], settings)),
                      ("Due date", _fmt_date(inv["due_date"], settings))]))
    story.append(Spacer(1, 5 * mm))
    rows = [["#", "Description", "Amount"]]
    for i, it in enumerate(items, 1):
        rows.append([str(i), Paragraph(_txt(it["description"]), CELL), _money(it["amount"], cur)])
    rows += [["", "Total", _money(inv["total"], cur)], ["", "Paid", _money(inv["paid"], cur)],
             ["", "Balance due", _money(inv["balance"], cur)]]
    t = _grid(rows, [12 * mm, 120 * mm, 50 * mm], accent=brand.accent, zebra=False)
    t.setStyle(TableStyle([("ALIGN", (2, 0), (2, -1), "RIGHT"),
                           ("FONTNAME", (1, -3), (-1, -1), "Helvetica-Bold"),
                           ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2ff"))]))
    story.append(t)
    if pays:
        story += [Spacer(1, 5 * mm), Paragraph("<b>Payment history</b>", BODY), Spacer(1, 2 * mm)]
        prow = [["Receipt", "Date", "Type", "Method", "Amount"]]
        for p in pays:
            prow.append([p["receipt_no"], _fmt_date(p["payment_date"], settings), p["kind"].replace("_", " "),
                         p["method"], _money(p["amount"], cur)])
        story.append(_grid(prow, [38 * mm, 30 * mm, 34 * mm, 40 * mm, 40 * mm], accent=brand.accent))
    if inv.get("notes"):
        story += [Spacer(1, 4 * mm), Paragraph(f"<b>Notes:</b> {_txt(inv['notes'])}", SMALL)]
    return _build(brand, story, A4, f"Invoice {inv['invoice_no']}")


def receipt_pdf(T, inst, settings, pay: dict, inv: dict, student: dict, recorded_by: str) -> bytes:
    brand = Brand(inst, settings)
    cur = settings["currency"]
    title = "Payment reversal" if pay["kind"] == "reversal" else "Payment receipt"
    story = _title(f"{title} {pay['receipt_no']}")
    credit = T.scalar("SELECT IFNULL(SUM(amount),0) AS v FROM student_credits WHERE institution_id=:iid "
                      "AND payment_id=:p AND kind='overpayment'", {"p": pay["id"]}) or 0
    pairs = [("Student", f"{student['first_name']} {student['last_name'] or ''}"),
             ("Admission no", student["admission_no"]), ("Invoice", inv["invoice_no"]),
             ("Payment date", _fmt_date(pay["payment_date"], settings)),
             ("Method", pay["method"]), ("Reference", pay["reference"] or "-"),
             ("Amount applied", _money(pay["amount"], cur)),
             ("Advance credit kept", _money(credit, cur)),
             ("Invoice total", _money(inv["total"], cur)), ("Remaining balance", _money(inv["balance"], cur)),
             ("Recorded by", recorded_by), ("Status", "REVERSED" if pay["is_reversed"] else "Valid")]
    if pay["kind"] == "reversal":
        pairs.append(("Reason", pay["reason"] or "-"))
    story.append(_kv(pairs))
    story += [Spacer(1, 10 * mm),
              Paragraph(f"Received with thanks: <b>{_txt(_money(pay['amount'] + credit, cur))}</b>", BODY),
              Spacer(1, 16 * mm),
              Paragraph("______________________<br/>Authorised signature", SMALL)]
    return _build(brand, story, A4, f"Receipt {pay['receipt_no']}")


# --------------------------------------------------------------------------- #
# Academic documents
# --------------------------------------------------------------------------- #
def report_card_pdf(inst, settings, student: dict, class_name: str, term_name: str, report: dict,
                    attendance_pct=None) -> bytes:
    brand = Brand(inst, settings)
    profile = PROFILES[inst["institution_type"]]
    story = _title(f"{profile['result_doc']} - {term_name}")
    story.append(_kv([("Student", f"{student['first_name']} {student['last_name'] or ''}"),
                      ("Admission no", student["admission_no"]), (profile["class"], class_name),
                      ("Attendance", f"{attendance_pct:.1f}%" if attendance_pct is not None else "-")]))
    story.append(Spacer(1, 5 * mm))
    head = ["Subject" if not profile["gpa"] else "Course", "Obtained", "Max", "%", "Grade"]
    if profile["credit_hours"]:
        head.insert(1, "Cr.")
    rows = [head]
    for l in report["lines"]:
        r = [Paragraph(_txt(f"{l['subject']}{' (' + l['code'] + ')' if l['code'] else ''}"), CELL),
             f"{l['obtained']:g}" if l["percent"] is not None else "-",
             f"{l['max']:g}" if l["percent"] is not None else "-",
             f"{l['percent']:.1f}" if l["percent"] is not None else "EX", l["grade"]]
        if profile["credit_hours"]:
            r.insert(1, f"{l['credit_hours']:g}")
        rows.append(r)
    widths = [80 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm]
    if profile["credit_hours"]:
        widths = [70 * mm, 14 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm]
    story.append(_grid(rows, widths, accent=brand.accent))
    story.append(Spacer(1, 5 * mm))
    summary = [("Overall %", f"{report['percent']:.2f}" if report["percent"] is not None else "-"),
               ("Result", report["result"])]
    if profile["gpa"]:
        summary.insert(1, ("GPA", f"{report['gpa']:.2f}" if report["gpa"] is not None else "-"))
    if report["failed"]:
        summary.append(("Subjects to re-sit", ", ".join(report["failed"])))
    story.append(_kv(summary))
    story += [Spacer(1, 18 * mm), _signatures()]
    return _build(brand, story, A4, f"{profile['result_doc']} {student['admission_no']}")


def transcript_pdf(inst, settings, student: dict, program_name: str, tr: dict) -> bytes:
    brand = Brand(inst, settings)
    story = _title("Academic transcript")
    story.append(_kv([("Student", f"{student['first_name']} {student['last_name'] or ''}"),
                      ("Registration no", student["admission_no"]), ("Program", program_name or "-"),
                      ("Status", student["status"].replace("_", " ").title()),
                      ("CGPA", f"{tr['cgpa']:.2f}" if tr["cgpa"] is not None else "-"),
                      ("Standing", tr["standing"] or "-"),
                      ("Credits earned", f"{tr['credits_earned']:g}")]))
    for t in tr["terms"]:
        rep = t["report"]
        rows = [["Code", "Course", "Cr.", "%", "Grade", "Points"]]
        for l in rep["lines"]:
            rows.append([l["code"] or "-", Paragraph(_txt(l["subject"]), CELL), f"{l['credit_hours']:g}",
                         f"{l['percent']:.1f}" if l["percent"] is not None else "EX", l["grade"],
                         f"{l['point']:.2f}" if l["point"] is not None else "-"])
        label = f"{t['term']['name']} ({t['term']['year'] or ''})"
        footer = (f"Semester GPA: {rep['gpa']:.2f}" if rep["gpa"] is not None else "Semester GPA: -") + \
                 (f"   |   Cumulative GPA: {t['cgpa']:.2f}" if t["cgpa"] is not None else "") + \
                 f"   |   Credits: {t['earned']:g}/{t['credits']:g}"
        story.append(KeepTogether([Spacer(1, 5 * mm), Paragraph(f"<b>{_txt(label)}</b>", BODY), Spacer(1, 2 * mm),
                                   _grid(rows, [22 * mm, 78 * mm, 14 * mm, 20 * mm, 20 * mm, 22 * mm],
                                         accent=brand.accent),
                                   Spacer(1, 1.5 * mm), Paragraph(_txt(footer), SMALL)]))
    if not tr["terms"]:
        story.append(Paragraph("No published results yet.", BODY))
    story += [Spacer(1, 16 * mm), _signatures(("Registrar", "Controller of examinations"))]
    return _build(brand, story, A4, f"Transcript {student['admission_no']}")


def _signatures(labels=("Class teacher", "Principal")):
    t = Table([["______________________", "______________________"], list(labels)],
              colWidths=[90 * mm, 90 * mm])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 8.5)]))
    return t


def id_card_pdf(inst, settings, student: dict, class_name: str, photo: bytes | None) -> bytes:
    """Credit-card sized student ID (85.6 × 54 mm)."""
    brand = Brand(inst, settings)
    buf = io.BytesIO()
    from reportlab.pdfgen import canvas as rl_canvas
    w, h = 85.6 * mm, 54 * mm
    c = rl_canvas.Canvas(buf, pagesize=(w, h))
    c.setFillColor(brand.accent)
    c.rect(0, h - 14 * mm, w, 14 * mm, stroke=0, fill=1)
    c.drawImage(ImageReader(io.BytesIO(brand.logo)), 3 * mm, h - 12.5 * mm, 11 * mm, 11 * mm, mask="auto")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(16 * mm, h - 7 * mm, _plain(brand.name)[:38])
    c.setFont("Helvetica", 6.5)
    c.drawString(16 * mm, h - 11 * mm, "STUDENT IDENTITY CARD")
    pic = photo or branding.monogram_png(f"{student['first_name']} {student['last_name'] or ''}",
                                          settings.get("accent", "Indigo"))
    c.drawImage(ImageReader(io.BytesIO(pic)), 4 * mm, 6 * mm, 22 * mm, 26 * mm, mask="auto",
                preserveAspectRatio=True)
    c.setFillColor(colors.HexColor("#111827"))
    y = h - 20 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(30 * mm, y, _plain(f"{student['first_name']} {student['last_name'] or ''}")[:30])
    c.setFont("Helvetica", 7)
    for label, val in (("Adm. no", student["admission_no"]), ("Class", class_name),
                       ("DOB", _fmt_date(student["dob"], settings)), ("Blood", student.get("blood_group") or "-"),
                       ("Emergency", student.get("emergency_contact") or student.get("phone") or "-")):
        y -= 4.2 * mm
        c.drawString(30 * mm, y, _plain(f"{label}: {val}")[:44])
    c.setFont("Helvetica", 5.5)
    c.setFillColor(colors.HexColor("#6b7280"))
    c.drawString(4 * mm, 2.5 * mm, _plain(f"If found, please return to {brand.name}")[:70])
    c.showPage()
    c.save()
    return buf.getvalue()


def admission_form_pdf(inst, settings, student: dict, guardians: list[dict], class_name: str,
                       photo: bytes | None = None) -> bytes:
    brand = Brand(inst, settings)
    story = _title("Admission form", f"Admission no {student['admission_no']}")
    if photo:
        story.append(Image(io.BytesIO(photo), 25 * mm, 30 * mm, kind="proportional"))
        story.append(Spacer(1, 3 * mm))
    story.append(_kv([("First name", student["first_name"]), ("Last name", student["last_name"] or "-"),
                      ("Gender", student["gender"] or "-"), ("Date of birth", _fmt_date(student["dob"], settings)),
                      ("Class / program", class_name), ("Admission date", _fmt_date(student["admission_date"], settings)),
                      ("Phone", student["phone"] or "-"), ("Email", student["email"] or "-"),
                      ("Address", student["address"] or "-"), ("Previous school", student["previous_school"] or "-"),
                      ("Emergency contact", student["emergency_contact"] or "-"), ("Category", student["category"] or "-")]))
    story += [Spacer(1, 5 * mm), Paragraph("<b>Guardians</b>", BODY), Spacer(1, 2 * mm)]
    rows = [["Name", "Relationship", "Phone", "Email", "Primary"]]
    for g in guardians:
        rows.append([Paragraph(_txt(g["name"]), CELL), g.get("relationship") or "-", g.get("phone") or "-",
                     Paragraph(_txt(g.get("email") or "-"), CELL), "Yes" if g.get("is_primary") else ""])
    if len(rows) == 1:
        rows.append(["-", "", "", "", ""])
    story.append(_grid(rows, [50 * mm, 30 * mm, 35 * mm, 50 * mm, 17 * mm], accent=brand.accent))
    story += [Spacer(1, 18 * mm), _signatures(("Parent / guardian", "Admission officer"))]
    return _build(brand, story, A4, f"Admission form {student['admission_no']}")


def notice_pdf(inst, settings, notice: dict, author: str) -> bytes:
    brand = Brand(inst, settings)
    story = _title(notice["title"], f"Circular dated {_fmt_date(notice['created_at'], settings)}"
                                    f"  |  Audience: {notice['audience']}")
    for para in str(notice["body"]).split("\n"):
        story.append(Paragraph(_txt(para) or "&nbsp;", BODY))
    story += [Spacer(1, 14 * mm), Paragraph(f"Issued by: {_txt(author)}", SMALL)]
    return _build(brand, story, A4, notice["title"])
