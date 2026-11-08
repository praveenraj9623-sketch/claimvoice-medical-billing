from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Conversation:
    claim_id: str
    mode: str = "Scripted walkthrough"
    session_id: str = field(default_factory=lambda: uuid4().hex)
    turns: list = field(default_factory=list)
    activity: list = field(default_factory=list)
    draft: dict | None = None
    saved: list = field(default_factory=list)
    consumed: set = field(default_factory=set)
    handoff: bool = False
    ended: bool = False
    error: str = ""

    def add(self, role, content):
        turn = {"id": len(self.turns) + 1, "role": role, "content": content}
        self.turns.append(turn)
        return turn

    def reserve(self, request_id):
        if request_id in self.consumed:
            return False
        self.consumed.add(request_id)
        return True
