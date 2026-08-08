"""Shared immutable envelope and canonical JSON rules for P0 contracts."""

from __future__ import annotations

import hashlib
import json
import types
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any, ClassVar, Literal, Mapping, Union, get_args, get_origin

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictStr,
    ValidationInfo,
    model_validator,
)
from typing_extensions import Self


_SKIP_HASH_VALIDATION_CONTEXT = "canonical_contract_skip_hash_validation"


def _parse_decimal(value: Any) -> Decimal:
    """Accept exact Decimal/string inputs and reject binary-float money inputs."""

    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise ValueError("canonical decimal fields require a Decimal or decimal string")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, str) and value.strip() == value and value:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid canonical decimal string") from exc
    else:
        raise ValueError("canonical decimal fields require a Decimal or decimal string")
    if not parsed.is_finite():
        raise ValueError("canonical decimal fields must be finite")
    return parsed


def decimal_to_json(value: Decimal) -> str:
    """Serialize a Decimal without binary conversion or exponent notation."""

    return format(value, "f")


CanonicalDecimal = Annotated[
    Decimal,
    BeforeValidator(_parse_decimal),
    PlainSerializer(decimal_to_json, return_type=str, when_used="json"),
]


def _require_literal_true(value: Any) -> bool:
    if value is not True:
        raise ValueError("field must be the JSON boolean true")
    return True


StrictTrue = Annotated[Literal[True], BeforeValidator(_require_literal_true)]


def canonicalize(value: Any) -> Any:
    """Return a deterministic JSON-compatible representation."""

    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        return decimal_to_json(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, Mapping):
        return {str(key): canonicalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        canonicalize(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate canonical JSON key: {key}")
        payload[key] = value
    return payload


def _wire_value_for_strict_validation(annotation: Any, value: Any) -> Any:
    """Convert only JSON container/time shapes; leave scalar types strict."""

    origin = get_origin(annotation)
    if origin is Annotated:
        return _wire_value_for_strict_validation(get_args(annotation)[0], value)
    if origin in (Union, types.UnionType):
        if value is None:
            return None
        union_types = tuple(item for item in get_args(annotation) if item is not type(None))
        for item in union_types:
            candidate = get_args(item)[0] if get_origin(item) is Annotated else item
            if candidate in (datetime, AwareDatetime):
                return _wire_value_for_strict_validation(candidate, value)
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                return _wire_value_for_strict_validation(candidate, value)
        return value
    if annotation in (datetime, AwareDatetime):
        if not isinstance(value, str):
            return value
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return value
    if origin is tuple:
        if not isinstance(value, list):
            return value
        item_types = get_args(annotation)
        item_type = item_types[0] if item_types else Any
        return tuple(_wire_value_for_strict_validation(item_type, item) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if not isinstance(value, dict):
            return value
        return {
            key: _wire_value_for_strict_validation(
                annotation.model_fields[key].annotation,
                item,
            )
            if key in annotation.model_fields
            else item
            for key, item in value.items()
        }
    return value


def _strict_wire_payload(model_type: type[BaseModel], payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    return {
        key: _wire_value_for_strict_validation(model_type.model_fields[key].annotation, value)
        if key in model_type.model_fields
        else value
        for key, value in payload.items()
    }


class CanonicalContract(BaseModel):
    """Frozen, content-addressed base for every cross-layer P0 contract."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    HASH_ALGORITHM: ClassVar[str] = "sha256"
    BUILD_DEFAULTS: ClassVar[Mapping[str, Any]] = {"supersedes_id": None}

    schema_version: StrictStr
    trace_id: StrictStr = Field(min_length=1, max_length=128)
    created_at: AwareDatetime
    producer: StrictStr = Field(min_length=1, max_length=128)
    content_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_id: StrictStr | None = Field(min_length=1, max_length=160)

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        if kwargs.get("strict") is False:
            raise ValueError("canonical contracts cannot disable strict validation")
        kwargs["strict"] = True
        return super().model_validate(obj, **kwargs)

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> Self:
        """Parse canonical JSON without weakening integer, boolean, or string types."""

        if kwargs.get("strict") is False:
            raise ValueError("canonical contracts cannot disable strict validation")
        try:
            payload = json.loads(
                json_data,
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid canonical contract JSON") from exc
        return cls.model_validate(
            _strict_wire_payload(cls, payload),
            **{**kwargs, "strict": True},
        )

    def hash_payload(self) -> dict[str, Any]:
        """Return the full immutable body except its self-referential hash."""

        return self.model_dump(mode="python", exclude={"content_hash"})

    def calculated_content_hash(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.hash_payload())).hexdigest()

    def canonical_json(self) -> str:
        """Serialize this contract deterministically for cross-repository wire use."""

        return canonical_json_bytes(self.model_dump(mode="python")).decode("utf-8")

    @model_validator(mode="after")
    def _verify_content_hash(self, info: ValidationInfo) -> Self:
        context = info.context if isinstance(info.context, dict) else {}
        if context.get(_SKIP_HASH_VALIDATION_CONTEXT) is True:
            return self
        calculated = self.calculated_content_hash()
        if self.content_hash != calculated:
            raise ValueError("content_hash does not match canonical contract content")
        return self

    @classmethod
    def build(cls, **values: Any) -> Self:
        """Validate producer inputs, calculate the hash, then validate as a consumer."""

        if "content_hash" in values:
            raise ValueError("build() calculates content_hash; consumers must use model_validate")
        producer_values: dict[str, Any] = {}
        for model_type in reversed(cls.__mro__):
            producer_values.update(model_type.__dict__.get("BUILD_DEFAULTS", {}))
        producer_values.update(values)
        draft = cls.model_validate(
            {**producer_values, "content_hash": "0" * 64},
            context={_SKIP_HASH_VALIDATION_CONTEXT: True},
        )
        return cls.model_validate(
            {
                **draft.model_dump(mode="python"),
                "content_hash": draft.calculated_content_hash(),
            }
        )

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Forbid Pydantic's validation-bypassing copy path for immutable contracts."""

        del update, deep
        raise TypeError("canonical contracts cannot be copied or updated; build a new object")


class FrozenValue(BaseModel):
    """Frozen strict base for nested contract values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


DataQuality = Annotated[
    str,
    Field(pattern=r"^(HIGH|MEDIUM|LOW|UNKNOWN)$"),
]
