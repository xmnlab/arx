"""
title: Conservative validity proofs for direct local scalar predicates.
"""

from __future__ import annotations

import astx

from public import public

from irx.analysis.resolved_nodes import SemanticInfo
from irx.typecheck import typechecked


@public
@typechecked
def nullable_branch_symbol(condition: astx.AST, truth: bool) -> str | None:
    """
    title: Resolve a local validity proof from a predicate or its negation.
    parameters:
      condition:
        type: astx.AST
      truth:
        type: bool
    returns:
      type: str | None
    """
    if isinstance(condition, astx.UnaryOp) and condition.op_code == "!":
        return nullable_branch_symbol(condition.operand, not truth)
    if not isinstance(condition, astx.NullableQuery) or not isinstance(
        condition.operand, astx.Identifier
    ):
        return None
    proves_valid = (
        condition.operation is astx.NullableOperation.IS_VALID and truth
    ) or (condition.operation is astx.NullableOperation.IS_NULL and not truth)
    info = getattr(condition.operand, "semantic", None)
    if (
        not proves_valid
        or not isinstance(info, SemanticInfo)
        or info.resolved_symbol is None
        or info.resolved_symbol.kind not in {"variable", "argument"}
    ):
        return None
    return info.resolved_symbol.symbol_id
