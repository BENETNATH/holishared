"""Tests for access codes: generation, resolution, limitation (B029)."""

from app.models import CODE_ALPHABET, generate_event_code, generate_guest_code


def test_generate_guest_code_length_8():
    assert len(generate_guest_code()) == 8


def test_generate_guest_code_uses_unambiguous_alphabet():
    chars = set("".join(generate_guest_code() for _ in range(200)))
    assert chars <= set(CODE_ALPHABET)


def test_generate_event_code_skips_reserved(monkeypatch):
    forced = iter("access")
    real_choice = __import__("secrets").choice

    def fake_choice(seq):
        return next(forced, None) or real_choice(seq)

    monkeypatch.setattr("app.models.secrets.choice", fake_choice)
    assert generate_event_code() != "access"
