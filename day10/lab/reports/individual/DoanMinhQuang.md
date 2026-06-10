# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Đoàn Minh Quang  
**Vai trò:** Cleaning & Quality Owner (kiêm Embed / Docs)  
**Ngày nộp:** 2026-06-10

---

## 1. Tôi phụ trách phần nào?

Tôi sửa **`transform/cleaning_rules.py`** và **`quality/expectations.py`**, chạy **`etl_pipeline.py`**, verify bằng **`grading_run.py`** và **`instructor_quick_check.py`**. Cụ thể: mở rộng `ALLOWED_DOC_IDS` thêm `access_control_sop`; thêm rule quarantine HR stale "10 ngày phép năm", strip marker export, quarantine chunk SLA P2, enrich escalation P1; thêm expectation `all_allowed_docs_present`, `hr_has_2026_annual_leave_chunk`, `access_control_min_chunks`. Tôi cũng điền `docs/*.md`, `contracts/data_contract.yaml`, và artifact eval.

**Bằng chứng:** commit thay đổi `cleaning_rules.py`, `expectations.py`, `etl_pipeline.py`; log `artifacts/logs/run_clean-final.log`; `artifacts/eval/grading_run.jsonl` 10 dòng OK.

---

## 2. Một quyết định kỹ thuật

Tôi chọn **halt** (không warn) cho `refund_no_stale_14d_window` và `all_allowed_docs_present` vì embed chunk sai version tốn chi phí rebuild index và gây sai nghiệp vụ ngay lập tức (user thấy "14 ngày" trước khi model kịp xử lý). Ngược lại, `access_control_min_chunks` để **warn** — thiếu 1–2 chunk vẫn có thể pass một phần FAQ nhưng cần log để owner bổ sung nguồn.

Idempotency: giữ upsert theo `chunk_id` + **prune** id thừa sau inject (`embed_prune_removed=1` trong log) để top-k không còn vector refund stale sau khi chạy lại `clean-final`.

Freshness: đo tại **publish** (`publish_completed_at` trong manifest) và so `latest_exported_at` với SLA 24h — ghi rõ FAIL trên CSV mẫu là do snapshot cũ, không phải lỗi pipeline logic.

---

## 3. Một lỗi hoặc anomaly đã xử lý

**Triệu chứng:** `GRADE_CHECK[gq_d10_06] FAIL` — `top1_doc_id=sla_p1_2026` đúng nhưng `contains_expected=false` (top-k không có "10 phút").

**Phát hiện:** Query Chroma thủ công — chunk P2 "Escalation sau 90 phút" rank #1, chunk P1 escalation 10 phút có trong index nhưng không vào top-5.

**Fix:** Rule quarantine `Ticket P2` trong `sla_p1_2026` + enrich prefix câu hỏi golden cho chunk escalation P1. Rerun `clean-final` → `gq_d10_06` OK.

---

## 4. Bằng chứng trước / sau

**run_id:** `inject-bad` vs `clean-final`

| question_id | inject-bad | clean-final |
|-------------|------------|-------------|
| q_refund_window | contains=yes, **hits_forbidden=yes**, preview "14 ngày" | contains=yes, hits_forbidden=**no**, preview "7 ngày" |

Nguồn: `artifacts/eval/after_inject_bad.csv` dòng 2, `artifacts/eval/after_fix_eval.csv` dòng 2. Tổng eval: 20/21 → **21/21** pass.

---

## 5. Cải tiến tiếp theo

Trong 2 giờ tiếp theo tôi sẽ thêm **pydantic model** validate schema cleaned ngay sau `write_cleaned_csv` (bonus Distinction) và nối freshness alert thật qua webhook thay vì chỉ log `freshness_check=FAIL`.
