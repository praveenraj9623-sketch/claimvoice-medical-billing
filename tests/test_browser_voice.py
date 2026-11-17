import asyncio

from claimvoice.browser.records import BrowserRecords
from claimvoice.browser.session import BrowserSession
from claimvoice.browser.tickets import issue_ticket, valid_ticket
from claimvoice.phone.simulator import PAID, PENDING


def test_browser_call_persists_supported_fields_after_hold(tmp_path):
    store = BrowserRecords(str(tmp_path / "browser.sqlite3"))

    async def complete():
        session = BrowserSession(None, store)
        await session.connected()
        await session.answer("Please hold.")
        assert session.snapshot()["state"] == "on_hold"
        await session.answer("I'm back.")
        for reply in PAID:
            await session.answer(reply)
        assert session.snapshot()["saved"]
        assert session.report["checks"] == []
        assert session.report["fields"]["payment_reference"] == "EFT-771"
        assert session.report["transcript"][session.report["evidence"]["payment_reference"]]["speaker"] == "representative"
        return session.call.call_id

    call_id = asyncio.run(complete())
    assert store.execute("SELECT id FROM claimvoice_browser_runs", fetch=True) == [(call_id,)]


def test_browser_missing_reference_requires_review(tmp_path):
    store = BrowserRecords(str(tmp_path / "browser.sqlite3"))

    async def complete():
        session = BrowserSession(None, store)
        await session.connected()
        for reply in (PENDING[0], "Unknown", "Unknown", PENDING[2]):
            await session.answer(reply)
        assert session.snapshot()["saved"]
        assert session.report["fields"]["reference_number"] is None
        assert "missing:reference_number" in session.report["checks"]

    asyncio.run(complete())


def test_launch_ticket_rejects_tampering_and_expiry(monkeypatch):
    from claimvoice.browser import tickets

    monkeypatch.setattr(tickets, "time", lambda: 100)
    ticket = issue_ticket("workspace secret")
    assert valid_ticket("workspace secret", ticket)
    assert not valid_ticket("separate secret", ticket)
    assert not valid_ticket("workspace secret", ticket + "é")
    monkeypatch.setattr(tickets, "time", lambda: 701)
    assert not valid_ticket("workspace secret", ticket)


def test_model_evidence_requires_a_verbatim_unambiguous_answer():
    from types import SimpleNamespace
    from claimvoice.browser.extraction import find_quote

    class StubClient:
        config = SimpleNamespace(model="openai/gpt-oss-20b")

        def post(self, endpoint, **kwargs):
            assert endpoint == "chat/completions"
            return {"choices": [{"message": {"content": '{"quote": "EFT-771"}'}}]}

    client = StubClient()
    assert find_quote(client, "payment_reference", "You can use EFT-771 for that payment.") == "EFT-771"
    assert find_quote(client, "payment_reference", "The transaction is EFT-551.") is None
    assert find_quote(client, "payment_reference", "It is not EFT-771.") is None
