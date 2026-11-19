"""Private transport probe. Asterisk emits 660 Hz only after receiving key 2."""
import asyncio
import os
import json
import wave
from pathlib import Path
from contextlib import AsyncExitStack
from importlib.metadata import version
from uuid import uuid4

import numpy as np
from livekit import api, rtc

from menu_guard import EXPECTED, publish
from audio import RATE, matches, tone_frames

URL = "ws://server:7880"
KEY = "labkey"
SECRET = "local-lab-only-00000000000000000000000000000000"


async def wait_audio(stream, hz=None, recording=None):
    buf = bytearray()
    consecutive = 0
    async for event in stream:
        buf.extend(event.frame.data.tobytes())
        while len(buf) >= 800:
            block = bytes(buf[:800])
            del buf[:800]
            if recording is not None:
                recording.writeframesraw(block)
            if hz is None:
                heard = np.max(np.abs(np.frombuffer(block, "<i2").astype(float))) > 250
            else:
                heard = matches(block, hz)
            consecutive = consecutive + 1 if heard else 0
            if consecutive >= 2:
                return
    raise RuntimeError("Remote audio ended before the expected signal")


async def exchange_question(room, source, stream, question, reply):
    with wave.open(str(question), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Question must be 8 kHz mono PCM16")
        while pcm := wav.readframes(160):
            await source.capture_frame(rtc.AudioFrame(pcm, RATE, 1, len(pcm) // 2))
    await source.wait_for_playout()
    await asyncio.sleep(0.25)
    await room.local_participant.publish_dtmf(code=11, digit="#")
    await asyncio.wait_for(wait_audio(stream, 1200), 8)
    with wave.open(str(reply), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", ""))
        await asyncio.wait_for(wait_audio(stream, 1400, recording=wav), 15)
    print("Received simulated representative's answer over SIP")


async def check_menu(room, stream, directory):
    # Publish only a closed WAV; the host recognizer sees exactly what the caller heard.
    temporary = directory / "recording.wav"
    with wave.open(str(temporary), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", ""))
        try:
            await asyncio.wait_for(wait_audio(stream, 1520, recording=wav), 12)
        except (asyncio.TimeoutError, RuntimeError):
            publish(directory / "menu-result.json", {"decision": "review_required", "reason": "incomplete_menu",
                                                      "audio": "recording.wav", "sent_digits": []})
            return False
    temporary.replace(directory / "menu-heard.wav")
    path = directory / "menu-decision.json"
    async def receive():
        while not path.exists():
            await asyncio.sleep(0.1)
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        decision = await asyncio.wait_for(receive(), 18)
    except asyncio.TimeoutError:
        decision = {"decision": "review_required", "reason": "recognition_timeout"}
    outcome = {**decision, "sent_digits": []}
    if decision.get("decision") == "authorized" and decision.get("heard_digit") == EXPECTED:
        await asyncio.sleep(0.35)  # Asterisk finishes the marker before listening for DTMF.
        await room.local_participant.publish_dtmf(code=int(EXPECTED), digit=EXPECTED)
        outcome["sent_digits"].append(EXPECTED)
    publish(directory / "menu-result.json", outcome)
    print("Menu result:", json.dumps(outcome), flush=True)
    return bool(outcome["sent_digits"])


async def probe():
    exchange = os.environ.get("CLAIMCALL_EXCHANGE_DIR")
    paid = os.environ.get("CLAIMCALL_CASE") == "paid"
    extension = os.environ.get("CLAIMCALL_EXTENSION", "7001")
    guard_directory = os.environ.get("CLAIMCALL_MENU_DIR")
    if (exchange or extension != "7001") and not guard_directory:
        raise RuntimeError("A menu check is required for this route")
    room_name = "sip-probe-" + uuid4().hex
    room = rtc.Room()
    incoming = asyncio.get_running_loop().create_future()

    @room.on("track_subscribed")
    def subscribed(track, publication, participant):
        if participant.identity == "insurer" and track.kind == rtc.TrackKind.KIND_AUDIO and not incoming.done():
            incoming.set_result(rtc.AudioStream(track, sample_rate=RATE, num_channels=1))

    async with AsyncExitStack() as stack:
        client = api.LiveKitAPI(URL, KEY, SECRET)
        stack.push_async_callback(client.aclose)
        token = (api.AccessToken(KEY, SECRET).with_identity("caller")
                 .with_grants(api.VideoGrants(room_join=True, room=room_name)).to_jwt())
        await room.connect(URL, token)
        stack.push_async_callback(client.room.delete_room, api.DeleteRoomRequest(room=room_name))
        stack.push_async_callback(room.disconnect)
        source = rtc.AudioSource(RATE, 1)
        stack.push_async_callback(source.aclose)
        track = rtc.LocalAudioTrack.create_audio_track("caller-audio", source)
        await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        trunk = await client.sip.create_sip_outbound_trunk(api.CreateSIPOutboundTrunkRequest(
            trunk=api.SIPOutboundTrunkInfo(name=room_name, address=os.environ["INSURER_ADDRESS"],
                                           transport="SIP_TRANSPORT_UDP", numbers=["7000"])))
        stack.push_async_callback(client.sip.delete_sip_trunk, api.DeleteSIPTrunkRequest(sip_trunk_id=trunk.sip_trunk_id))
        await client.sip.create_sip_participant(api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk.sip_trunk_id, sip_call_to=extension, room_name=room_name,
            participant_identity="insurer", wait_until_answered=True))
        stream = await asyncio.wait_for(incoming, 10)
        stack.push_async_callback(stream.aclose)
        if guard_directory:
            if not await check_menu(room, stream, Path(guard_directory)):
                if exchange:
                    raise RuntimeError("Menu requires review; see menu-result.json")
                return
        else:
            await asyncio.wait_for(wait_audio(stream), 12)
            print("Received insurer menu audio")
            await room.local_participant.publish_dtmf(code=2, digit="2")
        await asyncio.wait_for(wait_audio(stream, 660), 8)
        print("Asterisk accepted digit 2")
        if guard_directory and not exchange:
            return
        # Allow the marker to finish and Echo() to begin before transmitting.
        await asyncio.sleep(1.2)
        if exchange:
            directory = Path(exchange)
            await exchange_question(room, source, stream, directory / "question.wav", directory / "reply-heard.wav")
            if paid:
                for attempt in (1, 2):
                    # The ending marker lasts 500 ms. Start after Record() is listening.
                    await asyncio.sleep(0.8)
                    await exchange_question(room, source, stream, directory / f"clarify-{attempt}.wav",
                                            directory / f"reference-{attempt}-heard.wav")
            return
        for pcm in tone_frames(980, samples_per_frame=160, frame_count=40):
            await source.capture_frame(rtc.AudioFrame(pcm, RATE, 1, 160))
        await source.wait_for_playout()
        await asyncio.wait_for(wait_audio(stream, 980), 6)
        print("PASS: caller audio returned through Asterisk Echo()")


if __name__ == "__main__":
    print("LiveKit SDK", version("livekit"), "API", version("livekit-api"))
    asyncio.run(asyncio.wait_for(probe(), timeout=100 if os.environ.get("CLAIMCALL_CASE") == "paid" else 65))
