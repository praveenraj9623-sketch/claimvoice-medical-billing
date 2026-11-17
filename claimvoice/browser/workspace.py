"""Streamlit entry point for the browser voice workspace."""

import os
from urllib.parse import urlsplit

from dotenv import dotenv_values
import streamlit as st

from claimvoice.config import ROOT

from .tickets import issue_ticket

STYLE = """
<style>
.stApp {
  background: radial-gradient(at 14% 9%, #fff 0, transparent 45%),
              radial-gradient(at 82% 86%, #c4cdf8 0, transparent 63%), #eaf0fc;
}
.stMainBlockContainer {max-width:1160px}
[data-testid="stSidebar"] {background:#f5f7ff;border-right-color:#fff}
.cv-voice-header {
  background:linear-gradient(145deg,#fff,#edf1ffcf);
  border:1px solid #fff;border-radius:30px;
  box-shadow:inset 0 1px 3px #fff,0 14px 35px #36478019;
  padding:clamp(20px,4vw,40px)
}
.cv-voice-header p {color:#425474;margin:.5rem 0 0;font-size:1rem}
.cv-voice-header h1 {
  font:750 clamp(2.2rem,5vw,4rem)/1.07 -apple-system,BlinkMacSystemFont,
       Inter,"Segoe UI",sans-serif!important;letter-spacing:-.06em!important;
  margin:0;color:#1b2c53!important
}
[data-testid="stIFrame"] iframe {border-radius:28px}
</style>
"""


def render(secrets):
    st.markdown(STYLE, unsafe_allow_html=True)
    st.markdown("""
<div class="cv-voice-header">
  <h1>ClaimVoice</h1>
  <p>Follow up on a fictional EMS claim by voice. Review each answer against the conversation.</p>
</div>
""", unsafe_allow_html=True)
    settings = {**dotenv_values(ROOT / ".env"), **secrets, **os.environ}
    origin = str(settings.get("CLAIMVOICE_BROWSER_URL") or "")
    secret = str(settings.get("CLAIMVOICE_BROWSER_SECRET") or "")
    if not origin or len(secret) < 32:
        st.info("Browser voice needs a connected backend. Choose Phone Lab in the sidebar to try the scripted call scenarios.")
        return
    parsed = urlsplit(origin)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.scheme == "http"
    if ((parsed.scheme != "https" and not local) or not parsed.hostname or parsed.query
            or parsed.fragment or parsed.username is not None or parsed.path not in {"", "/"}):
        st.error("The browser voice backend must use an HTTPS origin.")
        return
    new_session = st.button("New voice session")
    if new_session or "browser_voice_ticket" not in st.session_state:
        st.session_state.browser_voice_ticket = issue_ticket(secret)
    url = f"{origin.rstrip('/')}/#ticket={st.session_state.browser_voice_ticket}"
    st.iframe(url, height=755)
    st.caption("If the microphone is blocked inside the page, start a new session and open it in a separate tab.")
    st.link_button("Open voice session in a new tab", url)
