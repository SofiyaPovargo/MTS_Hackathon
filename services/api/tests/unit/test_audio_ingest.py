"""Resumable audio upload helpers: ``Content-Range`` parsing and type handling."""

from __future__ import annotations

import pytest

from app.domain.errors import ValidationFailed
from app.services.audio_ingest import (
    AudioUpload,
    normalize_content_type,
    parse_content_range,
)


def test_parse_content_range_reads_a_closed_range() -> None:
    assert parse_content_range("bytes 0-1023/4096") == (0, 1023, 4096)
    assert parse_content_range("bytes 1024-2047/4096") == (1024, 2047, 4096)


def test_parse_content_range_accepts_a_byte_prefix_case_insensitively() -> None:
    assert parse_content_range("Bytes 0-0/1") == (0, 0, 1)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "items 0-9/30",
        "bytes 0-9",
        "bytes 0-9/",
        "bytes 5-4/30",  # start after end
        "bytes 0-30/30",  # end beyond the declared total
        "bytes 0-9/0",  # a zero-length upload cannot be chunked
        "bytes a-b/30",
        "bytes 0-9/xyz",
    ],
)
def test_parse_content_range_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValidationFailed):
        parse_content_range(value)


def test_normalize_content_type_strips_parameters_and_case() -> None:
    assert normalize_content_type("Audio/WAV; codec=pcm") == "audio/wav"
    assert normalize_content_type(None) == "application/octet-stream"
    assert AudioUpload(b"x", "audio/ogg; rate=16000").content_type == "audio/ogg"
