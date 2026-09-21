# mypy: disable-error-code=no-redef
# mypy: disable-error-code=untyped-decorator
"""
title: Resolve immutable array construction and the closed query signatures.
"""

from __future__ import annotations

import astx

from irx.analysis.array_queries import ARRAY_ARITY, resolve_query
from irx.analysis.array_values import ResolvedArray, array_storage
from irx.analysis.handlers.base import (
    SemanticAnalyzerCore,
    SemanticVisitorMixinBase,
)
from irx.analysis.ownership import typed_resource_ownership
from irx.analysis.resolved_nodes import OwnershipKind
from irx.analysis.types import is_assignable
from irx.diagnostics import DiagnosticCodes
from irx.typecheck import typechecked


@typechecked
class ArrayValueVisitorMixin(SemanticVisitorMixinBase):
    """
    title: Keep columnar meaning, signatures and lifetime facts in analysis.
    """

    def array_error(self, node: astx.AST, message: str) -> None:
        """
        title: Reject an invalid array operation before native lowering.
        parameters:
          node:
            type: astx.AST
          message:
            type: str
        """
        self.context.diagnostics.add(
            message, node=node, code=DiagnosticCodes.SEMANTIC_TYPE_MISMATCH
        )
        self._set_type(node, None)

    def array_result(
        self, node: astx.DataType, resolved: ResolvedArray
    ) -> None:
        """
        title: Attach resolved storage and shared immutable result ownership.
        parameters:
          node:
            type: astx.DataType
          resolved:
            type: ResolvedArray
        """
        self._semantic(node).resolved_array = resolved
        self._set_type(node, resolved.result_type)
        if isinstance(
            resolved.result_type,
            (astx.ArrayType, astx.ArrayBuilderType, astx.ChunkedArrayType),
        ):
            self._set_resource_ownership(
                node,
                typed_resource_ownership(
                    resolved.result_type, OwnershipKind.OWNED
                ),
            )

    @SemanticAnalyzerCore.visit.dispatch
    def visit(self, node: astx.ArrayLiteral) -> None:
        """
        title: Validate scalar values against the declared element type.
        parameters:
          node:
            type: astx.ArrayLiteral
        """
        storage = array_storage(node.type_)
        if storage is None:
            self.array_error(
                node,
                "array construction requires a supported primitive element",
            )
            return
        element, abi_type, type_id, suffix = storage
        expected = (
            astx.NullableType(element) if node.type_.nullable else element
        )
        if isinstance(node.type_, astx.ArrayBuilderType) and node.values:
            self.array_error(
                node, "array_builder construction takes no values"
            )
            return
        if isinstance(node.type_, astx.ChunkedArrayType):
            expected = astx.ArrayType(
                node.type_.element_type, nullable=node.type_.nullable
            )
        arguments: list[astx.DataType] = []
        for value in node.values:
            self.visit(value)
            actual = self._expr_type(value)
            if (
                not self._require_value_expression(
                    value,
                    context="Array element",
                    allow_none=node.type_.nullable,
                )
                or actual is None
            ):
                continue
            if not is_assignable(expected, actual):
                self.array_error(
                    value,
                    "array element is incompatible with its declared type",
                )
            arguments.append(actual)
        self.array_result(
            node,
            ResolvedArray(
                f"irx_arrow_array_builder_append_{suffix}",
                node.type_,
                element,
                abi_type,
                type_id,
                tuple(arguments),
                required_features=("core", "array", "dataframe")
                if isinstance(node.type_, astx.ChunkedArrayType)
                else ("core", "array"),
            ),
        )

    @SemanticAnalyzerCore.visit.dispatch
    def visit(self, node: astx.ArrayQuery) -> None:
        """
        title: Resolve closed array operations without backend type discovery.
        parameters:
          node:
            type: astx.ArrayQuery
        """
        arguments: list[astx.DataType] = []
        for index, value in enumerate(node.arguments):
            self.visit(value)
            self._require_value_expression(
                value,
                context="Array argument",
                allow_none=node.operation is astx.ArrayOperation.APPEND
                and index == 1,
            )
            actual = self._expr_type(value)
            if actual is not None:
                arguments.append(actual)
        if len(arguments) != ARRAY_ARITY[node.operation] or len(
            arguments
        ) != len(node.arguments):
            self.array_error(
                node,
                f"{node.operation.value} has invalid argument count or types",
            )
            return
        try:
            resolved = resolve_query(node.operation, tuple(arguments))
        except ValueError as error:
            self.array_error(node, str(error))
            return
        self.array_result(node, resolved)
