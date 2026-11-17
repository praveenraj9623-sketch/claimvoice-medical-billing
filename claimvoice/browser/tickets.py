"""Sign short-lived launch links without putting service credentials in the browser."""

from hashlib import sha256
import hmac
from time import time
from uuid import UUID, uuid4


def issue_ticket(secret):
    payload = f"{int(time()) + 600}.{uuid4().hex}"
    signature = hmac.new(secret.encode(), payload.encode(), sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_ticket(secret, ticket):
    try:
        expiry, nonce, signature = ticket.split(".")
        if not int(time()) < int(expiry) <= int(time()) + 600 or UUID(hex=nonce).hex != nonce:
            return False
    except ValueError:
        return False
    if not signature.isascii():
        return False
    expected = hmac.new(secret.encode(), f"{expiry}.{nonce}".encode(), sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
