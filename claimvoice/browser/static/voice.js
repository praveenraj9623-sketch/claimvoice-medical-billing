"use strict";

const byId = id => document.getElementById(id);
const labels = {
  status: "Claim status", denial_code: "Denial code", paid_amount: "Paid amount",
  payment_reference: "Check or EFT number", payment_date: "Payment date",
  reference_number: "Call reference", representative_name: "Representative",
};
const outcomes = {
  connecting: "Connecting", listening: "Listening", on_hold: "On hold", answered: "Completed",
  ended_by_operator: "Session ended", hold_timeout: "Hold limit reached", call_timeout: "Call limit reached",
  disconnected: "Disconnected", transcription_error: "Transcription unavailable",
  connection_error: "Connection failed", turn_limit: "Turn limit reached",
};
const ticket = new URLSearchParams(location.hash.slice(1)).get("ticket");
if (location.hash) history.replaceState(null, "", location.pathname);
let peer, mic, auth, report, timer;
let spoken = 0, displayed = 0, failures = 0, speaking = false;

function node(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function showState(state) {
  document.body.dataset.state = state;
  byId("state").textContent = state === "speaking" ? "Agent speaking" : (outcomes[state] || "Session ended");
}

function error(message) {
  byId("error").hidden = false;
  byId("error").textContent = message;
}

function cleanup() {
  clearTimeout(timer);
  if (peer) peer.close();
  mic?.getTracks().forEach(track => track.stop());
  window.speechSynthesis?.cancel();
  byId("stop").disabled = true;
}

async function request(path, options) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(16000) });
  if (response.ok) return response.json();
  if (response.status === 403) throw new Error("Open a fresh session from ClaimVoice.");
  if (response.status === 429) throw new Error("The demo is busy. Try again shortly.");
  throw new Error("The voice service is unavailable. Open a fresh session to retry.");
}

function waitForIce(connection) {
  if (connection.iceGatheringState === "complete") return Promise.resolve();
  return new Promise(resolve => {
    const timeout = setTimeout(done, 5500);
    function done() {
      clearTimeout(timeout);
      connection.removeEventListener("icegatheringstatechange", changed);
      resolve();
    }
    function changed() {
      if (connection.iceGatheringState === "complete") done();
    }
    connection.addEventListener("icegatheringstatechange", changed);
  });
}

async function start() {
  byId("start").disabled = true;
  byId("error").hidden = true;
  showState("connecting");
  try {
    mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    // Suppress input until the first prompt has finished playing.
    mic.getAudioTracks().forEach(track => { track.enabled = false; });
    peer = new RTCPeerConnection({iceServers: await request("/api/ice")});
    peer.addTransceiver(mic.getAudioTracks()[0], {direction: "sendonly", streams: [mic]});
    await peer.setLocalDescription(await peer.createOffer());
    await waitForIce(peer);
    const answer = await request("/api/offer", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({sdp: peer.localDescription.sdp, ticket}),
    });
    auth = {path: "/api/sessions/" + answer.id, headers: {Authorization: "Bearer " + answer.key}};
    await peer.setRemoteDescription({sdp: answer.sdp, type: answer.type});
    byId("stop").disabled = false;
    await poll();
  } catch (failure) {
    cleanup();
    showState("connection_error");
    if (!auth) byId("start").disabled = false;
    error(failure.name === "NotAllowedError" ? "Allow microphone access and try again." :
      (failure.message || "The microphone is unavailable."));
  }
}

function speak(text, state) {
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
    error("Device speech is unavailable. Follow the agent’s prompts in the transcript.");
    mic?.getAudioTracks().forEach(track => { track.enabled = true; });
    return;
  }
  speaking = true;
  showState("speaking");
  mic?.getAudioTracks().forEach(track => { track.enabled = false; });
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  const voice = speechSynthesis.getVoices().find(item => item.localService && item.lang === "en-US");
  if (voice) utterance.voice = voice;
  const deadline = setTimeout(() => { speechSynthesis.cancel(); failed(); }, 14000);
  function done() {
    clearTimeout(deadline);
    if (!speaking) return;
    speaking = false;
    if (!report) mic?.getAudioTracks().forEach(track => { track.enabled = true; });
    if (!report) showState(state);
  }
  function failed() {
    if (report) return;
    error("The browser could not play the prompt. Continue using the transcript.");
    done();
  }
  utterance.onend = done;
  utterance.onerror = failed;
  speechSynthesis.speak(utterance);
}

function render(snapshot) {
  if (report) return;
  for (const turn of snapshot.transcript.slice(displayed)) {
    if (!["agent", "representative"].includes(turn.speaker)) continue;
    const line = node("li", "");
    line.className = turn.speaker;
    line.append(node("strong", turn.speaker === "agent" ? "ClaimVoice" : "Insurer"), document.createTextNode(turn.text));
    byId("transcript").append(line);
    byId("transcript").scrollTop = byId("transcript").scrollHeight;
    byId("empty").hidden = true;
  }
  displayed = snapshot.transcript.length;
  if (!speaking) showState(snapshot.state);
  if (snapshot.report) {
    report = snapshot.report;
    cleanup();
    showState(snapshot.state);
    showReport(snapshot.saved);
    if (snapshot.state === "connection_error")
      error("The voice connection timed out. Open a new session and check your network.");
  } else if (!speaking && spoken < snapshot.speech.length) {
    spokeNext(snapshot);
  }
}

function spokeNext(snapshot) {
  speak(snapshot.speech[spoken], snapshot.state);
  spoken += 1;
}

function showReport(saved) {
  byId("results").hidden = false;
  byId("review-status").textContent =
    (report.checks.length ? "Needs human review. " : "Answers match the transcript. ") +
    (saved ? "Report saved." : "Database save failed. Download a copy.");
  byId("issues").replaceChildren(...report.checks.map(issue => {
    const [type, field] = issue.split(":");
    const message = field ? (type === "missing" ? "Missing " : "Insufficient evidence for ") + (labels[field] || field) :
      (outcomes[issue] || "Check call outcome");
    return node("li", message);
  }));
  byId("issues").hidden = !report.checks.length;
  byId("fields").replaceChildren(...Object.entries(report.fields).map(([key, value]) => {
    const row = node("div", "");
    const detail = node("dd", value ? (key === "paid_amount" ? "$" + value : value) : "—");
    const evidence = report.transcript[report.evidence[key]];
    if (evidence) detail.append(node("small", "“" + (evidence.evidence_quote || evidence.text) + "”"));
    row.append(node("dt", labels[key]), detail);
    return row;
  }));
  const ms = report.transcript_to_reply_ms;
  if (ms.length) byId("latency").textContent =
    "Mean server response after transcription: " + Math.round(ms.reduce((a, b) => a + b, 0) / ms.length) + " ms";
}

async function poll() {
  try {
    render(await request(auth.path, {headers: auth.headers}));
    failures = 0;
  } catch (failure) {
    failures += 1;
    if (failures >= 3) {
      cleanup();
      showState("connection_error");
      error(failure.message);
      return;
    }
  }
  if (!report) timer = setTimeout(poll, 350);
}

async function stop() {
  byId("stop").disabled = true;
  clearTimeout(timer);
  try {
    render(await request(auth.path + "/end", {method: "POST", headers: auth.headers}));
  } catch (failure) {
    error(failure.message);
    await poll();
  }
}

function download() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: "application/json"}));
  const anchor = node("a", "");
  anchor.href = url;
  anchor.download = "claimvoice-" + report.call_id + ".json";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

byId("start").addEventListener("click", start);
byId("stop").addEventListener("click", stop);
byId("export").addEventListener("click", download);
window.addEventListener("pagehide", () => {
  if (auth && !report) fetch(auth.path + "/end", {method: "POST", headers: auth.headers, keepalive: true}).catch(() => {});
  cleanup();
});
if (!ticket) {
  byId("start").disabled = true;
  error("Open this voice session from the ClaimVoice workspace.");
}
