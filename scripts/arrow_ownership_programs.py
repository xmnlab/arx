"""
title: Generated ownership programs for native sanitizer gates.
summary: >-
  These ASTx programs exercise IRx capabilities. They are not claims of Arx
  parser support for user-defined generators.
"""

from __future__ import annotations

import astx


def block(*nodes: astx.AST) -> astx.Block:
    """
    title: Build a fresh statement block without shared AST nodes.
    parameters:
      nodes:
        type: astx.AST
        variadic: positional
    returns:
      type: astx.Block
    """
    result = astx.Block()
    for node in nodes:
        result.append(node)
    return result


def tensor(value: int) -> astx.TensorLiteral:
    """
    title: Build a small Arrow-backed managed value.
    parameters:
      value:
        type: int
    returns:
      type: astx.TensorLiteral
    """
    return astx.TensorLiteral(
        (astx.LiteralInt32(value),), element_type=astx.Int32(), shape=(1,)
    )


def main_function(body: astx.Block) -> astx.FunctionDef:
    """
    title: Wrap one native sanitizer program entry point.
    parameters:
      body:
        type: astx.Block
    returns:
      type: astx.FunctionDef
    """
    return astx.FunctionDef(
        astx.FunctionPrototype("main", astx.Arguments(), astx.Int32()), body
    )


def class_program() -> astx.Module:
    """
    title: Exercise shared class owners, Arrow field replacement and return.
    returns:
      type: astx.Module
    """
    module = astx.Module()
    module.block.append(
        astx.ClassDefStmt(
            name="Box",
            attributes=[
                astx.VariableDeclaration(
                    "values",
                    astx.TensorType(astx.Int32(), shape=(1,)),
                    mutability=astx.MutabilityKind.mutable,
                    value=tensor(7),
                )
            ],
        )
    )
    module.block.append(
        astx.FunctionDef(
            astx.FunctionPrototype(
                "make_box", astx.Arguments(), astx.ClassType("Box")
            ),
            block(astx.FunctionReturn(astx.ClassConstruct("Box"))),
        )
    )
    module.block.append(
        main_function(
            block(
                astx.VariableDeclaration(
                    "first",
                    astx.ClassType("Box"),
                    value=astx.FunctionCall("make_box", []),
                ),
                astx.VariableDeclaration(
                    "second",
                    astx.ClassType("Box"),
                    value=astx.Identifier("first"),
                ),
                astx.BinaryOp(
                    "=",
                    astx.FieldAccess(astx.Identifier("second"), "values"),
                    tensor(9),
                ),
                astx.FunctionReturn(astx.LiteralInt32(0)),
            )
        )
    )
    return module


def generator_program(
    *, early_close: bool, fail_after_resume: bool
) -> astx.Module:
    """
    title: Exercise suspended owners on exhaustion, early close and failure.
    parameters:
      early_close:
        type: bool
      fail_after_resume:
        type: bool
    returns:
      type: astx.Module
    """
    module = astx.Module()
    body = block(
        astx.VariableDeclaration(
            "before",
            astx.String(),
            value=astx.BinaryOp(
                "+", astx.LiteralString("owned"), astx.LiteralString(" before")
            ),
        ),
        astx.VariableDeclaration(
            "data",
            astx.TensorType(astx.Int32(), shape=(1,)),
            value=tensor(3),
        ),
        astx.YieldStmt(astx.LiteralInt32(1)),
        astx.VariableDeclaration(
            "after",
            astx.String(),
            value=astx.BinaryOp(
                "+", astx.LiteralString("owned"), astx.LiteralString(" after")
            ),
        ),
    )
    if fail_after_resume:
        body.append(astx.AssertStmt(astx.LiteralBoolean(False)))
    body.append(astx.YieldStmt(astx.LiteralInt32(2)))
    module.block.append(
        astx.FunctionDef(
            astx.FunctionPrototype(
                "values", astx.Arguments(), astx.GeneratorType(astx.Int32())
            ),
            body,
        )
    )
    loop_body = block(astx.BreakStmt()) if early_close else block()
    module.block.append(
        main_function(
            block(
                astx.ForInLoopStmt(
                    astx.Identifier("item"),
                    astx.FunctionCall("values", []),
                    loop_body,
                ),
                astx.FunctionReturn(astx.LiteralInt32(0)),
            )
        )
    )
    return module


def ownership_programs() -> tuple[tuple[str, astx.Module, int], ...]:
    """
    title: Return independent generated programs and expected exit statuses.
    returns:
      type: tuple[tuple[str, astx.Module, int], Ellipsis]
    """
    return (
        ("class_owners", class_program(), 0),
        (
            "generator_exhaustion",
            generator_program(early_close=False, fail_after_resume=False),
            0,
        ),
        (
            "generator_early_close",
            generator_program(early_close=True, fail_after_resume=False),
            0,
        ),
        (
            "generator_failure",
            generator_program(early_close=False, fail_after_resume=True),
            1,
        ),
    )
