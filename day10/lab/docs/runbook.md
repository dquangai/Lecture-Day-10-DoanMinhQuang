# Runbook — Lab Day 10 (incident tối giản)

---

## Symptom

Agent / eval trả lời **"14 ngày"** hoàn tiền thay vì **7 ngày**, hoặc HR trả **10 ngày phép năm** thay vì **12 ngày**. User CS phản hồi policy sai dù model không đổi.

---

## Detection

| Signal | Cách phát hiện |
|--------|----------------|
| Eval | `python eval_retrieval.py` → `hits_forbidden=yes` hoặc `contains_expected=no` |
| Grading | `grading_run.jsonl` → `contains_expected=false` / `hits_forbidden=true` |
| Expectation | Log `expectation[refund_no_stale_14d_window] FAIL` → pipeline halt exit 2 |
| Freshness | Log `freshness_check=FAIL` — data snapshot cũ hơn SLA 24h |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Mở `artifacts/manifests/manifest_clean-final.json` | `run_id`, `cleaned_records=33`, `quarantine_records=214` |
| 2 | Mở `artifacts/quarantine/quarantine_<run-id>.csv` | Tìm `reason=stale_*`, `unknown_doc_id` |
| 3 | Chạy `python eval_retrieval.py --out artifacts/eval/after_fix_eval.csv` | So sánh `q_refund_window`, `q_hr_annual_leave_under3` |
| 4 | Kiểm tra log embed | Có `embed_prune_removed` sau inject — tránh vector cũ |

**Thứ tự debug:** Freshness → Volume (`raw/cleaned/quarantine`) → Schema/contract → Lineage (`run_id`) → retrieval.

---

## Mitigation

1. **Không** `--skip-validate` trên production run.
2. Rerun chuẩn: `python etl_pipeline.py run --run-id clean-final`
3. Verify: `python grading_run.py` + `instructor_quick_check.py --grading artifacts/eval/grading_run.jsonl`
4. Nếu vừa inject demo: bắt buộc rerun clean trước khi nộp grading.

---

## Prevention

- Giữ `refund_no_stale_14d_window` và `hr_leave_no_stale_10d_annual` ở severity **halt**.
- Mở rộng allowlist phải đồng bộ `cleaning_rules.py` + `contracts/data_contract.yaml`.
- Freshness FAIL trên CSV mẫu (`exported_at=2026-04-10`) là **chấp nhận được** trong lab — SLA 24h áp cho snapshot thật; ghi rõ trong monitor khi deploy production.
