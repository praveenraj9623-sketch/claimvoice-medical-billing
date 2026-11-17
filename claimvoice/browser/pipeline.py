"""Move microphone audio through Pipecat and send final transcripts to the call engine."""

import asyncio
from datetime import datetime, timezone

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.settings import STTSettings
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from claimvoice.groq_client import ServiceError


class ClaimTranscriber(SegmentedSTTService):
    def __init__(self, client, session):
        super().__init__(
            sample_rate=16000, audio_passthrough=False,
            settings=STTSettings(model=client.config.stt_model, language=None),
        )
        self.client = client
        self.session = session

    async def run_stt(self, audio):
        if self.session.call.outcome != "in_progress":
            return
        try:
            text = await asyncio.to_thread(self.client.transcribe, audio)
        except (ServiceError, ValueError):
            await self.session.finish("transcription_error")
            return
        yield TranscriptionFrame(text, "", datetime.now(timezone.utc).isoformat())


class ClaimAnswers(FrameProcessor):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            if frame.finalized and frame.text.strip():
                await self.session.answer(frame.text)
            return
        await self.push_frame(frame, direction)


async def run_pipeline(connection, client, session):
    transport = SmallWebRTCTransport(connection, TransportParams(audio_in_enabled=True))
    pipeline = Pipeline([
        transport.input(),
        VADProcessor(vad_analyzer=SileroVADAnalyzer()),
        ClaimTranscriber(client, session),
        ClaimAnswers(session),
    ])
    worker = PipelineWorker(pipeline, enable_rtvi=False)

    @transport.event_handler("on_client_connected")
    async def connected(_transport, _client):
        await session.connected()

    @transport.event_handler("on_client_disconnected")
    async def disconnected(_transport, _client):
        await session.finish("disconnected")
        await worker.cancel()

    try:
        await PipelineRunner(handle_sigint=False).run(worker)
    finally:
        await session.finish("disconnected")
