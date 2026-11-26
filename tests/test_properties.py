"""Property-based tests (Hypothesis) for the pure building blocks."""

import string

from app.core import hardening, secret_scan
from app.core.ratelimit import Limit
from app.services.claims import normalize_path, overlaps
from app.services.errors import Unprocessable
from hypothesis import assume, given, settings
from hypothesis import strategies as st

segment = st.text(alphabet=string.ascii_letters + string.digits + "._-", min_size=1, max_size=12).filter(
    lambda s: s not in (".", "..")
)
rel_path = st.lists(segment, min_size=1, max_size=6).map("/".join)
glob_piece = st.sampled_from(["*", "**", "*.py", "?", "[ab]*"])
claim_path = st.one_of(
    rel_path,
    rel_path.map(lambda p: p + "/"),
    st.tuples(rel_path, glob_piece).map(lambda t: f"{t[0]}/{t[1]}"),
)


@given(claim_path)
def test_normalize_is_idempotent_and_safe(raw):
    once = normalize_path(raw)
    assert normalize_path(once) == once
    assert ".." not in once.split("/")
    assert not once.startswith("/")
    assert "//" not in once


@given(st.text(max_size=80))
@settings(max_examples=300)
def test_normalize_never_crashes(raw):
    try:
        out = normalize_path(raw)
    except Unprocessable:
        return
    assert ".." not in out.split("/") and not out.startswith("/")


@given(claim_path, claim_path)
def test_overlap_is_symmetric(a, b):
    a, b = normalize_path(a), normalize_path(b)
    assert overlaps(a, b) == overlaps(b, a)


@given(claim_path)
def test_overlap_is_reflexive(a):
    a = normalize_path(a)
    assert overlaps(a, a)


@given(rel_path, rel_path)
def test_directory_claim_covers_everything_under_it(d, f):
    assert overlaps(normalize_path(d + "/"), normalize_path(f"{d}/{f}"))
    assert overlaps(normalize_path(d), normalize_path(f"{d}/{f}"))


@given(rel_path, rel_path)
def test_distinct_plain_files_in_different_dirs_dont_overlap(a, b):
    a, b = f"left/{a}", f"right/{b}"
    assert not overlaps(normalize_path(a), normalize_path(b))


_secret_values = st.sampled_from(
    [
        "AK" + "IA" + "Q3EGUJ5NJ7WLXKZP",
        "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
        "sk" + "_live_" + "a" * 24,
        "AI" + "za" + "S" * 35,
    ]
)


@given(st.text(max_size=200), _secret_values, st.text(max_size=200))
@settings(max_examples=200)
def test_redaction_removes_secrets_wherever_they_appear(before, secret, after):
    # A secret is only recognized at a word boundary; pad with spaces so random
    # neighbouring characters don't legitimately extend the token.
    text, hits = secret_scan.redact(f"{before} {secret} {after}")
    assert secret not in text
    assert hits


@given(st.text(max_size=300))
@settings(max_examples=300)
def test_redaction_is_idempotent(text):
    once, _ = secret_scan.redact(text)
    twice, hits = secret_scan.redact(once)
    assert twice == once and hits == []


@given(st.text(alphabet=string.ascii_letters + " .,;:!?\n", max_size=300))
def test_plain_prose_is_never_redacted(text):
    assume("AKIA" not in text)
    assert secret_scan.redact(text) == (text, [])


@given(st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=8, max_size=40))
def test_log_redaction_hides_any_key_value(value):
    line = hardening.redact(f"GET /api/workspaces/w/ws?since=1&api_key={value}&x=2 HTTP/1.1")
    assert f"api_key={value}" not in line and "since=1" in line


@given(st.integers(min_value=0, max_value=10**6), st.sampled_from(["second", "minute", "hour", "s", "m", "h"]))
def test_limit_parse_roundtrip(count, unit):
    limit = Limit.parse(f"{count}/{unit}")
    assert limit.count == count and limit.period in (1, 60, 3600)
    assert limit.enabled == (count > 0)
