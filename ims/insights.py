"""Offline, rule-based insights (no cloud AI, no API key).

Flags students who need follow-up from three transparent signals: low
attendance, failed subjects in published results and overdue fees.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import attendance, fees


def at_risk_students(T, settings: dict, days: int = 60, include_fees: bool = True) -> pd.DataFrame:
    start = (date.today() - timedelta(days=days)).isoformat()
    att = attendance.percentages(T, start, date.today().isoformat())
    if att.empty:
        return pd.DataFrame()
    threshold = float(settings["attendance_threshold"])
    pass_pct = float(settings["pass_percent"])
    # Only the most recent term that has published results counts, so old
    # (already re-sat or superseded) papers do not keep flagging a student.
    latest = T.q1("""
        SELECT e.term_id FROM marksheets m JOIN exams e ON e.id=m.exam_id JOIN terms t ON t.id=e.term_id
        WHERE m.institution_id=:iid AND m.status='published' ORDER BY t.start_date DESC LIMIT 1
    """)
    fails = T.q("""
        SELECT r.student_id, COUNT(*) AS failed
        FROM results r JOIN marksheets m ON m.id=r.marksheet_id JOIN exams e ON e.id=r.exam_id
        WHERE r.institution_id=:iid AND m.status='published' AND r.is_exempt=0 AND e.term_id=:t
          AND (r.is_absent=1 OR 100.0 * IFNULL(r.obtained_marks,0) / r.max_marks < :p)
        GROUP BY r.student_id
    """, {"p": pass_pct, "t": latest["term_id"] if latest else -1})
    fail_map = {r["student_id"]: r["failed"] for r in fails}
    overdue_map = {}
    if include_fees:
        for inv in fees.invoices(T, "i.status='issued' AND i.due_date < :d", {"d": date.today().isoformat()}):
            if inv["balance"] > fees.EPS:
                overdue_map[inv["student_id"]] = overdue_map.get(inv["student_id"], 0) + inv["balance"]
    rows = []
    for r in att.itertuples():
        reasons, score = [], 0
        if pd.notna(r.percent) and r.percent < threshold:
            reasons.append(f"attendance {r.percent:.0f}%")
            score += 2 if r.percent < threshold - 15 else 1
        f = fail_map.get(r.student_id, 0)
        if f:
            reasons.append(f"{f} failed paper(s)")
            score += min(f, 3)
        due = overdue_map.get(r.student_id, 0)
        if due:
            reasons.append(f"overdue {settings['currency']} {due:,.0f}")
            score += 1
        if score:
            rows.append({"student_id": r.student_id, "Admission no": r.admission_no, "Student": r.student,
                         "Attendance %": r.percent, "Failed papers": f, "Overdue": round(due, 2),
                         "Risk": "High" if score >= 3 else "Medium" if score == 2 else "Low",
                         "Why": ", ".join(reasons), "score": score})
    df = pd.DataFrame(rows)
    return df.sort_values("score", ascending=False).drop(columns="score") if not df.empty else df


def collection_forecast(T, months: int = 6) -> pd.DataFrame:
    """Monthly collections plus a simple linear-trend projection for next month."""
    rows = T.q("""
        SELECT substr(payment_date,1,7) AS month, SUM(amount) AS collected
        FROM payments WHERE institution_id=:iid AND kind<>'credit_applied'
        GROUP BY month ORDER BY month DESC LIMIT :n
    """, {"n": months})
    df = pd.DataFrame(rows[::-1])
    if len(df) >= 2:
        n = len(df)
        xs = list(range(n))
        mx, my = sum(xs) / n, df["collected"].mean()
        denom = sum((x - mx) ** 2 for x in xs) or 1
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, df["collected"])) / denom
        df.attrs["next_month_estimate"] = max(0.0, my + slope * (n - mx))
    return df
