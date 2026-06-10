# Quality report — Lab Day 10 (nhóm)

**run_id:** `clean-final` (sau fix) · `inject-bad` (corruption demo)  
**Ngày:** 2026-06-10

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước (baseline thiếu access + SLA fix) | Sau (`clean-final`) | Ghi chú |
|--------|----------------------------------------|---------------------|---------|
| raw_records | 247 | 247 | CSV cố định |
| cleaned_records | ~28 (thiếu access_control) | **33** | +5 doc access + SLA enrich |
| quarantine_records | ~219 | **214** | Thêm rule P2/HR stale |
| Expectation halt? | Có thể pass nhưng grading fail | **Không** (exit 0) | 9 expectations OK |

---

## 2. Before / after retrieval

**File:** `artifacts/eval/after_inject_bad.csv` vs `artifacts/eval/after_fix_eval.csv`

**Câu then chốt — refund (`q_refund_window`):**

| | top1_preview | contains_expected | hits_forbidden |
|--|--------------|-------------------|----------------|
| **Trước** (`inject-bad`, `--no-refund-fix`) | …14 ngày làm việc… | yes | **yes** |
| **Sau** (`clean-final`) | …7 ngày làm việc… | yes | **no** |

**HR versioning — `q_hr_annual_leave_under3`:**

| | contains_expected | hits_forbidden | top1_doc_expected |
|--|-------------------|----------------|-------------------|
| inject-bad | yes | no | yes |
| clean-final | yes | no | yes |

*(HR đã sạch trước inject; refund là case thay đổi rõ nhất.)*

**Tổng eval 21 câu:** inject **20/21** pass · clean **21/21** pass.

**Grading:** `artifacts/eval/grading_run.jsonl` — 10/10 `GRADE_CHECK` OK.

---

## 3. Freshness & monitor

```
freshness_check=FAIL age_hours=1470.863 sla_hours=24.0 reason=freshness_sla_exceeded
```

`latest_exported_at=2026-04-10` trong CSV mẫu — cũ hơn SLA 24h so với thời điểm chạy pipeline (2026-06-10). **FAIL hợp lý** cho lab; production cần đo tại boundary **publish** (`publish_completed_at` trong manifest) khi sync thật.

Manifest ghi 2 boundary: `ingest_completed_at` → `publish_completed_at` (log `artifacts/logs/run_clean-final.log`).

---

## 4. Corruption inject (Sprint 3)

**Lệnh:**

```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
```

**Cố ý:** tắt rule fix 14→7 ngày + bỏ qua expectation halt → embed chunk stale refund.

**Phát hiện:**

- Log: `expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1`
- Eval: `q_refund_window` → `hits_forbidden=yes`
- Manifest: `no_refund_fix=true`, `skipped_validate=true`

**Khôi phục:** rerun `clean-final` → expectation OK → grading 10/10.

---

## 5. Hạn chế & việc chưa làm

- Chưa tích hợp Great Expectations / pydantic validate schema cleaned (bonus).
- Freshness trên CSV mẫu luôn FAIL với SLA 24h — cần policy rõ snapshot vs live sync.
- Enrich escalation P1 bằng prefix text — cải thiện retrieval nhưng mang tính heuristic, chưa thay chunking theo heading PDF.
