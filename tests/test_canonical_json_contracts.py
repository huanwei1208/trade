from __future__ import annotations

import json

import pytest

from trade.platform.contracts.messages import (
    CanonicalJsonError,
    CanonicalJsonErrorCode,
    decode_bounded_json_v1,
    encode_canonical_json_v1,
)


def _assert_decode_error(raw: bytes, code: CanonicalJsonErrorCode) -> None:
    with pytest.raises(CanonicalJsonError) as raised:
        decode_bounded_json_v1(raw)

    assert raised.value.code is code
    assert str(raised.value) == code.value


def _assert_encode_error(value: object, code: CanonicalJsonErrorCode) -> None:
    with pytest.raises(CanonicalJsonError) as raised:
        encode_canonical_json_v1(value)

    assert raised.value.code is code
    assert str(raised.value) == code.value


def test_canonical_json_round_trip_preserves_scalars_and_exact_escape_policy() -> None:
    value = {
        "controls": "\x00\b\t\n\f\r\x1f",
        "decomposed": "e\u0301",
        "punctuation": '/\\"',
        "text": "比特币",
        "composed": "\u00e9",
    }

    canonical = encode_canonical_json_v1(value)

    assert canonical == (
        b'{"composed":"\xc3\xa9","controls":"\\u0000\\b\\t\\n\\f\\r\\u001f",'
        b'"decomposed":"e\xcc\x81","punctuation":"/\\\\\\"","text":"\xe6\xaf\x94\xe7\x89\xb9\xe5\xb8\x81"}'
    )
    assert b"\\/" not in canonical
    assert b"\\u00e9" not in canonical
    assert decode_bounded_json_v1(canonical) == value
    assert encode_canonical_json_v1(decode_bounded_json_v1(canonical)) == canonical


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"null", None),
        (b"true", True),
        (b"false", False),
        (b'{"array":[],"object":{}}', {"array": [], "object": {}}),
    ],
)
def test_canonical_json_accepts_the_closed_scalar_and_empty_container_set(
    raw: bytes,
    expected: object,
) -> None:
    assert decode_bounded_json_v1(raw) == expected
    assert encode_canonical_json_v1(expected) == raw


def test_canonical_json_sorts_decoded_unicode_scalar_sequences_without_normalization() -> None:
    raw = (
        b'{"\\ud83d\\ude00":"astral","\\ue000":"private",'
        b'"e\\u0301":"decomposed","\\u00e9":"composed"}'
    )

    decoded = decode_bounded_json_v1(raw)
    canonical = encode_canonical_json_v1(decoded)

    assert isinstance(decoded, dict)
    assert canonical == (
        b'{"e\xcc\x81":"decomposed","\xc3\xa9":"composed",'
        b'"\xee\x80\x80":"private","\xf0\x9f\x98\x80":"astral"}'
    )
    assert list(decoded) == ["😀", "\ue000", "e\u0301", "\u00e9"]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":1,"\\u0061":2}',
        b'{"\\ud83d\\ude00":1,"\xf0\x9f\x98\x80":2}',
    ],
)
def test_canonical_json_rejects_duplicate_decoded_keys_before_materialization(raw: bytes) -> None:
    _assert_decode_error(raw, CanonicalJsonErrorCode.DUPLICATE_KEY)


def test_canonical_json_enforces_raw_input_budget_before_decode() -> None:
    exact = b"0" + (b" " * 65_535)

    assert decode_bounded_json_v1(exact) == 0
    _assert_decode_error(exact + b" ", CanonicalJsonErrorCode.RAW_BYTES_EXCEEDED)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"\xef\xbb\xbf{}", CanonicalJsonErrorCode.BOM_FORBIDDEN),
        (b'"\xff"', CanonicalJsonErrorCode.INVALID_UTF8),
        (b'"\\ud800"', CanonicalJsonErrorCode.INVALID_SURROGATE),
        (b'"\\udc00"', CanonicalJsonErrorCode.INVALID_SURROGATE),
        (b'"\\ud800\\u0061"', CanonicalJsonErrorCode.INVALID_SURROGATE),
        (b'"\x01"', CanonicalJsonErrorCode.INVALID_SYNTAX),
        (b'"\\x00"', CanonicalJsonErrorCode.INVALID_SYNTAX),
    ],
)
def test_canonical_json_rejects_bom_invalid_utf8_surrogates_and_bad_strings(
    raw: bytes,
    code: CanonicalJsonErrorCode,
) -> None:
    _assert_decode_error(raw, code)


def test_canonical_json_string_and_key_limits_use_decoded_utf8_bytes() -> None:
    exact_ascii = ("x" * 2_048).encode()
    exact_cjk = ("界" * 682 + "ab").encode()

    assert decode_bounded_json_v1(b'"' + exact_ascii + b'"') == "x" * 2_048
    assert decode_bounded_json_v1(b'"' + exact_cjk + b'"') == "界" * 682 + "ab"
    assert decode_bounded_json_v1(b'{"' + exact_ascii + b'":0}') == {"x" * 2_048: 0}
    _assert_decode_error(
        b'"' + exact_ascii + b'x"',
        CanonicalJsonErrorCode.STRING_BYTES_EXCEEDED,
    )
    _assert_decode_error(
        b'"' + exact_cjk + "界".encode() + b'"',
        CanonicalJsonErrorCode.STRING_BYTES_EXCEEDED,
    )


def test_canonical_json_container_depth_is_iterative_and_exact() -> None:
    depth_eight = (b"[" * 8) + b"0" + (b"]" * 8)
    depth_nine = (b"[" * 9) + b"0" + (b"]" * 9)
    depth_fifteen_hundred = (b"[" * 1_500) + b"0" + (b"]" * 1_500)

    assert decode_bounded_json_v1(b"0") == 0
    assert decode_bounded_json_v1(depth_eight) == [[[[[[[[0]]]]]]]]
    _assert_decode_error(depth_nine, CanonicalJsonErrorCode.CONTAINER_DEPTH_EXCEEDED)
    _assert_decode_error(
        depth_fifteen_hundred,
        CanonicalJsonErrorCode.CONTAINER_DEPTH_EXCEEDED,
    )


@pytest.mark.parametrize("token", [b"0", b"1", b"9999999999999999999"])
def test_canonical_json_accepts_canonical_non_negative_integer_tokens(token: bytes) -> None:
    assert decode_bounded_json_v1(token) == int(token)


@pytest.mark.parametrize(
    "token",
    [
        b"-1",
        b"00",
        b"01",
        b"10000000000000000000",
        b"1.0",
        b"1e1",
        b"NaN",
        b"Infinity",
        b"-Infinity",
    ],
)
def test_canonical_json_rejects_unsupported_number_spellings(token: bytes) -> None:
    _assert_decode_error(token, CanonicalJsonErrorCode.INVALID_INTEGER)


def test_canonical_json_per_container_item_limit_is_exact() -> None:
    exact_array = b"[" + b",".join(b"0" for _ in range(100)) + b"]"
    over_array = b"[" + b",".join(b"0" for _ in range(101)) + b"]"
    exact_object = json.dumps(
        {f"k{index:03d}": 0 for index in range(100)},
        separators=(",", ":"),
    ).encode()
    over_object = json.dumps(
        {f"k{index:03d}": 0 for index in range(101)},
        separators=(",", ":"),
    ).encode()

    decoded_array = decode_bounded_json_v1(exact_array)
    decoded_object = decode_bounded_json_v1(exact_object)

    assert isinstance(decoded_array, list)
    assert isinstance(decoded_object, dict)
    assert len(decoded_array) == 100
    assert len(decoded_object) == 100
    _assert_decode_error(over_array, CanonicalJsonErrorCode.CONTAINER_ITEMS_EXCEEDED)
    _assert_decode_error(over_object, CanonicalJsonErrorCode.CONTAINER_ITEMS_EXCEEDED)


def test_canonical_json_aggregate_item_limit_is_exact() -> None:
    exact_value = [[0] * 100 for _ in range(10)] + [[0] * 13]
    over_value = [[0] * 100 for _ in range(10)] + [[0] * 14]
    exact_raw = json.dumps(exact_value, separators=(",", ":")).encode()
    over_raw = json.dumps(over_value, separators=(",", ":")).encode()

    assert decode_bounded_json_v1(exact_raw) == exact_value
    _assert_decode_error(over_raw, CanonicalJsonErrorCode.AGGREGATE_ITEMS_EXCEEDED)
    assert encode_canonical_json_v1(exact_value) == exact_raw
    _assert_encode_error(over_value, CanonicalJsonErrorCode.AGGREGATE_ITEMS_EXCEEDED)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b" ",
        b"{} {}",
        b'{"a"}',
        b'{"a":}',
        b'{"a":0,}',
        b"[0,]",
        b"[",
        b"{",
        b"truefalse",
        b"nul",
    ],
)
def test_canonical_json_rejects_malformed_grammar_with_one_stable_error(raw: bytes) -> None:
    _assert_decode_error(raw, CanonicalJsonErrorCode.INVALID_SYNTAX)


@pytest.mark.parametrize(
    "value",
    [
        -1,
        10_000_000_000_000_000_000,
        1.0,
        float("nan"),
        b"binary",
        ("tuple",),
        {1: "non-string key"},
    ],
)
def test_canonical_json_encoder_rejects_values_outside_the_closed_v1_model(
    value: object,
) -> None:
    expected = (
        CanonicalJsonErrorCode.INVALID_INTEGER
        if isinstance(value, int) and not isinstance(value, bool)
        else CanonicalJsonErrorCode.UNSUPPORTED_VALUE
    )
    _assert_encode_error(value, expected)


def test_canonical_json_encoder_enforces_owner_output_budget_during_emission() -> None:
    assert encode_canonical_json_v1(0, max_bytes=1) == b"0"
    assert encode_canonical_json_v1("x", max_bytes=3) == b'"x"'
    with pytest.raises(CanonicalJsonError) as raised:
        encode_canonical_json_v1("x", max_bytes=2)

    assert raised.value.code is CanonicalJsonErrorCode.OUTPUT_BYTES_EXCEEDED


def test_canonical_json_global_output_budget_is_exact() -> None:
    exact = {f"k{index:02d}": "x" * 2_048 for index in range(31)}
    exact["k31"] = "x" * 1_759
    over = {**exact, "k31": "x" * 1_760}

    canonical = encode_canonical_json_v1(exact)

    assert len(canonical) == 65_536
    assert decode_bounded_json_v1(canonical) == exact
    _assert_encode_error(over, CanonicalJsonErrorCode.OUTPUT_BYTES_EXCEEDED)


def test_canonical_json_public_functions_reject_wrong_boundary_types() -> None:
    with pytest.raises(TypeError, match="bytes"):
        decode_bounded_json_v1("{}")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer"):
        encode_canonical_json_v1({}, max_bytes=True)
    with pytest.raises(ValueError, match="1..65,536"):
        encode_canonical_json_v1({}, max_bytes=65_537)
