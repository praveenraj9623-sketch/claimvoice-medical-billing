"""Untrusted model-derived facts must remain text in HTML summary cards."""
from claimvoice.presentation import field_list
from claimvoice.speech import speech_html


def test_reported_facts_are_escaped_and_unknown_values_stay_unknown():
    html = field_list([("Status", '<img src=x onerror="alert(1)">'), ("Reference", None)], draft=True)
    assert '<img' not in html
    assert '&lt;img' in html
    assert 'Not reported' in html


def test_speech_payload_cannot_close_script_or_trigger_autoplay():
    html = speech_html('</script><img src=x onerror="alert(1)">')
    assert '</script><img' not in html
    assert '\\u003c/script\\u003e' in html
    assert "document.getElementById('play').onclick" in html
    assert 'role="status"' in html
