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
    return """<!doctype html><html><body>
<button id="play">Play assistant reply</button> <button id="stop">Stop</button>
<p id="status" role="status">Press Play. Uses your browser's speech service.</p>
<script>
const text = """ + encoded + """;
const status = document.getElementById('status');
const synth = window.speechSynthesis;
document.getElementById('play').onclick = () => {
 if (!synth || !window.SpeechSynthesisUtterance) {status.textContent='Speech unavailable. Read the conversation instead.'; return;}
 if (!synth.getVoices().length) {status.textContent='No voices available yet. Try Play again or read the text.'; return;}
 synth.cancel(); status.textContent='Waiting for playback'; const u = new SpeechSynthesisUtterance(text);
 u.onstart=()=>status.textContent='Playing';
 u.onend=()=>status.textContent='Finished';
 u.onerror=()=>status.textContent='Playback unavailable or blocked. Check browser permissions; text remains available.';
 synth.speak(u);
 setTimeout(()=>{if(status.textContent==='Waiting for playback') status.textContent='Playback did not start. Try Play again or read the text.';},5000);
};
document.getElementById('stop').onclick=()=>{if(synth) synth.cancel(); status.textContent='Stopped';};
window.addEventListener('pagehide',()=>{if(synth) synth.cancel();});
</script></body></html>"""
