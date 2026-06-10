# Data contract — Lab Day 10

> Đồng bộ với `contracts/data_contract.yaml` · Owner: **AI in Action — Nhóm DoanMinhQuang**

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `policy_refund_v4` | CSV batch export | Chunk stale **14 ngày**; typo lặp | `expectation[refund_no_stale_14d_window]` halt; eval `hits_forbidden` |
| `sla_p1_2026` | CSV batch export | Duplicate; chunk **P2** lẫn P1 | Quarantine `sla_priority_mismatch_p2`; retrieval top-k sai escalation |
| `it_helpdesk_faq` | CSV batch export | Chunk rỗng; duplicate | `missing_chunk_text`; dedupe quarantine |
| `hr_leave_policy` | CSV batch export | Version **10 vs 12 ngày phép**; date < 2026 | `HR_LEAVE_MIN_EFFECTIVE_DATE`; `stale_hr_annual_leave_text` |
| `access_control_sop` | CSV batch export | Thiếu trong allowlist baseline | `all_allowed_docs_present` halt; grading `gq_d10_10` fail |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| chunk_id | string | Có | SHA256 16 ký tự + seq |
| doc_id | string | Có | Thuộc `allowed_doc_ids` trong contract |
| chunk_text | string | Có | min 8 ký tự; đã strip marker export |
| effective_date | date (ISO) | Có | `YYYY-MM-DD` sau normalize |
| exported_at | datetime | Có | Dùng freshness SLA trên manifest |

---

## 3. Quy tắc quarantine vs drop

- Record lỗi → **`artifacts/quarantine/quarantine_<run-id>.csv`** kèm cột `reason` (không drop im lặng).
- Lý do phổ biến: `unknown_doc_id`, `stale_hr_policy_effective_date`, `duplicate_chunk_text`, `sla_priority_mismatch_p2_in_p1_corpus`.
- Merge lại: SME/owner review quarantine CSV → sửa nguồn hoặc cập nhật rule → rerun pipeline với `run_id` mới.

---

## 4. Phiên bản & canonical

| Chính sách | Source of truth | Version cutoff |
|------------|-----------------|----------------|
| Refund | `data/docs/policy_refund_v4.txt` | Cửa sổ **7 ngày làm việc** (v4) |
| HR leave | `data/docs/hr_leave_policy.txt` | `effective_date >= 2026-01-01` (env `HR_LEAVE_MIN_EFFECTIVE_DATE`) |
| SLA P1 | `data/docs/sla_p1_2026.txt` | doc_id `sla_p1_2026` |
| Access | `data/docs/access_control_sop.txt` | doc_id `access_control_sop` |
