# Preserved upstream worker - separate from ClaimVoice

The original worker is based on [livekit-examples/outbound-caller-python](https://github.com/livekit-examples/outbound-caller-python/tree/608f4c7055c3e3307a98187cfdf74b77eeac8600). Its original instructions remain available in that commit's [README](https://github.com/livekit-examples/outbound-caller-python/blob/608f4c7055c3e3307a98187cfdf74b77eeac8600/README.md) and the repository history. Upstream history, `agent.py` and [MIT LICENSE](LICENSE) are preserved.

## Which path should I run?

For the synthetic browser follow-up demo, use [README.md](README.md), `app.py` and `requirements.txt`. This does not dispatch a telephone call and does not use the LiveKit worker.

The preserved `agent.py` is the upstream dental/outbound-calling example. It is not connected to the ClaimVoice interface. It may place real calls if separately configured and dispatched. It was not exercised as part of this adaptation or README cleanup.

## Optional worker configuration

If independently investigating the upstream example, use a separate environment, `requirements-livekit.txt` and the placeholders in `.env.livekit.example` for `.env.local`. The original setup's references to `requirements.txt` and `.env.example` refer to upstream names, not the browser-app files in this adaptation. Consult upstream LiveKit documentation for current SIP, provider and dispatch requirements.

LiveKit coordinates real-time sessions/telephony; it is not itself an STT, LLM or TTS model. The upstream configuration can involve LiveKit, OpenAI, Deepgram and Cartesia services. These are not requirements for the Groq-backed Streamlit demo and are not evidence of a deployed ClaimVoice telephone integration.
