"""Private transport probe. Asterisk emits 660 Hz only after receiving key 2."""
import asyncio
import os
from contextlib import AsyncExitStack
from importlib.metadata import version
from uuid import uuid4

import numpy as np
from livekit import api, rtc

from audio import RATE, matches, tone

URL = "ws://server:7880"
KEY = "labkey"
SECRET = "local-lab-only-00000000000000000000000000000000"


async def wait_audio(stream, hz=None):
    buf = bytearray()
    consecutive = 0
    async for event in stream:
        buf.extend(event.frame.data.tobytes())
        while len(buf) >= 800:
            block = bytes(buf[:800])
            del buf[:800]
            if hz is None:
                heard = np.max(np.abs(np.frombuffer(block, "<i2").astype(float))) > 250
            else:
                heard = matches(block, hz)
            consecutive = consecutive + 1 if heard else 0
            if consecutive >= 2:
                return
    raise RuntimeError("Remote audio ended before the expected signal")


async def probe():
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
            sip_trunk_id=trunk.sip_trunk_id, sip_call_to="7001", room_name=room_name,
            participant_identity="insurer", wait_until_answered=True))
        stream = await asyncio.wait_for(incoming, 10)
        stack.push_async_callback(stream.aclose)
        await asyncio.wait_for(wait_audio(stream), 12)
        print("Received insurer menu audio")
        await room.local_participant.publish_dtmf(code=2, digit="2")
        await asyncio.wait_for(wait_audio(stream, 660), 8)
        print("Asterisk accepted digit 2")
        # Allow the marker to finish and Echo() to begin before transmitting.
        await asyncio.sleep(1.2)
        frame = rtc.AudioFrame(tone(980, 160), RATE, 1, 160)
        for _ in range(40):
            await source.capture_frame(frame)
        await source.wait_for_playout()
        await asyncio.wait_for(wait_audio(stream, 980), 6)
        print("PASS: caller audio returned through Asterisk Echo()")


if __name__ == "__main__":
    print("LiveKit SDK", version("livekit"), "API", version("livekit-api"))
    asyncio.run(asyncio.wait_for(probe(), timeout=65))
