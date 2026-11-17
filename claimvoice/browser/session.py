"""Serialize voice turns, enforce deadlines and save a review report."""

import asyncio
import logging
from time import monotonic

from claimvoice.phone.engine import Call
from claimvoice.phone.review import build_report

from .extraction import find_quote

LOG = logging.getLogger(__name__)


class BrowserSession:
    def __init__(self, client, records):
        self.call = Call(quote_finder=lambda field, text: find_quote(client, field, text))
        self.records = records
        self.lock = asyncio.Lock()
        self.active = False
        self.report = None
        self.save_failed = False
        self.peer = None
        self.worker = None
        self.updated = monotonic()
        self.turn_latency_ms = []
        self.spoken = []
        self.deadline_task = asyncio.create_task(self._watch_deadline())

    def _queue_speech(self, actions, started=None):
        for action in actions:
            if action.kind == "speak":
                self.spoken.append(action.value)
                if started is not None:
                    self.turn_latency_ms.append(round((monotonic() - started) * 1000, 1))

    async def connected(self):
        async with self.lock:
            if not self.active and self.call.outcome == "in_progress":
                self.active = True
                self._queue_speech(self.call.connect_representative())

    async def answer(self, text):
        async with self.lock:
            if not self.active or self.call.outcome != "in_progress":
                return
            started = monotonic()
            actions = await asyncio.to_thread(self.call.prompt, text)
            self._queue_speech(actions, started)
            if self.call.outcome != "in_progress":
                await self._save()

    async def finish(self, outcome):
        async with self.lock:
            if self.call.outcome == "in_progress":
                self.call.finish(outcome)
                await self._save()

    async def _watch_deadline(self):
        while self.call.outcome == "in_progress":
            await asyncio.sleep(min(0.5, self.call.seconds_remaining()))
            async with self.lock:
                if self.call.outcome != "in_progress":
                    return
                if not self.active and monotonic() - self.call.started >= 20:
                    self.call.finish("connection_error")
                    await self._save()
                elif self.call.seconds_remaining() == 0:
                    self.call.timeout()
                    await self._save()

    async def _save(self):
        result = build_report(self.call, transport="browser-webrtc")
        result["transcript_to_reply_ms"] = self.turn_latency_ms.copy()
        self.updated = monotonic()
        try:
            await asyncio.to_thread(self.records.save, result)
        except Exception:
            LOG.error("Could not save browser call %s", self.call.call_id)
            self.save_failed = True
        self.report = result
        if self.peer is not None:
            # Closing in the background keeps transport disconnect callbacks
            # from attempting to reacquire the active turn lock.
            asyncio.create_task(self.peer.disconnect())

    def snapshot(self):
        state = "connecting"
        if self.report is not None:
            state = self.call.outcome
        elif self.active:
            state = "on_hold" if self.call.hold_until else "listening"
        return {
            "state": state,
            "speech": self.spoken,
            "transcript": self.call.transcript,
            "report": self.report,
            "saved": self.report is not None and not self.save_failed,
        }
