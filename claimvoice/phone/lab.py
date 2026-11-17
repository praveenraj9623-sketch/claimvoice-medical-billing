"""Streamlit workspace for simulated phone calls."""

import json

import streamlit as st

from .review import metrics
from .simulator import FIXTURES, benchmark, simulate


def render():
    st.header("ClaimVoice Phone Lab")
    st.write("Test one fictional insurer route, review what the representative said, and inspect why a call stopped.")
    st.caption("Synthetic IVR and representative transcripts. No phone or model requests. Latency measures Python processing.")
    choice = st.selectbox("Insurer scenario", list(FIXTURES))
    left, right = st.columns(2)
    reports = st.session_state.setdefault("phone_reports", [])
    if left.button("Run scenario", type="primary"):
        reports.append(simulate(choice))
    if right.button("Run benchmark"):
        reports.extend(benchmark())
    del reports[:-150]
    if not reports:
        return
    summary = metrics(reports)
    columns = st.columns(4)
    for column, label, value in zip(
        columns,
        ("Calls attempted", "IVR passed", "Complete records", "Flagged for review"),
        ("attempts", "ivr_passed", "complete", "needs_review"),
    ):
        column.metric(label, summary[value])
    st.caption(f"Python latency mean {summary['app_latency_mean_ms']} ms · P95 {summary['app_latency_p95_ms']} ms "
               f"· {summary['latency_samples']} samples · $0 provider spend")
    st.caption(f"Fixture match {summary['fixture_matching_fields']}/{summary['fixture_checked_fields']} fields "
               "· Includes expected blank fields")
    latest = st.selectbox(
        "Inspect attempt", range(len(reports) - 1, -1, -1),
        format_func=lambda index: f"{index + 1}. {reports[index]['fixture']} — {reports[index]['outcome']}",
    )
    report = reports[latest]
    st.subheader("Transcript and captured fields")
    for item in report["transcript"]:
        st.write(f"**{item['speaker'].title()}** · {item['text']}")
    st.json(report["fields"])
    if report["checks"]:
        st.warning("Review required · " + ", ".join(report["checks"]))
    else:
        st.success("Captured fields match the cited transcript turns.")
    st.download_button("Download call reports", json.dumps(reports, indent=2), "claimvoice-phone-lab.json", "application/json")
