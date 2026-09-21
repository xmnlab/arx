"""
title: Closed signatures for immutable arrays, chunks and unique builders.
"""

from __future__ import annotations

import astx

from public import private, public

from irx.analysis.array_values import ResolvedArray, array_storage
from irx.analysis.types import is_assignable, is_signed_integer_type, same_type
from irx.typecheck import typechecked

ARRAY_ARITY = {
    astx.ArrayOperation.APPEND: 2,
    astx.ArrayOperation.RESERVE: 2,
    astx.ArrayOperation.BUILDER_LENGTH: 1,
    astx.ArrayOperation.FINISH: 1,
    astx.ArrayOperation.CHUNK_COUNT: 1,
    astx.ArrayOperation.CHUNK_AT: 2,
    astx.ArrayOperation.COMBINE: 1,
    astx.ArrayOperation.LENGTH: 1,
    astx.ArrayOperation.NULL_COUNT: 1,
    astx.ArrayOperation.OFFSET: 1,
    astx.ArrayOperation.AT: 2,
    astx.ArrayOperation.SLICE: 3,
    astx.ArrayOperation.CONCAT: 2,
    astx.ArrayOperation.COPY: 1,
    astx.ArrayOperation.EQUAL: 2,
}

BUILDER_OPERATIONS = {
    astx.ArrayOperation.APPEND,
    astx.ArrayOperation.RESERVE,
    astx.ArrayOperation.BUILDER_LENGTH,
    astx.ArrayOperation.FINISH,
}
INDEX_OPERATIONS = {
    astx.ArrayOperation.AT,
    astx.ArrayOperation.SLICE,
    astx.ArrayOperation.CHUNK_AT,
    astx.ArrayOperation.RESERVE,
}


@private
@typechecked
def builder_signature(
    operation: astx.ArrayOperation,
    base: astx.ArrayBuilderType,
    element: astx.DataType,
    suffix: str,
    arguments: tuple[astx.DataType, ...],
) -> tuple[str, astx.DataType]:
    """
    title: Resolve mutation or reset-in-place finish without copying builders.
    parameters:
      operation:
        type: astx.ArrayOperation
      base:
        type: astx.ArrayBuilderType
      element:
        type: astx.DataType
      suffix:
        type: str
      arguments:
        type: tuple[astx.DataType, Ellipsis]
    returns:
      type: tuple[str, astx.DataType]
    """
    if operation not in BUILDER_OPERATIONS:
        raise ValueError("builder requires an explicit builder operation")
    if operation is astx.ArrayOperation.APPEND:
        expected = astx.NullableType(element) if base.nullable else element
        if not is_assignable(expected, arguments[1]):
            raise ValueError("builder element is incompatible with its type")
        return f"irx_arrow_array_builder_append_{suffix}", astx.NoneType()
    if operation is astx.ArrayOperation.FINISH:
        return "irx_arrow_array_builder_build", astx.ArrayType(
            base.element_type, nullable=base.nullable
        )
    if operation is astx.ArrayOperation.BUILDER_LENGTH:
        return "irx_arrow_array_builder_length", astx.Int64()
    return "irx_arrow_array_builder_reserve", astx.NoneType()


@private
@typechecked
def value_signature(
    operation: astx.ArrayOperation,
    base: astx.ArrayType | astx.ChunkedArrayType,
    element: astx.DataType,
    suffix: str,
) -> tuple[str, astx.DataType]:
    """
    title: Resolve only explicitly supported physical or logical operations.
    parameters:
      operation:
        type: astx.ArrayOperation
      base:
        type: astx.ArrayType | astx.ChunkedArrayType
      element:
        type: astx.DataType
      suffix:
        type: str
    returns:
      type: tuple[str, astx.DataType]
    """
    chunked = isinstance(base, astx.ChunkedArrayType)
    prefix = "irx_arrow_chunked" if chunked else "irx_arrow_array"
    if operation in BUILDER_OPERATIONS:
        raise ValueError("builder operation requires an array_builder")
    if operation is astx.ArrayOperation.AT:
        return f"{prefix}_get_{suffix}", astx.NullableType(element)
    if operation is astx.ArrayOperation.EQUAL:
        return f"{prefix}_equal", astx.Boolean()
    if operation in {
        astx.ArrayOperation.COMBINE,
        astx.ArrayOperation.CHUNK_AT,
        astx.ArrayOperation.CHUNK_COUNT,
    }:
        if not chunked:
            raise ValueError("chunk operation requires a chunked_array")
        if operation is astx.ArrayOperation.CHUNK_COUNT:
            return f"{prefix}_num_chunks", astx.Int64()
        name = (
            "chunk" if operation is astx.ArrayOperation.CHUNK_AT else "combine"
        )
        return f"{prefix}_{name}", astx.ArrayType(
            base.element_type, nullable=base.nullable
        )
    if chunked and operation is astx.ArrayOperation.OFFSET:
        raise ValueError("chunked arrays have no single physical offset")
    name = operation.value.removeprefix("array_")
    result: astx.DataType = astx.Int64()
    if operation in {
        astx.ArrayOperation.SLICE,
        astx.ArrayOperation.CONCAT,
        astx.ArrayOperation.COPY,
    }:
        result = base
    return f"{prefix}_{name}", result


@public
@typechecked
def resolve_query(
    operation: astx.ArrayOperation, arguments: tuple[astx.DataType, ...]
) -> ResolvedArray:
    """
    title: Resolve element conversions, result ownership and native symbol.
    parameters:
      operation:
        type: astx.ArrayOperation
      arguments:
        type: tuple[astx.DataType, Ellipsis]
    returns:
      type: ResolvedArray
    """
    if len(arguments) != ARRAY_ARITY[operation]:
        raise ValueError("array query has invalid argument count")
    base = arguments[0]
    if (
        not isinstance(
            base,
            (astx.ArrayType, astx.ArrayBuilderType, astx.ChunkedArrayType),
        )
        or (storage := array_storage(base)) is None
    ):
        raise ValueError("array query requires a supported primitive array")
    element, abi_type, type_id, suffix = storage
    if operation in INDEX_OPERATIONS and not all(
        is_signed_integer_type(item) for item in arguments[1:]
    ):
        raise ValueError("array indices and lengths require signed integers")
    if operation in {astx.ArrayOperation.CONCAT, astx.ArrayOperation.EQUAL}:
        if not same_type(base, arguments[1]):
            raise ValueError(
                "array operands require matching element and nullability types"
            )
    if isinstance(base, astx.ArrayBuilderType):
        symbol, result = builder_signature(
            operation, base, element, suffix, arguments
        )
    else:
        symbol, result = value_signature(operation, base, element, suffix)
    return ResolvedArray(
        symbol,
        result,
        element,
        abi_type,
        type_id,
        arguments,
        operation,
        required_features=("core", "array", "dataframe")
        if isinstance(base, astx.ChunkedArrayType)
        else ("core", "array"),
    )
