import socket
import asyncio
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    # Windows event loops create local socketpairs for wakeups. Allocate the
    # AppTest runtime before blocking sockets; no service connections are made.
    loops = [asyncio.new_event_loop() for _ in range(24)] if request.node.path.name == "test_app.py" else []
    # AppTest creates and closes a fresh loop on each run.
    available = iter(loops)
    if loops:
        monkeypatch.setattr(asyncio, "new_event_loop", lambda: next(available))
    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests may not open network connections")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    for loop in loops:
        if not loop.is_closed():
            loop.close()
