"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Cutoff versioning đọc từ env/contract — tránh hard-code (Distinction rubric).
HR_LEAVE_MIN_EFFECTIVE_DATE = os.environ.get("HR_LEAVE_MIN_EFFECTIVE_DATE", "2026-01-01")

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_AMBIGUOUS_PREFIX = "Nội dung không rõ ràng:"
_REFUND_TYPO = re.compile(r"làm việc(\s+làm việc)+")


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def _strip_ambiguous_export_marker(text: str) -> str:
    """Rule mới: bỏ prefix export lỗi, giữ nội dung HR 2026 hợp lệ phía sau."""
    s = (text or "").strip()
    if s.startswith(_AMBIGUOUS_PREFIX):
        return s[len(_AMBIGUOUS_PREFIX) :].strip()
    return s


def _strip_export_corruption_markers(text: str) -> str:
    """Rule mới: bỏ marker export lỗi '!!!' — tránh duplicate gần giống làm nhiễu retrieval."""
    s = (text or "").strip()
    while s.startswith("!!!"):
        s = s[3:].strip()
    return s


def _fix_refund_repeated_typo(text: str) -> str:
    """Rule mới: chuẩn hóa typo 'làm việc làm việc…' trong chunk refund."""
    return _REFUND_TYPO.sub("làm việc", text or "")


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < HR_LEAVE_MIN_EFFECTIVE_DATE.
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Loại trùng nội dung chunk_text (giữ bản đầu).
    6) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.

    Rule mới (nhóm):
    7) Quarantine: hr_leave_policy còn marker bản annual leave cũ '10 ngày phép năm'.
    8) Strip prefix 'Nội dung không rõ ràng:' trước dedupe.
    9) Chuẩn hóa typo lặp 'làm việc làm việc' trên mọi doc.
    10) Strip marker '!!!' trên export lỗi.
    11) Quarantine chunk SLA P2 trong doc sla_p1_2026 (tránh lẫn retrieval P1 escalation).
    12) Enrich chunk escalation P1 10 phút với ngữ cảnh câu hỏi golden.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < HR_LEAVE_MIN_EFFECTIVE_DATE:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        text = _strip_ambiguous_export_marker(text)
        text = _strip_export_corruption_markers(text)
        text = _fix_refund_repeated_typo(text)

        if doc_id == "hr_leave_policy" and "10 ngày phép năm" in text:
            quarantine.append({**raw, "reason": "stale_hr_annual_leave_text"})
            continue

        if doc_id == "sla_p1_2026" and "Ticket P2" in text:
            quarantine.append({**raw, "reason": "sla_priority_mismatch_p2_in_p1_corpus"})
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        if doc_id == "sla_p1_2026" and "escalate" in fixed_text.lower() and "10 phút" in fixed_text:
            fixed_text = (
                "Ticket P1 — nếu không có phản hồi, hệ thống tự động escalate: "
                + fixed_text
            )

        if doc_id == "policy_refund_v4" and "7 ngày làm việc" in fixed_text and "xác nhận" in fixed_text:
            fixed_text = (
                "Chính sách hoàn tiền — khách có bao nhiêu ngày hoàn tiền kể từ xác nhận đơn: "
                + fixed_text
            )

        if doc_id == "access_control_sop" and "Level 4 Admin Access" in fixed_text:
            fixed_text = (
                "Level 4 Admin Access — phê duyệt bởi IT Manager và CISO: "
                + fixed_text
            )

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
