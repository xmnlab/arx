"""
title: First-class columnar array type and literal syntax.
"""

from __future__ import annotations

from typing import cast

import astx

from arx.exceptions import ParserException
from arx.lexer import TokenKind
from arx.parser.base import ParserMixinBase
from arx.parser.descriptors import DescriptorParser


class ArrayParser:
    """
    title: Parse array structure while leaving storage and validity to IRx.
    attributes:
      parser:
        type: ParserMixinBase
    """

    parser: ParserMixinBase

    def __init__(self, parser: ParserMixinBase) -> None:
        """
        title: Share the parser token stream without semantic binding state.
        parameters:
          parser:
            type: ParserMixinBase
        """
        self.parser = parser

    def type(
        self, name: str = "array"
    ) -> astx.ArrayType | astx.ArrayBuilderType | astx.ChunkedArrayType:
        """
        title: Parse the bracketed logical element and optional nullability.
        parameters:
          name:
            type: str
        returns:
          type: astx.ArrayType | astx.ArrayBuilderType | astx.ChunkedArrayType
        """
        parser = self.parser
        parser._consume_operator("[")
        logical = DescriptorParser(parser).logical_type()
        nullable = False
        if parser._is_operator("|"):
            parser._consume_operator("|")
            if parser.tokens.cur_tok.kind != TokenKind.none_literal:
                raise ParserException("Array nullability expects none.")
            parser.tokens.get_next_token()
            nullable = True
        parser._consume_operator("]")
        types: dict[
            str,
            type[astx.ArrayType]
            | type[astx.ArrayBuilderType]
            | type[astx.ChunkedArrayType],
        ] = {
            "array": astx.ArrayType,
            "array_builder": astx.ArrayBuilderType,
            "chunked_array": astx.ChunkedArrayType,
        }
        return types[name](logical, nullable=nullable)

    def literal(
        self, loc: astx.SourceLocation, name: str = "array"
    ) -> astx.ArrayLiteral:
        """
        title: Parse a typed scalar sequence, including an empty sequence.
        parameters:
          loc:
            type: astx.SourceLocation
          name:
            type: str
        returns:
          type: astx.ArrayLiteral
        """
        type_ = self.type(name)
        parser = self.parser
        parser._consume_operator("(")
        values: list[astx.Expr] = []
        while not parser._is_operator(")"):
            values.append(cast(astx.Expr, parser.parse_expression()))
            if parser._is_operator(")"):
                break
            parser._consume_operator(",")
        parser._consume_operator(")")
        return astx.ArrayLiteral(type_, tuple(values), loc=loc)
