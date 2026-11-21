"""Normalize a tree-sitter tree the way dry4clj normalizes a Clojure form.

The name in call position stays: `filter`, `Println`, `map`, an operator, the
type constructed by `new`. Local names, field names, type names in argument
position, and literals become generic markers. Two functions that call the
same operations in the same shape therefore share a fingerprint set even when
their locals differ.
"""

from __future__ import annotations

from dryer.shape import K
from dryer.treesitter import node_text

_SKIP = {
    "comment",
    "line_comment",
    "block_comment",
    "documentation_comment",
    "doc_comment",
}

_IDENTIFIERS = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
    "package_identifier",
}

_LITERALS = {
    "string",
    "string_literal",
    "interpreted_string_literal",
    "raw_string_literal",
    "verbatim_string_literal",
    "interpolated_string_expression",
    "char_literal",
    "rune_literal",
    "character_literal",
    "number",
    "integer",
    "float",
    "real_literal",
    "decimal_integer_literal",
    "hex_integer_literal",
    "octal_integer_literal",
    "binary_integer_literal",
    "decimal_floating_point_literal",
    "hex_floating_point_literal",
    "int_literal",
    "float_literal",
    "imaginary_literal",
    "integer_literal",
    "true",
    "false",
    "null",
    "nil",
    "none",
    "undefined",
    "null_literal",
    "boolean_literal",
    "template_string",
    "regex",
    "regex_literal",
}

_OPERATORS = {
    "+",
    "-",
    "*",
    "/",
    "%",
    "**",
    "==",
    "!=",
    "<",
    ">",
    "<=",
    ">=",
    "===",
    "!==",
    "&&",
    "||",
    "&",
    "|",
    "^",
    "<<",
    ">>",
    ">>>",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<=",
    ">>=",
    ">>>=",
    "!",
    "~",
    "++",
    "--",
    "and",
    "or",
    "not",
    "??",
    "?.",
    "=",
    ":=",
    "=>",
    "?",
}

_CALLS = {
    "call",
    "call_expression",
    "invocation_expression",
    "method_invocation",
    "object_creation_expression",
    "new_expression",
}

_ATTRIBUTES = {
    "attribute",
    "member_expression",
    "member_access_expression",
    "conditional_access_expression",
    "member_binding_expression",
    "selector_expression",
    "field_access",
    "field_expression",
}

# Read as a path when called or constructed, so each name in it stays.
_SCOPED = {
    "scoped_identifier",
    "scoped_type_identifier",
    "generic_type",
    "qualified_name",
    "alias_qualified_name",
    "generic_name",
}

_CALL_TAILS = {"argument_list", "arguments", "token_tree", "initializer_expression"}
_INTERPOLATIONS = {"interpolation", "template_substitution"}
_TYPE_ARGS = {"type_arguments", "type_parameters", "type_argument_list", "type_parameter_list"}

# PowerShell-specific helpers: expression wrapper chain collapses when single-child
# so real operators, commands, and member calls dominate fingerprints.
_PS_WRAPPERS = {
    "pipeline",
    "pipeline_chain",
    "logical_expression",
    "bitwise_expression",
    "comparison_expression",
    "additive_expression",
    "multiplicative_expression",
    "format_expression",
    "range_expression",
    "array_literal_expression",
    "unary_expression",
    "argument_expression",
    "logical_argument_expression",
    "bitwise_argument_expression",
    "comparison_argument_expression",
    "additive_argument_expression",
    "multiplicative_argument_expression",
    "format_argument_expression",
    "range_argument_expression",
    "left_assignment_expression",
}
_PS_CONSTANTS = {"$true", "$false", "$null"}
_PS_OPERATOR_TOKENS = {
    "-and",
    "-or",
    "-xor",
    "-not",
    "-band",
    "-bor",
    "-bxor",
    "-bnot",
    "-shl",
    "-shr",
    "-f",
    "-join",
    "-split",
    "-csplit",
    "-isplit",
    "-replace",
    "-creplace",
    "-ireplace",
    "-is",
    "-isnot",
    "-as",
    "-in",
    "-cin",
    "-iin",
    "-notin",
    "-cnotin",
    "-inotin",
    "-contains",
    "-ccontains",
    "-icontains",
    "-notcontains",
    "-cnotcontains",
    "-inotcontains",
    "-eq",
    "-ceq",
    "-ieq",
    "-ne",
    "-cne",
    "-ine",
    "-gt",
    "-cgt",
    "-igt",
    "-ge",
    "-cge",
    "-ige",
    "-lt",
    "-clt",
    "-ilt",
    "-le",
    "-cle",
    "-ile",
    "-like",
    "-clike",
    "-ilike",
    "-notlike",
    "-cnotlike",
    "-inotlike",
    "-match",
    "-cmatch",
    "-imatch",
    "-notmatch",
    "-cnotmatch",
    "-inotmatch",
}

_DATA: bytes = b""
_LANGUAGE: str = ""


def normalize(node, data: bytes, omit=None, language: str = ""):
    """Normalized tree for `node`, or None when the node is only punctuation.

    `omit`, when given, is a predicate over descendant nodes. A descendant it
    accepts normalizes to nothing, as a comment does. The root is always kept.
    """

    global _DATA, _LANGUAGE
    _DATA = data
    _LANGUAGE = language
    return _normalize(node, omit=omit)


def _text(node) -> str:
    return node_text(_DATA, node)


_PENDING = object()


def _is_literal(node) -> bool:
    if node.type not in _LITERALS:
        return False
    if node.type in {"string", "interpolated_string_expression"} and any(
        child.type in _INTERPOLATIONS for child in node.children
    ):
        return False
    return True


def _named_before_args(node):
    """The callee's parts, and the argument list and initializer that follow.
    A comment among them, as in `foo /* c */ (x)`, is no part."""

    named = [child for child in node.named_children if child.type not in _SKIP]
    for index, child in enumerate(named):
        if child.type in _CALL_TAILS:
            return named[:index], [item for item in named[index:] if item.type in _CALL_TAILS]
    return named, []


def _without_type_args(nodes):
    type_args = [child for child in nodes if child.type in _TYPE_ARGS]
    rest = [child for child in nodes if child.type not in _TYPE_ARGS]
    return rest, type_args


def _callee_leaf(node):
    if node.type in _IDENTIFIERS:
        return [K("symbol"), _text(node)]
    return _PENDING


def _named_leaf(node, head: bool):
    if node.type in _IDENTIFIERS:
        if head:
            return [K("symbol"), _text(node)]
        return K("symbol")
    if _is_literal(node):
        return K("literal")
    return _PENDING


def _ps_leaf(node, head: bool):
    """PowerShell-specific leaves: operators, command/member names, variables, constants."""

    if node.type in _SKIP or node.type == "command_argument_sep":
        return None
    if node.type == "comparison_operator":
        return [K("symbol"), _text(node).strip().lower()]
    if node.type == "assignement_operator":
        return [K("symbol"), _text(node).strip()]
    if node.type == "command_name":
        return [K("symbol"), _text(node).strip().lower()]
    if node.type == "member_name":
        return [K("symbol"), _text(node).strip().lower()]
    if node.type == "function_name":
        return K("symbol")
    if node.type == "variable":
        low = _text(node).strip().lower()
        if low in _PS_CONSTANTS:
            return [K("symbol"), low]
        return K("symbol")
    if node.type == "string_literal":
        if any(
            child.type == "expandable_string_literal" and child.named_children
            for child in node.children
        ):
            return _PENDING
        return K("literal")
    if node.type in {"verbatim_string_characters", "verbatim_here_string_characters", "expandable_here_string_literal"}:
        return K("literal")
    if not node.is_named:
        low = _text(node).strip().lower()
        if low in _OPERATORS or low in _PS_OPERATOR_TOKENS or node.type in _OPERATORS:
            return [K("symbol"), low]
        return None
    if node.type == "simple_name":
        return [K("symbol"), _text(node).strip().lower()] if head else K("symbol")
    return _named_leaf(node, head)


def _try_leaf(node, mode: str, head: bool):
    if _LANGUAGE == "powershell":
        if mode == "callee":
            return _callee_leaf(node)
        return _ps_leaf(node, head)
    if mode == "callee":
        return _callee_leaf(node)
    if mode == "path":
        return _PENDING
    if node.type in _SKIP:
        return None
    if node.type in _OPERATORS:
        return [K("symbol"), node.type]
    if not node.is_named:
        return None
    return _named_leaf(node, head)


def _call_jobs(node):
    incoming, args = _named_before_args(node)
    rest, type_args = _without_type_args(incoming)
    jobs = []
    if rest:
        *receivers, callee = rest
        jobs.extend((child, "norm", False) for child in receivers)
        jobs.append((callee, "callee", False))
    jobs.extend((child, "norm", False) for child in type_args)
    jobs.extend((child, "norm", False) for child in args)
    return jobs


def _attr_jobs(node, head: bool):
    named = [child for child in node.named_children if child.type not in _SKIP]
    if not named:
        return []
    *objects, name = named
    jobs = [(obj, "norm", False) for obj in objects]
    if name.type in _IDENTIFIERS:
        return jobs
    if head:
        jobs.append((name, "callee", False))
    else:
        jobs.append((name, "norm", False))
    return jobs


def _path_jobs(node):
    jobs = []
    for child in node.named_children:
        if child.type in _SKIP or child.type in _IDENTIFIERS:
            continue
        if child.type in _SCOPED:
            jobs.append((child, "path", False))
        else:
            jobs.append((child, "norm", False))
    return jobs


def _callee_jobs(node):
    if node.type in _ATTRIBUTES:
        return _attr_jobs(node, True)
    if node.type in _SCOPED:
        return _path_jobs(node)
    return [(node, "norm", True)]


def _jobs(node, mode: str, head: bool):
    if _LANGUAGE == "powershell":
        if node.type in _PS_WRAPPERS and len(node.children) == 1:
            return [(node.children[0], "norm", head)]
        if node.type == "parenthesized_expression" and len(node.named_children) == 1:
            return [(node.named_children[0], "norm", head)]
        return [(child, "norm", False) for child in node.children]
    if mode == "callee":
        return _callee_jobs(node)
    if mode == "path":
        return _path_jobs(node)
    if node.type == "parenthesized_expression" and len(node.named_children) == 1:
        return [(node.named_children[0], "norm", head)]
    if node.type in _CALLS:
        return _call_jobs(node)
    if node.type in _ATTRIBUTES:
        return _attr_jobs(node, head)
    return [(child, "norm", False) for child in node.children]


def _name_value(name, head: bool, cache):
    """Keep a member's spelling when it is the thing being called."""

    if name.type in _IDENTIFIERS:
        if head:
            return [K("symbol"), _text(name)]
        return K("symbol")
    if head:
        return cache[(id(name), "callee", False)]
    return cache[(id(name), "norm", False)]


def _assemble_call(node, cache):
    incoming, args = _named_before_args(node)
    rest, type_args = _without_type_args(incoming)
    out = [K(node.type)]
    if rest:
        *receivers, callee = rest
        for child in receivers:
            norm = cache[(id(child), "norm", False)]
            if norm is not None:
                out.append(norm)
        out.append(cache[(id(callee), "callee", False)])
    for child in [*type_args, *args]:
        norm = cache[(id(child), "norm", False)]
        if norm is not None:
            out.append(norm)
    return out


def _assemble_attr(node, head: bool, cache):
    named = [child for child in node.named_children if child.type not in _SKIP]
    if not named:
        return [K(node.type)]
    *objects, name = named
    parts = [K(node.type)]
    for obj in objects:
        norm = cache[(id(obj), "norm", False)]
        if norm is not None:
            parts.append(norm)
    nested = _name_value(name, head, cache)
    if nested is not None:
        parts.append(nested)
    return parts


def _assemble_path(node, cache):
    """A callee path keeps each name in the path. Type arguments stay structural."""

    parts = [K(node.type)]
    for child in node.named_children:
        if child.type in _SKIP:
            continue
        if child.type in _IDENTIFIERS:
            parts.append([K("symbol"), _text(child)])
        elif child.type in _SCOPED:
            parts.append(cache[(id(child), "path", False)])
        else:
            norm = cache[(id(child), "norm", False)]
            if norm is not None:
                parts.append(norm)
    return parts


def _callee_value(node, cache):
    if node.type in _ATTRIBUTES:
        return _assemble_attr(node, True, cache)
    if node.type in _SCOPED:
        return _assemble_path(node, cache)
    return cache[(id(node), "norm", True)]


def _assemble_children(node, cache):
    children = []
    for child in node.children:
        norm = cache[(id(child), "norm", False)]
        if norm is not None:
            children.append(norm)
    return [K(node.type), *children]


def _assemble(node, mode: str, head: bool, cache):
    if _LANGUAGE == "powershell":
        if node.type in _PS_WRAPPERS and len(node.children) == 1:
            return cache[(id(node.children[0]), "norm", head)]
        if node.type == "parenthesized_expression" and len(node.named_children) == 1:
            return cache[(id(node.named_children[0]), "norm", head)]
        return _assemble_children(node, cache)
    if mode == "callee":
        return _callee_value(node, cache)
    if mode == "path":
        return _assemble_path(node, cache)
    if node.type == "parenthesized_expression" and len(node.named_children) == 1:
        child = node.named_children[0]
        return cache[(id(child), "norm", head)]
    if node.type in _CALLS:
        return _assemble_call(node, cache)
    if node.type in _ATTRIBUTES:
        return _assemble_attr(node, head, cache)
    return _assemble_children(node, cache)


def _omitted_or_leaf(current, mode: str, head: bool, root, omit):
    if omit is not None and current.id != root.id and omit(current):
        return None
    return _try_leaf(current, mode, head)


def _normalize(node, head: bool = False, omit=None):
    # Post-order. A 1,200-deep expression must not raise RecursionError.
    cache = {}
    stack = [(node, "norm", head, False)]
    while stack:
        current, mode, is_head, expanded = stack.pop()
        key = (id(current), mode, is_head)
        if not expanded:
            if key in cache:
                continue
            leaf = _omitted_or_leaf(current, mode, is_head, node, omit)
            if leaf is not _PENDING:
                cache[key] = leaf
                continue
            stack.append((current, mode, is_head, True))
            for child, child_mode, child_head in reversed(_jobs(current, mode, is_head)):
                stack.append((child, child_mode, child_head, False))
            continue
        cache[key] = _assemble(current, mode, is_head, cache)
    return cache[(id(node), "norm", head)]
