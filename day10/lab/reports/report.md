# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** DoanMinhQuang  
**Thành viên:**

| Tên | Vai trò (Day 10) | MHV         |
|-----|------------------|-------------|
| Đoàn Minh Quang | Ingestion / Cleaning / Embed / Monitoring | 2A202600757 |

**Ngày nộp:** 2026-06-10  
**Repo:** `Lecture-Day-10-DoanMinhQuang/day10/lab`

---

## 1. Pipeline tổng quan

Nguồn raw là **`data/raw/policy_export_dirty.csv`** — export batch 247 dòng mô phỏng 5 hệ thống (refund, SLA, FAQ, HR, access). Pipeline `etl_pipeline.py` đọc CSV → `transform/cleaning_rules.py` (clean + quarantine) → `quality/expectations.py` (halt nếu fail) → embed Chroma collection `day10_kb` → ghi manifest + log.

**`run_id`** lấy từ tham số `--run-id` hoặc timestamp UTC; xuất hiện trong `artifacts/logs/run_<run-id>.log` và `artifacts/manifests/manifest_<run-id>.json`. Run chính thức: **`clean-final`**.

**Lệnh một dòng:**

```bash
python etl_pipeline.py run --run-id clean-final && python grading_run.py --out artifacts/eval/grading_run.jsonl
```

---

## 2. Cleaning & expectation

Baseline đã có allowlist, parse ngày ISO, dedupe, fix refund 14→7. Nhóm mở rộng thêm rule và expectation để pass grading 10 câu và chống trivial.

### 2a. Bảng metric_impact

| Rule / Expectation mới | Trước | Sau / khi inject | Chứng cứ |
|------------------------|-------|------------------|----------|
| `access_control_sop` vào allowlist | `missing_doc_ids=['access_control_sop']` halt | 6 chunk access trong cleaned | `manifest_clean-final.json`; `gq_d10_10` OK |
| `stale_hr_annual_leave_text` quarantine | HR chunk "10 ngày phép năm" trong index | 0 violation E6 | log `hr_leave_no_stale_10d_annual OK`; `gq_d10_09` OK |
| `sla_priority_mismatch_p2` quarantine | `gq_d10_06` FAIL (P2 90 phút top-1) | `gq_d10_06` OK | `grading_run.jsonl`; eval `q_p1_escalation` |
| Enrich escalation P1 + strip `!!!` | top-k thiếu "10 phút" | contains_expected=yes | `after_fix_eval.csv` |
| `all_allowed_docs_present` (E7) halt | thiếu doc sau clean | `missing_doc_ids=[]` | log run_clean-final |
| `refund_no_stale_14d_window` + inject | violations=0 | inject: violations=**1**, `hits_forbidden=yes` | log inject-bad; `after_inject_bad.csv` |

**Expectation halt:** E1, E2, E3, E5, E6, E7, E8. **Warn:** E4, E9.

**Ví dụ fail:** Run `inject-bad` → `expectation[refund_no_stale_14d_window] FAIL` → pipeline tiếp tục chỉ vì `--skip-validate` (Sprint 3 demo).

---

## 3. Before / after ảnh hưởng retrieval

**Kịch bản inject:** `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate` — embed refund stale 14 ngày.

**Kết quả:**

| Metric | inject-bad | clean-final |
|--------|------------|-------------|
| Eval 21 câu pass | 20/21 | **21/21** |
| `q_refund_window` hits_forbidden | **yes** | no |
| Grading 10 câu | fail gq_d10_01 | **10/10 OK** |

Artifact: `artifacts/eval/after_inject_bad.csv`, `artifacts/eval/after_fix_eval.csv`, `docs/quality_report.md`.

---

## 4. Freshness & monitoring

SLA **24 giờ** (`FRESHNESS_SLA_HOURS` trong `.env`). Đo trên `latest_exported_at` trong manifest (max `exported_at` cleaned). CSV mẫu có timestamp **2026-04-10** → `freshness_check=FAIL` (age ~1470h) — chấp nhận trong lab vì đây là snapshot cố định, không phải sync live. Production: đo thêm tại `publish_completed_at` (đã log 2 boundary trong manifest).

---

## 5. Liên hệ Day 09

Day 09 supervisor-workers gọi retrieval trên corpus đã embed. Day 10 đảm bảo corpus **sạch version** trước khi agent đọc — cùng domain `data/docs/` nhưng đi qua lớp ETL CSV. Collection tách `day10_kb` để chứng minh pipeline publish; có thể trỏ Day 09 retriever sang collection này sau mỗi `run`.

---

## 6. Rủi ro còn lại

- Freshness FAIL trên data mẫu cần policy rõ khi demo với GV.
- Rule enrich escalation bằng prefix text — nên thay bằng chunking theo heading tài liệu gốc.
- Chưa có alert Slack thật (`#data-pipeline-alerts` chỉ khai báo trong contract).

**Peer review (3 câu):**

1. Rule quarantine P2 trong doc P1 có làm mất thông tin hợp lệ không? → Chấp nhận vì export lẫn priority; P2 nên doc_id riêng ở production.
2. `--skip-validate` chỉ dùng demo inject — đã ghi runbook.
3. `HR_LEAVE_MIN_EFFECTIVE_DATE` từ env — đổi env có thể làm fail E8; đã sync contract.
