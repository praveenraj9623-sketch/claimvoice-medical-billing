import io
import json
import wave


def validate_wav(audio):
    if not isinstance(audio, bytes) or not audio or len(audio) > 20 * 1024 * 1024:
        raise ValueError("Record nonempty WAV audio under 20 MB.")
    try:
        with wave.open(io.BytesIO(audio)) as wav:
            if wav.getnframes() == 0 or not wav.readframes(1):
                raise ValueError("Recording is empty.")
    except (wave.Error, EOFError):
        raise ValueError("Audio must be a valid WAV recording.") from None


def speech_html(text):
    # JSON string encoding plus HTML-sensitive escapes prevents closing script injection.
    encoded = json.dumps(text).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return """<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>
*{box-sizing:border-box}body{margin:0;background:transparent;color:#172c42;font-family:system-ui,-apple-system,sans-serif;font-size:12px}.bar{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #dce6ed;border-radius:12px;padding:12px}.label{font-size:11px;font-weight:650;color:#617589;margin-right:auto;line-height:1.5}button{display:inline-flex;align-items:center;justify-content:center;gap:7px;font:600 12px system-ui;min-height:38px;border:1px solid #dce6ed;border-radius:8px;padding:8px 13px;background:white;color:#172c42;cursor:pointer;white-space:nowrap}#play{background:#087f83;border-color:#087f83;color:white}button:hover{filter:brightness(.94)}button:focus-visible{outline:3px solid #64c7cd;outline-offset:2px}svg{flex-shrink:0}#status{font-size:11px;color:#617589;margin:8px 2px;line-height:1.4}@media(max-width:410px){.label{display:none}.bar{padding:9px}button{flex:1}}
</style></head><body>
<div class="bar"><div class="label">Assistant playback<br><span style="font-weight:400">Browser speech service</span></div><button id="play" type="button"><svg aria-hidden="true" width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2.5v11l9-5.5z"/></svg>Play assistant reply</button><button id="stop" type="button"><svg aria-hidden="true" width="11" height="11" viewBox="0 0 12 12" fill="currentColor"><rect x="1" y="1" width="10" height="10" rx="1"/></svg>Stop</button></div>
<p id="status" role="status" aria-live="polite">Press Play to listen. Voice availability depends on your browser.</p>
<script>
const text = """ + encoded + """;
const status = document.getElementById('status');
const synth = window.speechSynthesis;
let current = null;
document.getElementById('play').onclick = () => {
 if (!synth || !window.SpeechSynthesisUtterance) {status.textContent='Speech unavailable. Read the conversation instead.'; return;}
 if (!synth.getVoices().length) {status.textContent='No voices available yet. Try Play again or read the text.'; return;}
 current=null; synth.cancel(); status.textContent='Waiting for playback'; const u = new SpeechSynthesisUtterance(text);
 current=u;
 u.onstart=()=>{if(current===u) status.textContent='Playing assistant reply';};
 u.onend=()=>{if(current===u){status.textContent='Playback finished';current=null;}};
 u.onerror=()=>{if(current===u){status.textContent='Playback unavailable or blocked. Read the conversation instead.';current=null;}};
 synth.speak(u);
 setTimeout(()=>{if(current===u && status.textContent==='Waiting for playback') status.textContent='Playback did not start. Try Play again or read the text.';},5000);
};
document.getElementById('stop').onclick=()=>{current=null;if(synth) synth.cancel();status.textContent='Playback stopped';};
window.addEventListener('pagehide',()=>{current=null;if(synth) synth.cancel();});
</script></body></html>"""
