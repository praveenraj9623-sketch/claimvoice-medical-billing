"""Presentation helpers; no provider calls or workflow state changes."""
from html import escape
from decimal import Decimal, InvalidOperation
import streamlit as st


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root {--cv-ink:#172c42;--cv-muted:#617589;--cv-line:#dce6ed;--cv-teal:#087f83;}
.stApp {background:#f5f8fa;}
.stApp, [data-testid="stSidebar"] {font-family:'DM Sans',sans-serif;color:var(--cv-ink);}
h1,h2,h3 {font-family:'Manrope',sans-serif!important;letter-spacing:-.035em!important;color:var(--cv-ink)!important;}
.stMainBlockContainer {max-width:1400px;padding-top:2.4rem;padding-bottom:3rem;}
[data-testid="stSidebar"] {background:#fff;border-right:1px solid var(--cv-line);}
[data-testid="stSidebar"] .stSidebarBlockContainer {padding-top:2rem;}
[data-testid="stSidebar"] h2 {font-size:1rem;letter-spacing:0!important;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {font-size:.78rem;line-height:1.6;}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-color:var(--cv-line)!important;border-radius:16px!important;}
[data-testid="stChatMessage"] {border:1px solid #e5edf2;border-radius:14px;background:white;padding:1rem;margin-bottom:.65rem;}
[data-testid="stChatMessage"] p {line-height:1.7;}
[data-testid="stChatMessageAvatarAssistant"] {background:#087f83;}
[data-testid="stChatMessageAvatarUser"] {background:#465d79;}
.stButton button,.stDownloadButton button,.stFormSubmitButton button {border-radius:9px;min-height:42px;font-weight:600;}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"] {background:#087f83;border-color:#087f83;color:white;}
.stButton button[kind="primary"]:hover,.stFormSubmitButton button[kind="primary"]:hover {background:#06666b;border-color:#06666b;}
.stButton button:focus-visible,.stDownloadButton button:focus-visible {outline:3px solid #64c7cd;outline-offset:3px;}
[data-testid="stTextArea"] textarea {background:#fff;line-height:1.65;}
button[data-baseweb="tab"] {font-size:.93rem;font-weight:600;padding:0 1.1rem;}
[data-baseweb="tab-list"] {gap:.2rem;border-bottom:1px solid var(--cv-line);margin-bottom:1.25rem;}
[data-baseweb="tab-highlight"] {background:#087f83;}
[data-testid="stMetric"] {padding:.6rem 0;}
[data-testid="stAlert"] {border-radius:10px;}
.cv-brand {display:flex;align-items:center;gap:11px;margin-bottom:1.7rem;}
.cv-logo {width:39px;height:39px;background:#087f83;color:white;border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.cv-brand strong {font:800 1.25rem 'Manrope',sans-serif;letter-spacing:-.045em;}
.cv-brand small {display:block;color:var(--cv-muted);font-size:.73rem;margin-top:2px;}
.cv-hero {display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:1.3rem;}
.cv-eyebrow {font-size:.7rem;text-transform:uppercase;font-weight:700;letter-spacing:.16em;color:#087f83;margin-bottom:9px;}
.cv-hero h1 {font-size:2.05rem!important;line-height:1.2!important;margin:0 0 9px;padding:0;}
.cv-hero p {font-size:.92rem;color:var(--cv-muted);margin:0;line-height:1.6;}
.cv-pill {display:inline-flex;align-items:center;gap:6px;border-radius:30px;padding:7px 11px;font-size:.72rem;font-weight:700;background:#e7f4f2;color:#07676b;white-space:nowrap;}
.cv-pill.neutral {background:#edf1f6;color:#53657b;}
.cv-steps {display:flex;gap:10px;margin:1.5rem 0;}
.cv-step {flex:1;display:flex;align-items:center;gap:9px;border:1px solid var(--cv-line);background:#fff;border-radius:10px;padding:12px;font-size:.79rem;color:var(--cv-muted);}
.cv-step span {border-radius:7px;display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;background:#eff3f6;font-weight:700;flex-shrink:0;}
.cv-step.current {border-color:#95d3d0;color:#07676b;background:#edf8f6;}
.cv-step.current span {background:#087f83;color:#fff;}
.cv-summary {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 1.5rem;}
.cv-stat {background:#fff;border:1px solid var(--cv-line);border-radius:12px;padding:15px 17px;}
.cv-label {font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--cv-muted);margin-bottom:7px;}
.cv-value {font-size:1rem;font-weight:700;overflow-wrap:anywhere;}
.cv-sub {font-size:.73rem;color:var(--cv-muted);margin-top:5px;}
.cv-note {font-size:.79rem;line-height:1.65;color:var(--cv-muted);padding:11px 14px;border-left:3px solid #8bc7c9;background:#edf5f6;border-radius:0 8px 8px 0;margin:.6rem 0 1.2rem;}
.cv-section {font:800 1.05rem 'Manrope',sans-serif;margin:3px 0 5px;letter-spacing:-.02em;}
.cv-section-sub {color:var(--cv-muted);font-size:.8rem;line-height:1.6;margin-bottom:15px;}
.cv-fields {margin:0;}
.cv-fields>div {padding:11px 0;border-bottom:1px solid #edf1f5;}
.cv-fields>div:last-child {border-bottom:none;}
.cv-fields dt {font-size:.73rem;color:var(--cv-muted);margin-bottom:4px;}
.cv-fields dd {font-size:.87rem;font-weight:500;margin:0;line-height:1.6;overflow-wrap:anywhere;white-space:pre-wrap;}
.cv-draft {display:grid;grid-template-columns:1fr 1fr;gap:13px;margin:12px 0;}
.cv-draft>div {background:#f8fafc;border:1px solid #e7eef3;border-radius:10px;padding:14px;min-width:0;}
.cv-draft dd {font-size:.93rem;}
.cv-empty {background:white;border:1px solid var(--cv-line);border-radius:16px;padding:32px;margin-bottom:1rem;}
.cv-empty h2 {font-size:1.5rem!important;margin:0 0 10px;}
.cv-empty p {color:var(--cv-muted);font-size:.91rem;line-height:1.8;max-width:650px;}
.cv-footer {font-size:.73rem;line-height:1.6;color:var(--cv-muted);border-top:1px solid var(--cv-line);padding-top:15px;margin-top:1.7rem;}
@media(max-width:760px){.stMainBlockContainer{padding:1.4rem 1rem 2rem}.cv-hero{align-items:flex-start;flex-direction:column;gap:12px}.cv-hero h1{font-size:1.65rem!important}.cv-summary{grid-template-columns:1fr 1fr}.cv-steps{gap:5px}.cv-step{padding:8px;font-size:.7rem;gap:5px}.cv-draft{grid-template-columns:1fr}.cv-stat{padding:12px}.cv-empty{padding:22px}}
</style>
"""


def safe(value):
    if value is None or value == "":
        return "Not reported"
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(x) for x in value) or "Not reported"
    return escape(str(value), quote=True)


def field_list(items, draft=False):
    cls = "cv-fields cv-draft" if draft else "cv-fields"
    return f'<dl class="{cls}">' + "".join(
        f"<div><dt>{safe(label)}</dt><dd>{safe(value)}</dd></div>" for label, value in items
    ) + "</dl>"


def amount(value):
    try:
        return f"${Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return "Not reported"


def style():
    st.markdown(CSS, unsafe_allow_html=True)


def brand():
    st.markdown('''<div class="cv-brand"><div class="cv-logo" aria-hidden="true"><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 13v-1a8 8 0 0 1 16 0v1M4 12H3v6h4v-6H4Zm16 0h1v6h-4v-6h3ZM18 18v1a2 2 0 0 1-2 2h-4"/></svg></div><div><strong>ClaimVoice</strong><small>Follow-up workspace</small></div></div>''', unsafe_allow_html=True)


def header():
    st.markdown('''<div class="cv-hero"><div><div class="cv-eyebrow">Insurer follow-up workspace</div><h1>A clearer conversation.<br>A better follow-up record.</h1><p>Capture reported details, review the evidence, and save your next steps.</p></div><span class="cv-pill neutral">Synthetic data · Browser demo</span></div>''', unsafe_allow_html=True)


def steps(state):
    current = 1 if state is None else (3 if state.draft else 2)
    labels = ["Set up a session", "Capture the reply", "Review & export"]
    st.markdown('<div class="cv-steps">' + ''.join(
        f'<div class="cv-step{" current" if i == current else ""}"><span>{i}</span>{label}</div>'
        for i, label in enumerate(labels, 1)) + '</div>', unsafe_allow_html=True)


def summary(state, claim):
    values = [
        ("Selected claim", state.claim_id, claim["patient"]),
        ("Billed amount", amount(claim["billed_amount"]), "Original submitted amount"),
        ("Session mode", state.mode, "No API requests" if state.mode == "Scripted walkthrough" else "Explicit Groq requests"),
        ("Session status", "Ended" if state.ended else "Active", "Human review flagged" if state.handoff else f"{len(state.turns)} conversation turns"),
    ]
    st.markdown('<div class="cv-summary">' + ''.join(
        f'<div class="cv-stat"><div class="cv-label">{safe(label)}</div><div class="cv-value">{safe(value)}</div><div class="cv-sub">{safe(sub)}</div></div>'
        for label,value,sub in values) + '</div>', unsafe_allow_html=True)


def section(title, subtitle=""):
    st.markdown(f'<div class="cv-section">{safe(title)}</div><div class="cv-section-sub">{safe(subtitle) if subtitle else ""}</div>', unsafe_allow_html=True)
