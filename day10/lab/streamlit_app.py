#!/usr/bin/env python3
"""
Streamlit chatbot — CS + IT Helpdesk (grounded RAG).

Chạy:
  cd day10/lab
  streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

from chat_engine import build_answer, retrieve

load_dotenv()

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)
MANIFEST_PATH = ROOT / "artifacts" / "manifests" / "manifest_clean-final.json"

EXAMPLE_QUESTIONS = [
    "Khách có bao nhiêu ngày hoàn tiền?",
    "Sản phẩm nào không được hoàn tiền?",
    "SLA phản hồi P1 là bao lâu?",
    "Escalate P1 sau mấy phút?",
    "Tài khoản khóa sau mấy lần đăng nhập sai?",
    "Nhân viên dưới 3 năm được mấy ngày phép?",
    "Level 4 cần ai phê duyệt?",
]


@st.cache_resource(show_spinner="Đang kết nối Chroma…")
def _warmup():
    from chat_engine import get_collection

    get_collection()
    return True


def _load_manifest() -> Optional[Dict[str, Any]]:
    if not MANIFEST_PATH.is_file():
        return None
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def render_message(msg: Dict[str, Any]) -> None:
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("warning"):
            st.warning(msg["warning"])
        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander("Xem context retrieval (top-k)"):
                st.caption("✅ = chunk nguồn khớp câu trả lời (không phải luôn là rank #1).")
                for s in msg["sources"]:
                    mark = " ✅" if s.get("selected") else ""
                    st.markdown(
                        f"**#{s['rank']}** `{s['doc_id']}` · {s['effective_date']}{mark}"
                    )
                    st.caption(s["preview"])


def main() -> None:
    st.set_page_config(page_title="CS + IT Helpdesk", page_icon="💬", layout="centered")
    _warmup()

    has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Chào bạn! Mình là trợ lý **CS + IT Helpdesk**.\n\n"
                    "Mình đọc câu hỏi của bạn, tìm đoạn tài liệu liên quan trong index `day10_kb`, "
                    "rồi **tóm tắt trả lời** — không copy nguyên block mẫu.\n\n"
                    "Hỏi tự do (tiếng Việt, có hoặc không dấu), ví dụ: *\"refund được bao lâu?\"*, "
                    "*\"level 4 ai duyệt?\"*, *\"VPN tối đa mấy máy?\"*, *\"quen mat khau lam sao?\"*"
                ),
                "sources": [],
            }
        ]

    with st.sidebar:
        st.header("Day 10 Demo")
        manifest = _load_manifest()
        if manifest:
            st.success(f"Pipeline `{manifest.get('run_id')}`")
            st.caption(
                f"cleaned {manifest.get('cleaned_records')} · "
                f"quarantine {manifest.get('quarantine_records')}"
            )
        else:
            st.warning("Chưa có manifest")

        top_k = st.slider("Top-k retrieval", 3, 10, 5)
        use_llm = st.checkbox(
            "Dùng LLM tổng hợp câu trả lời",
            value=has_openai,
            disabled=not has_openai,
            help="Cần OPENAI_API_KEY trong .env",
        )
        st.markdown("**Gợi ý câu hỏi**")
        for i, q in enumerate(EXAMPLE_QUESTIONS):
            if st.button(q, use_container_width=True, key=f"ex_{i}"):
                st.session_state.pending_question = q

        if st.button("Xóa hội thoại", use_container_width=True):
            st.session_state.messages = st.session_state.messages[:1]
            st.rerun()

    for msg in st.session_state.messages:
        render_message(msg)

    pending = st.session_state.pop("pending_question", None)
    prompt = pending or st.chat_input("Hỏi gì cũng được — mình sẽ đọc và trả lời theo tài liệu nội bộ…")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt.strip()})
        try:
            docs, metas = retrieve(prompt.strip(), top_k=top_k)
            result = build_answer(prompt.strip(), docs, metas, use_llm=use_llm and has_openai)
        except Exception as exc:
            result = {
                "text": f"Không truy vấn được index: {exc}\n\nChạy: `python etl_pipeline.py run --run-id clean-final`",
                "sources": [],
                "warning": None,
            }
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["text"],
                "sources": result.get("sources", []),
                "warning": result.get("warning"),
            }
        )
        st.rerun()


if __name__ == "__main__":
    main()
