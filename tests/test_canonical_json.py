"""Focused tests for the canonical JSON pipeline and atomic writer."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from beacon.core.canonical_json import InvalidJsonValue, dumps_canonical, write_atomic
from beacon.core.limits import LIMIT_INVALID_VALUE, LIMIT_SNAPSHOT_BYTES, LimitError

MIB = 1024 * 1024


# ---------------------------------------------------------------------------
# Byte stability and deterministic key ordering
# ---------------------------------------------------------------------------


def test_byte_stable_across_calls_and_key_order() -> None:
    value = {"z": 1, "a": {"d": 2, "b": 3}, "m": [4, 5]}
    first = dumps_canonical(value)
    second = dumps_canonical(dict(value))
    assert first == second
    assert json.loads(first.decode("utf-8")) == value
    # Keys are serialized in sorted order.
    assert first.index(b'"a"') < first.index(b'"m"') < first.index(b'"z"')


def test_nested_mappings_are_sorted_recursively() -> None:
    out = dumps_canonical({"outer": {"zebra": 1, "apple": 2}})
    assert out.index(b'"apple"') < out.index(b'"zebra"')


def test_scalar_types_round_trip() -> None:
    value = [None, True, False, 0, 123, 1.5, "text"]
    assert json.loads(dumps_canonical(value).decode("utf-8")) == value


# ---------------------------------------------------------------------------
# Unicode
# ---------------------------------------------------------------------------


def test_unicode_preserved_not_escaped() -> None:
    value = {"greeting": "héllo wörld \u4f60\u597d \U0001f600"}
    out = dumps_canonical(value)
    decoded = out.decode("utf-8")
    assert "\u4f60\u597d" in decoded  # ensure_ascii=False keeps raw unicode
    assert json.loads(decoded) == value


def test_multibyte_byte_stability() -> None:
    value = {"snowman": "\u2603", "emoji": "\U0001f600"}
    assert dumps_canonical(value) == dumps_canonical(value)


# ---------------------------------------------------------------------------
# Final newline: exactly one trailing newline
# ---------------------------------------------------------------------------


def test_exactly_one_trailing_newline() -> None:
    out = dumps_canonical({"a": 1})
    assert out.endswith(b"\n")
    assert not out.endswith(b"\n\n")
    assert out.count(b"\n") == 1


def test_empty_container_still_has_single_newline() -> None:
    for value in ({}, [], {"a": {"b": []}}):
        out = dumps_canonical(value)
        assert out.endswith(b"\n")
        assert out.count(b"\n") == 1


# ---------------------------------------------------------------------------
# Invalid values are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        object(),
        b"bytes",
        {1, 2, 3},
        (1, 2),
        1j,
    ],
)
def test_invalid_leaf_value_rejected(value: object) -> None:
    with pytest.raises(InvalidJsonValue):
        dumps_canonical(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_nested_rejected(value: float) -> None:
    with pytest.raises(InvalidJsonValue):
        dumps_canonical({"a": [{"b": value}]})


def test_non_string_mapping_key_rejected() -> None:
    with pytest.raises(InvalidJsonValue):
        dumps_canonical({1: "bad key"})


def test_invalid_value_path_reported() -> None:
    with pytest.raises(InvalidJsonValue) as excinfo:
        dumps_canonical({"a": [{"b": float("nan")}]})
    assert excinfo.value.path == "$.a[0].b"


def test_nested_non_json_value_rejected() -> None:
    with pytest.raises(InvalidJsonValue):
        dumps_canonical({"a": {"b": {2: "x"}}})


# ---------------------------------------------------------------------------
# Size boundary
# ---------------------------------------------------------------------------


def test_under_ceiling_ok() -> None:
    out = dumps_canonical({"a": "x" * 100}, byte_ceiling=1 * MIB)
    assert len(out) <= 1 * MIB


def test_exact_ceiling_allowed() -> None:
    value = {"pad": "x" * 1000}
    expected = dumps_canonical(value)
    out = dumps_canonical(value, byte_ceiling=len(expected))
    assert out == expected
    assert len(out) == len(expected)


def test_over_ceiling_refused() -> None:
    with pytest.raises(LimitError) as excinfo:
        dumps_canonical({"a": "CONTENT_MARKER_XYZ" * 100}, byte_ceiling=16)
    assert excinfo.value.code == LIMIT_SNAPSHOT_BYTES
    assert excinfo.value.limit == "snapshot_bytes"
    assert "CONTENT_MARKER_XYZ" not in str(excinfo.value)  # no content leak


def test_write_over_ceiling_leaves_destination_untouched(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    dest.write_text("old-content", encoding="utf-8")
    with pytest.raises(LimitError) as excinfo:
        write_atomic(dest, {"a": "x" * 100}, byte_ceiling=16)
    assert excinfo.value.code == LIMIT_SNAPSHOT_BYTES
    assert dest.read_text(encoding="utf-8") == "old-content"
    assert list(tmp_path.iterdir()) == [dest]


def test_default_ceiling_is_snapshot_bytes() -> None:
    assert dumps_canonical({"a": 1}).startswith(b'{"a":1}')


@pytest.mark.parametrize("ceiling", [-1, -100, True, 1.5, "100"])
def test_invalid_ceiling_rejected(ceiling: object) -> None:
    with pytest.raises(LimitError) as excinfo:
        dumps_canonical({"a": 1}, byte_ceiling=ceiling)  # type: ignore[arg-type]
    assert excinfo.value.code == LIMIT_INVALID_VALUE
    assert excinfo.value.limit == "snapshot_bytes"


def test_write_with_invalid_ceiling_leaves_destination_untouched(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    dest.write_text("old-content", encoding="utf-8")
    with pytest.raises(LimitError) as excinfo:
        write_atomic(dest, {"a": 1}, byte_ceiling=-5)  # type: ignore[arg-type]
    assert excinfo.value.code == LIMIT_INVALID_VALUE
    assert dest.read_text(encoding="utf-8") == "old-content"
    assert list(tmp_path.iterdir()) == [dest]


# ---------------------------------------------------------------------------
# Atomic replacement
# ---------------------------------------------------------------------------


def test_atomic_replacement(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    dest.write_text("old-content", encoding="utf-8")
    write_atomic(dest, {"z": 1, "a": 2})
    assert dest.read_bytes() == dumps_canonical({"z": 1, "a": 2})
    assert "old-content" not in dest.read_text(encoding="utf-8")
    # No temporary artifacts remain.
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_atomic_replacement_nested(tmp_path: Path) -> None:
    dest = tmp_path / "nested" / "out.json"
    dest.parent.mkdir()
    dest.write_text("old", encoding="utf-8")
    write_atomic(dest, {"k": [1, 2, {"m": "v"}]})
    assert json.loads(dest.read_text(encoding="utf-8")) == {"k": [1, 2, {"m": "v"}]}
    assert [p.name for p in dest.parent.iterdir()] == ["out.json"]


# ---------------------------------------------------------------------------
# Cleanup after simulated write / replace errors
# ---------------------------------------------------------------------------


def test_cleanup_after_replace_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "out.json"
    dest.write_text("old-content", encoding="utf-8")

    def boom_replace(*args: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom_replace)
    with pytest.raises(OSError):
        write_atomic(dest, {"a": 1})

    # Destination preserved and no temporary artifacts remain.
    assert dest.read_text(encoding="utf-8") == "old-content"
    assert list(tmp_path.iterdir()) == [dest]


def test_cleanup_after_fsync_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "out.json"
    dest.write_text("old-content", encoding="utf-8")

    def boom_fsync(*args: object) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", boom_fsync)
    with pytest.raises(OSError):
        write_atomic(dest, {"a": 1})

    assert dest.read_text(encoding="utf-8") == "old-content"
    assert list(tmp_path.iterdir()) == [dest]


def test_cleanup_after_invalid_value(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    dest.write_text("old-content", encoding="utf-8")
    with pytest.raises(InvalidJsonValue):
        write_atomic(dest, {"a": float("nan")})
    assert dest.read_text(encoding="utf-8") == "old-content"
    assert list(tmp_path.iterdir()) == [dest]


def test_no_temp_artifact_on_new_file_success(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    write_atomic(dest, {"a": 1})
    assert list(tmp_path.iterdir()) == [dest]
