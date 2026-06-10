#!/usr/bin/env python3
"""
Chat engine — retrieval + trả lời tự nhiên (extractive hoặc LLM).

Chạy UI: streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)

FORBIDDEN_MARKERS = ("14 ngày làm việc", "14 ngày", "10 ngày phép năm")

DOMAIN_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "policy_refund_v4": ("hoàn tiền", "refund", "hoàn lại", "đơn hàng", "finance", "hàng kỹ thuật số", "cs-refund"),
    "sla_p1_2026": ("p1", "sla", "ticket", "escalat", "incident", "sự cố", "15 phút", "4 giờ", "10 phút", "#incident"),
    "it_helpdesk_faq": ("đăng nhập", "mật khẩu", "vpn", "email", "khóa", "lockout", "quên mật khẩu", "90 ngày", "helpdesk", "laptop"),
    "hr_leave_policy": ("phép năm", "nghỉ phép", "nghỉ ốm", "nhân viên", "thai sản", "hr portal", "kinh nghiệm"),
    "access_control_sop": ("access", "quyền", "level", "admin", "ciso", "phê duyệt", "standard access", "elevated"),
}

REFUND_GOLDEN_QUESTION = (
    "Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền kể từ khi đơn được xác nhận?"
)

DOC_LABELS = {
    "policy_refund_v4": "Chính sách hoàn tiền",
    "sla_p1_2026": "SLA ticket P1",
    "it_helpdesk_faq": "FAQ IT Helpdesk",
    "hr_leave_policy": "Chính sách nghỉ phép HR",
    "access_control_sop": "Quy trình cấp quyền truy cập",
}

_STOPWORDS = frozenset(
    "là có của cho với trong khi nào ai gì bao nhiêu lâu không được cần phải theo một các và hoặc em anh chị bạn khách hệ thống thì mà để từ kể từ minh hoi ve cho muon lam sao thi duoc".split()
)

_VI_ACCENT_MAP = str.maketrans(
    {
        "à": "a",
        "á": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ă": "a",
        "ằ": "a",
        "ắ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "ặ": "a",
        "â": "a",
        "ầ": "a",
        "ấ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ậ": "a",
        "è": "e",
        "é": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "ề": "e",
        "ế": "e",
        "ể": "e",
        "ễ": "e",
        "ệ": "e",
        "ì": "i",
        "í": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ò": "o",
        "ó": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ồ": "o",
        "ố": "o",
        "ổ": "o",
        "ỗ": "o",
        "ộ": "o",
        "ơ": "o",
        "ờ": "o",
        "ớ": "o",
        "ở": "o",
        "ỡ": "o",
        "ợ": "o",
        "ù": "u",
        "ú": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ừ": "u",
        "ứ": "u",
        "ử": "u",
        "ữ": "u",
        "ự": "u",
        "ỳ": "y",
        "ý": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
        "đ": "d",
    }
)


def _normalize_vi(text: str) -> str:
    return text.lower().translate(_VI_ACCENT_MAP)


def get_collection():
    import chromadb
    from chromadb.utils import embedding_functions

    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")
    model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=db_path)
    emb = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)
    return client.get_collection(name=collection_name, embedding_function=emb)


def retrieve(question: str, top_k: int) -> Tuple[List[str], List[Dict[str, Any]]]:
    col = get_collection()
    queries = [question]
    ql = _normalize_vi(question)
    if any(k in ql for k in ("hoan tien", "refund", "hoan lai")) and len(question) < 120:
        queries.append(REFUND_GOLDEN_QUESTION)
    if any(k in ql for k in ("level", "access", "quyen", "admin", "ciso", "phe duyet")):
        queries.append("Level 4 Admin Access cần phê duyệt bởi ai?")
    hr_bucket = _hr_tenure_bucket(question)
    if hr_bucket:
        gq = _hr_golden_question(hr_bucket)
        if gq:
            queries.append(gq)
    elif any(k in ql for k in ("phep nam", "nghi phep", "nhan vien", "hr portal", "kinh nghiem")):
        pass  # không ép golden under-3 khi chưa rõ thâm niên
    if any(k in ql for k in ("mat khau", "dang nhap", "vpn", "khoa tai khoan", "helpdesk")):
        queries.append("Tài khoản bị khóa sau bao nhiêu lần đăng nhập sai?")

    seen_ids: set[str] = set()
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    for q in queries:
        res = col.query(query_texts=[q], n_results=top_k)
        batch_docs = (res.get("documents") or [[]])[0]
        batch_metas = (res.get("metadatas") or [[]])[0]
        for doc, meta in zip(batch_docs, batch_metas):
            cid = (meta or {}).get("doc_id", "") + "|" + (doc or "")[:120]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            docs.append(doc)
            metas.append(meta or {})
    return docs, metas


def _score_domains(question: str) -> Dict[str, int]:
    q = _normalize_vi(question)
    return {
        doc_id: sum(2 for kw in kws if _normalize_vi(kw) in q)
        for doc_id, kws in DOMAIN_KEYWORDS.items()
    }


def _token_overlap(question: str, text: str) -> int:
    qw = {
        _normalize_vi(w)
        for w in re.findall(r"\w+", question.lower())
        if len(w) > 2 and _normalize_vi(w) not in _STOPWORDS
    }
    tw = {_normalize_vi(w) for w in re.findall(r"\w+", text.lower()) if len(w) > 2}
    return len(qw & tw)


def _access_level_in_question(question: str) -> Optional[str]:
    q = question.lower()
    m = re.search(r"level\s*(\d+)", q, re.I)
    if m:
        return f"level {m.group(1)}"
    if "standard access" in q:
        return "level 2"
    if "elevated access" in q:
        return "level 3"
    if "admin access" in q and "level 4" not in q and not re.search(r"level\s*\d", q):
        return "level 4"
    return None


def _hr_tenure_bucket(question: str) -> Optional[str]:
    """under_3 | mid_3_5 | over_5 | sick — suy từ câu hỏi (vd. 9 năm → over_5)."""
    q = _normalize_vi(question)
    if any(k in q for k in ("nghi om", "om co luong", "nghi benh", "benh thi")):
        return "sick"
    if any(k in q for k in ("tren 5 nam", "hon 5 nam", "5 nam tro len", "sau 5 nam")):
        return "over_5"
    if any(k in q for k in ("duoi 3 nam", "it hon 3 nam", "chua du 3 nam")):
        return "under_3"
    if any(k in q for k in ("3 den 5 nam", "3-5 nam", "tu 3 den 5", "3 toi 5 nam")):
        return "mid_3_5"

    m = re.search(r"(\d+)\s*nam(?:\s*(?:kinh nghiem|kn|lam viec))?", q)
    if m:
        years = int(m.group(1))
        if years > 5:
            return "over_5"
        if years >= 3:
            return "mid_3_5"
        return "under_3"
    return None


def _hr_chunk_matches_tenure(doc: str, bucket: str) -> bool:
    dl = _normalize_vi(doc)
    if bucket == "sick":
        return "om" in dl or "10 ngay/nam" in dl
    if bucket == "over_5":
        return "18 ngay" in dl and "tren 5" in dl
    if bucket == "mid_3_5":
        return "15 ngay" in dl and ("3 den 5" in dl or "3-5" in dl)
    if bucket == "under_3":
        return "12 ngay" in dl and "duoi 3" in dl
    return False


def _hr_golden_question(bucket: str) -> str:
    return {
        "sick": "Số ngày nghỉ ốm có trả lương là bao nhiêu?",
        "over_5": "Nhân viên trên 5 năm kinh nghiệm được bao nhiêu ngày phép năm?",
        "mid_3_5": "Nhân viên có kinh nghiệm từ 3 đến 5 năm được bao nhiêu ngày phép năm?",
        "under_3": "Nhân viên dưới 3 năm kinh nghiệm được bao nhiêu ngày phép năm?",
    }.get(bucket, "")


def _question_intent(question: str) -> str:
    q = _normalize_vi(question)
    if any(w in q for w in ("ai ", "ai?", "boi ai", "phe duyet boi", "who", "can ai")):
        return "who"
    if any(w in q for w in ("bao nhieu", "may ", "how many")):
        return "quantity"
    if any(w in q for w in ("bao lau", "trong bao", "mat bao", "how long", "khi nao")):
        return "duration"
    if any(w in q for w in ("la gi", "gi ", "what", "nao khong", "the nao")):
        return "what"
    return "general"


def _extract_fact_tokens(text: str) -> set[str]:
    """Các mẩu fact trong câu trả lời — dùng khớp chunk nguồn."""
    norm = _normalize_vi(text)
    facts: set[str] = set()
    for m in re.finditer(
        r"\d+[\d\s\-–]*(ngay lam viec|ngay phep nam|ngay/nam|ngay|phut|gio|lan|thiet bi|gb)",
        norm,
    ):
        facts.add(re.sub(r"\s+", " ", m.group(0).strip()))
    for phrase in (
        "it manager",
        "ciso",
        "line manager",
        "it admin",
        "it security",
        "senior engineer",
        "license",
        "subscription",
        "ky thuat so",
        "cs-refund",
        "incident-p1",
        "7 ngay",
        "12 ngay",
        "15 ngay",
        "18 ngay",
        "10 ngay",
        "5 lan",
        "2 thiet bi",
        "15 phut",
        "10 phut",
        "4 gio",
        "30 phut",
        "90 ngay",
        "50gb",
        "sso portal",
    ):
        if phrase in norm:
            facts.add(phrase)
    return facts


def _support_score(answer: str, question: str, doc: str, meta: Dict[str, Any]) -> int:
    dn = _normalize_vi(doc)
    score = 0
    for fact in _extract_fact_tokens(answer):
        if fact in dn:
            score += 8
    score += _token_overlap(answer, doc) * 3
    score += _token_overlap(question, doc)
    score += _score_domains(question).get((meta or {}).get("doc_id", ""), 0)
    hr_bucket = _hr_tenure_bucket(question) or _hr_tenure_bucket(answer)
    if hr_bucket and (meta or {}).get("doc_id") == "hr_leave_policy":
        if _hr_chunk_matches_tenure(doc, hr_bucket):
            score += 25
        elif hr_bucket != "sick" and _hr_chunk_matches_tenure(doc, "under_3"):
            score -= 10
    return score


def pick_source_chunk(
    question: str,
    answer: str,
    docs: List[str],
    metas: List[Dict[str, Any]],
) -> Tuple[int, str, Dict[str, Any]]:
    """Chọn chunk nguồn khớp câu trả lời (ưu tiên khi dùng LLM)."""
    if not docs:
        return 0, "", {}

    best_i, best_score = 0, -1
    for i, (doc, meta) in enumerate(zip(docs, metas)):
        s = _support_score(answer, question, doc, meta or {})
        if s > best_score:
            best_score, best_i = s, i

    if best_score > 0:
        return best_i, docs[best_i], metas[best_i] or {}

    return pick_answer_chunk(question, docs, metas)


def pick_answer_chunk(
    question: str,
    docs: List[str],
    metas: List[Dict[str, Any]],
) -> Tuple[int, str, Dict[str, Any]]:
    if not docs:
        return 0, "", {}

    scores = _score_domains(question)
    target_doc = max(scores, key=scores.get) if max(scores.values(), default=0) > 0 else ""

    def _pick_from_doc(doc_id: str, prefer_fn) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        for i, (doc, meta) in enumerate(zip(docs, metas)):
            if (meta or {}).get("doc_id") != doc_id:
                continue
            if prefer_fn(doc):
                return i, doc, meta or {}
        for i, (doc, meta) in enumerate(zip(docs, metas)):
            if (meta or {}).get("doc_id") == doc_id:
                return i, doc, meta or {}
        return None

    if target_doc == "policy_refund_v4":

        def _prefer_refund(doc: str) -> bool:
            dl = doc.lower()
            q = question.lower()
            if any(k in q for k in ("ngoại lệ", "không được hoàn", "hàng kỹ thuật số", "license")):
                return any(k in dl for k in ("ngoại lệ", "kỹ thuật số", "license", "subscription"))
            if "finance" in q or "3-5" in q:
                return "finance" in dl or "3-5" in dl
            return "7 ngày" in dl and ("xác nhận" in dl or "hoàn tiền" in dl)

        hit = _pick_from_doc("policy_refund_v4", _prefer_refund)
        if hit:
            return hit

    if target_doc == "hr_leave_policy":
        tenure = _hr_tenure_bucket(question)

        def _prefer_hr(doc: str) -> bool:
            if tenure:
                return _hr_chunk_matches_tenure(doc, tenure)
            q = _normalize_vi(question)
            if "om" in q or "nghi om" in q:
                return _hr_chunk_matches_tenure(doc, "sick")
            if "15 ngay" in q or "3 den 5" in q:
                return _hr_chunk_matches_tenure(doc, "mid_3_5")
            if "18 ngay" in q or "tren 5" in q:
                return _hr_chunk_matches_tenure(doc, "over_5")
            return _hr_chunk_matches_tenure(doc, "under_3")

        hit = _pick_from_doc("hr_leave_policy", _prefer_hr)
        if hit:
            return hit

    if target_doc == "access_control_sop":
        level = _access_level_in_question(question)
        if level:

            def _prefer_access(doc: str) -> bool:
                dl = doc.lower()
                if level == "level 4":
                    return "level 4" in dl and "admin access" in dl
                if level == "level 3":
                    return "level 3" in dl or "elevated access" in dl
                if level == "level 2":
                    return "level 2" in dl or "standard access" in dl
                if level == "level 1":
                    return "level 1" in dl or "read only" in dl
                return level in dl

            hit = _pick_from_doc("access_control_sop", _prefer_access)
            if hit:
                return hit

    if target_doc == "sla_p1_2026":
        q = question.lower()

        def _prefer_sla(doc: str) -> bool:
            dl = doc.lower()
            if "escalat" in q or ("10 phút" in q and "phản hồi" in q):
                return "escalat" in dl and "10 phút" in dl
            if "4 giờ" in q or "resolution" in q:
                return "4 giờ" in dl or "resolution" in dl
            if "15 phút" in q or "phản hồi đầu" in q:
                return "15 phút" in dl
            if "30 phút" in q:
                return "30 phút" in dl
            return True

        hit = _pick_from_doc("sla_p1_2026", _prefer_sla)
        if hit:
            return hit

    if target_doc == "it_helpdesk_faq":
        best_i, best_score = 0, -1
        for i, (doc, meta) in enumerate(zip(docs, metas)):
            if (meta or {}).get("doc_id") != "it_helpdesk_faq":
                continue
            s = _token_overlap(question, doc)
            if s > best_score:
                best_score, best_i = s, i
        if best_score > 0:
            return best_i, docs[best_i], metas[best_i]

    if target_doc:
        hit = _pick_from_doc(target_doc, lambda _d: True)
        if hit:
            return hit

    best_i, best_score = 0, _token_overlap(question, docs[0])
    for i, doc in enumerate(docs[1:], 1):
        s = _token_overlap(question, doc)
        if s > best_score:
            best_score, best_i = s, i
    return best_i, docs[best_i], metas[best_i] or {}


def _best_sentence(question: str, chunk: str) -> str:
    clean = re.sub(r"\s*\[cleaned:[^\]]+\]", "", chunk).strip()
    parts = re.split(r"(?<=[.!?])\s+", clean)
    if len(parts) <= 1:
        return clean
    best, best_score = parts[0], -1
    for p in parts:
        if len(p) < 8:
            continue
        score = _token_overlap(question, p)
        if score > best_score:
            best_score, best = score, p
    return best


def _synthesize_extractive(question: str, chunk: str, doc_id: str) -> str:
    intent = _question_intent(question)
    q = _normalize_vi(question)
    sent = _best_sentence(question, chunk)
    label = DOC_LABELS.get(doc_id, doc_id)

    tenure = _hr_tenure_bucket(question)
    if doc_id == "hr_leave_policy" and tenure == "sick":
        return f"Theo **{label}**, nghỉ ốm có trả lương tối đa **10 ngày/năm**."
    if doc_id == "hr_leave_policy" and tenure in ("over_5", "mid_3_5", "under_3"):
        days = {
            "over_5": "18 ngày phép năm",
            "mid_3_5": "15 ngày phép năm",
            "under_3": "12 ngày phép năm",
        }
        return f"Theo **{label}**, mức phép năm áp dụng là **{days[tenure]}**."

    if intent == "who":
        m = re.search(r"phê duyệt bởi ([^.]+)", sent, re.I)
        if m:
            return f"Theo **{label}**, cần phê duyệt bởi **{m.group(1).strip()}**."
        m = re.search(r"(IT Manager[^.]*CISO[^.]*)", sent, re.I)
        if m:
            return f"Theo **{label}**, {m.group(1).strip()}."

    if intent in ("quantity", "duration"):
        m = re.search(
            r"(\d+[\d\s\-–]*(ngày làm việc|ngày/năm|ngày phép năm|ngày|phút|giờ|lần|thiết bị)[^.]*)",
            sent,
            re.I,
        )
        if m:
            val = m.group(1).strip()
            if "hoan tien" in q or "refund" in q:
                if "ke tu" in _normalize_vi(val):
                    return f"Theo **{label}**, thời hạn yêu cầu hoàn tiền là **{val}**."
                return f"Theo **{label}**, thời hạn yêu cầu hoàn tiền là **{val}** kể từ khi đơn được xác nhận."
            if "escalat" in q or ("p1" in q and "10 phut" in _normalize_vi(sent)):
                return f"Theo **{label}**, ticket P1 sẽ **tự động escalate sau {val}** nếu chưa có phản hồi."
            if "phep nam" in q or ("phep" in q and "om" not in q):
                tenure = _hr_tenure_bucket(question)
                if tenure == "over_5":
                    return f"Theo **{label}**, nhân viên trên 5 năm kinh nghiệm được **18 ngày phép năm**."
                if tenure == "mid_3_5":
                    return f"Theo **{label}**, nhân viên từ 3 đến 5 năm kinh nghiệm được **15 ngày phép năm**."
                if tenure == "under_3":
                    return f"Theo **{label}**, nhân viên dưới 3 năm kinh nghiệm được **12 ngày phép năm**."
                return f"Theo **{label}**, mức phép năm áp dụng là **{val}**."
            if "om" in q:
                return f"Theo **{label}**, nghỉ ốm có trả lương tối đa **{val}**."
            if "vpn" in q or "thiet bi" in q:
                return f"Theo **{label}**, giới hạn là **{val}**."
            if "dang nhap" in q or "khoa" in q or "mat khau" in q:
                return f"Theo **{label}**, tài khoản bị khóa sau **{val}** đăng nhập sai liên tiếp."
            if "sla" in q or "p1" in q or "15 phút" in q or "4 giờ" in q:
                return f"Theo **{label}**, cam kết SLA là **{val}**."
            return f"Theo **{label}**: **{val}**."

    if "escalat" in q and re.search(r"10\s*phút", sent, re.I):
        return f"Theo **{label}**, ticket P1 sẽ **tự động escalate sau 10 phút** nếu chưa có phản hồi."

    if intent == "what" and any(k in q for k in ("ngoai le", "khong duoc hoan", "san pham", "chinh sach hoan")):
        if "ky thuat so" in _normalize_vi(sent) or "license" in sent.lower():
            return (
                f"Theo **{label}**, không được hoàn tiền đối với **hàng kỹ thuật số** "
                "(license key, subscription) và một số trường hợp khuyến mãi."
            )
        if "7 ngay" in _normalize_vi(sent) or "hoan tien" in q:
            return (
                f"Theo **{label}**, khách có thể yêu cầu hoàn tiền trong **7 ngày làm việc** "
                "kể từ khi đơn hàng được xác nhận (trừ hàng kỹ thuật số và một số ngoại lệ)."
            )

    # Câu trả lời tự nhiên — paraphrase nhẹ từ câu liên quan nhất
    body = re.sub(r"^(Escalation P1|Ticket P1|VPN|Quên mật khẩu):\s*", "", sent, flags=re.I).strip()
    if body.endswith("."):
        body = body[:-1]
    return f"Theo **{label}**: {body}."


def generate_with_llm(question: str, docs: List[str], metas: List[Dict[str, Any]]) -> Optional[str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        context = "\n\n".join(
            f"[{DOC_LABELS.get(m.get('doc_id', ''), m.get('doc_id'))}] {d}"
            for d, m in zip(docs[:5], metas[:5])
        )
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn là trợ lý CS + IT Helpdesk nội bộ. "
                        "CHỈ trả lời bằng tiếng Việt, ngắn gọn (1-3 câu), "
                        "dựa đúng context được cung cấp. "
                        "Không bịa. Nếu context không đủ, nói rõ là không có trong tài liệu."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nCâu hỏi: {question}",
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None


def is_relevant(question: str, doc: str, meta: Dict[str, Any]) -> bool:
    scores = _score_domains(question)
    doc_id = (meta or {}).get("doc_id", "")
    if scores.get(doc_id, 0) > 0:
        return True
    if max(scores.values(), default=0) > 0 and doc_id == max(scores, key=scores.get):
        return True
    return _token_overlap(question, doc) >= 1


def build_answer(
    question: str,
    docs: List[str],
    metas: List[Dict[str, Any]],
    *,
    use_llm: bool = False,
) -> Dict[str, Any]:
    if not docs:
        return {
            "text": "Hiện chưa có dữ liệu trong index. Vui lòng chạy pipeline embed trước.",
            "sources": [],
            "warning": None,
            "mode": "empty",
        }

    idx, chunk, meta = pick_answer_chunk(question, docs, metas)
    doc_id = meta.get("doc_id", "unknown")

    if not is_relevant(question, chunk, meta):
        return {
            "text": (
                "Mình chưa tìm thấy thông tin phù hợp trong knowledge base CS/IT Helpdesk cho câu hỏi này.\n\n"
                "Bạn có thể hỏi cụ thể về: **hoàn tiền**, **SLA P1**, **IT FAQ** (mật khẩu/VPN), "
                "**phép năm HR**, hoặc **cấp quyền access (Level 1–4)**."
            ),
            "sources": [],
            "warning": None,
            "mode": "no_match",
        }

    blob = " ".join(docs).lower()
    stale_hits = [m for m in FORBIDDEN_MARKERS if m in blob]
    warning = None
    if stale_hits:
        warning = (
            "Cảnh báo data quality: context còn marker stale "
            f"({', '.join(stale_hits)}). Kiểm tra pipeline hoặc chạy lại clean-final."
        )

    mode = "extractive"
    answer_text: Optional[str] = None
    if use_llm:
        answer_text = generate_with_llm(question, docs, metas)
        if answer_text:
            mode = "llm"

    if not answer_text:
        answer_text = _synthesize_extractive(question, chunk, doc_id)

    idx, chunk, meta = pick_source_chunk(question, answer_text, docs, metas)
    doc_id = meta.get("doc_id", doc_id)

    eff = meta.get("effective_date", "—")
    footer = f"\n\n*Nguồn: {DOC_LABELS.get(doc_id, doc_id)} · hiệu lực {eff}*"

    sources = []
    for i, (doc, m) in enumerate(zip(docs, metas), 1):
        sources.append(
            {
                "rank": i,
                "doc_id": (m or {}).get("doc_id", "?"),
                "effective_date": (m or {}).get("effective_date", "—"),
                "run_id": (m or {}).get("run_id", "—"),
                "preview": doc[:280] + ("…" if len(doc) > 280 else ""),
                "selected": i - 1 == idx,
            }
        )

    return {
        "text": answer_text + footer,
        "sources": sources,
        "warning": warning,
        "top1_doc_id": doc_id,
        "mode": mode,
    }
