import os
import requests
import streamlit as st
import pandas as pd

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

st.set_page_config(
    page_title="SQL Data Analyst Agent",
    page_icon="",
    layout="wide",
)

# ── Session state init ────────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state["session_id"] = ""
if "history" not in st.session_state:
    st.session_state["history"] = []   # list of {question, insight, confidence_label}


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("SQL Data Analyst Agent")

    # New conversation button
    if st.button("New Conversation", use_container_width=True):
        if st.session_state["session_id"]:
            try:
                requests.delete(
                    f"{BACKEND_URL}/conversation/{st.session_state['session_id']}",
                    timeout=5,
                )
            except Exception:
                pass
        st.session_state["session_id"] = ""
        st.session_state["history"] = []
        st.rerun()

    st.divider()

    # Database schema viewer
    st.subheader("Database Schema")
    if st.button("Refresh Schema", use_container_width=True):
        st.session_state.pop("schema", None)

    if "schema" not in st.session_state:
        try:
            resp = requests.get(f"{BACKEND_URL}/schema", timeout=10)
            resp.raise_for_status()
            st.session_state["schema"] = resp.json()["schema"]
        except Exception as exc:
            st.session_state["schema"] = f"Could not load schema: {exc}"

    st.code(st.session_state["schema"], language="sql")


# ── Smart chart helper ────────────────────────────────────────────────────────
def _render_chart(df: pd.DataFrame) -> None:
    if df.empty:
        return
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    text_cols = df.select_dtypes(exclude="number").columns.tolist()
    date_like = [c for c in df.columns if any(k in c.lower() for k in ("date", "month", "year", "week"))]

    if not numeric_cols:
        return

    st.subheader("Chart")
    try:
        if date_like and numeric_cols:
            chart_df = df.set_index(date_like[0]).sort_index()
            st.line_chart(chart_df[numeric_cols[0]])
        elif len(text_cols) == 1 and len(numeric_cols) == 1:
            st.bar_chart(df.set_index(text_cols[0])[numeric_cols[0]])
        elif len(numeric_cols) >= 2:
            st.area_chart(df[numeric_cols])
    except Exception:
        pass  # chart is best-effort


# ── Conversation history display ──────────────────────────────────────────────
def _confidence_badge(label: str) -> str:
    colors = {"High": "🟢", "Medium": "🟡", "Low": "🔴", "None": "⚫"}
    return colors.get(label, "⚫")


if st.session_state["history"]:
    st.subheader("Conversation History")
    for i, turn in enumerate(st.session_state["history"], 1):
        badge = _confidence_badge(turn["confidence_label"])
        with st.expander(f"Turn {i}: {turn['question'][:70]}…  {badge}", expanded=False):
            st.markdown(f"**Insight:** {turn['insight']}")
            st.caption(f"Confidence: {turn['confidence_label']}")
    st.divider()


# ── Main: question input ──────────────────────────────────────────────────────
st.title("Ask your data a question")

if st.session_state["session_id"]:
    st.caption(f"Session: `{st.session_state['session_id'][:8]}…`  ({len(st.session_state['history'])} turn(s))")

question = st.text_area(
    "Your question",
    placeholder=(
        "e.g. What are the top 5 products by revenue?\n"
        "e.g. Which countries have the most customers?\n"
        "e.g. How does that compare with last year?"   # multi-turn follow-up example
    ),
    height=90,
    key="question_input",
)

if st.button("Analyze", type="primary") and question.strip():
    with st.spinner("Agent is planning and running queries…"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/analyze",
                json={
                    "question": question,
                    "session_id": st.session_state["session_id"],
                },
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as exc:
            st.error(f"Request failed: {exc.response.text}")
            st.stop()
        except Exception as exc:
            st.error(f"Connection error: {exc}")
            st.stop()

    # Persist session
    st.session_state["session_id"] = data["session_id"]
    st.session_state["history"].append({
        "question": question,
        "insight": data["insight"],
        "confidence_label": data["confidence_label"],
    })

    step_results = data.get("step_results", [])
    successful = [s for s in step_results if not s["error"]]

    # ── Status banner ─────────────────────────────────────────────────────────
    badge = _confidence_badge(data["confidence_label"])
    if not successful:
        st.error(data["insight"])
        st.stop()

    col_status, col_conf = st.columns([3, 1])
    with col_status:
        st.success(f"{len(successful)}/{len(step_results)} step(s) succeeded")
    with col_conf:
        st.metric(
            "Confidence",
            f"{badge} {data['confidence_label']}",
            delta=f"{data['confidence_score']:.0%}",
            delta_color="off",
        )

    # ── Plan summary ──────────────────────────────────────────────────────────
    with st.expander("Analytical Plan", expanded=False):
        st.markdown(f"**Summary:** {data['plan']}")
        for i, step in enumerate(data.get("plan_steps", []), 1):
            st.markdown(f"**Step {i}:** {step}")

    # ── Insight ───────────────────────────────────────────────────────────────
    st.subheader("Insight")
    st.markdown(data["insight"])
    st.divider()

    # ── Per-step results ──────────────────────────────────────────────────────
    st.subheader("Query Results")

    if len(step_results) == 1:
        sr = step_results[0]
        if sr["error"]:
            st.warning(sr["error"])
        else:
            with st.expander("SQL Query", expanded=True):
                st.code(sr["sql"], language="sql")
            if sr["results"]:
                df = pd.DataFrame(sr["results"])
                st.dataframe(df, use_container_width=True)
                _render_chart(df)
    else:
        tabs = st.tabs([f"Step {i + 1}" for i in range(len(step_results))])
        for tab, sr in zip(tabs, step_results):
            with tab:
                st.markdown(f"**Task:** {sr['step']}")
                if sr["error"]:
                    st.warning(sr["error"])
                    continue
                with st.expander("SQL", expanded=False):
                    st.code(sr["sql"], language="sql")
                if sr["results"]:
                    df = pd.DataFrame(sr["results"])
                    st.dataframe(df, use_container_width=True)
                    _render_chart(df)
                else:
                    st.info("No rows returned.")

    if data.get("total_retries", 0) > 0:
        st.caption(f"Note: {data['total_retries']} retry attempt(s) made during this analysis.")
