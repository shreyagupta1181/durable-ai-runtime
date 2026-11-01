from pydantic import BaseModel, Field


class CalculatorInput(BaseModel):
    expression: str = Field(
        min_length=1,
        max_length=200,
        description="A mathematical expression to evaluate.",
    )


import ast
import math
import operator


# Only these arithmetic operations are permitted.
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def evaluate_node(node):
    """Evaluate only explicitly allowed arithmetic AST nodes."""

    if isinstance(node, ast.Constant):
        if type(node.value) not in (int, float):
            raise ValueError("Only numeric values are allowed.")

        return node.value

    if isinstance(node, ast.BinOp):
        operation = OPERATORS.get(type(node.op))

        if operation is None:
            raise ValueError("Unsupported arithmetic operation.")

        left = evaluate_node(node.left)
        right = evaluate_node(node.right)

        # Prevent excessively large exponent calculations.
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("Exponent is too large.")

        result = operation(left, right)

        if isinstance(result, complex):
            raise ValueError("Complex results are not supported.")

        if not math.isfinite(result):
            raise ValueError("Result must be finite.")

        if abs(result) > 1e100:
            raise ValueError("Result is too large.")

        return result

    if isinstance(node, ast.UnaryOp):
        operation = UNARY_OPERATORS.get(type(node.op))

        if operation is None:
            raise ValueError("Unsupported unary operation.")

        return operation(evaluate_node(node.operand))

    raise ValueError("Invalid expression.")


def calculate(expression: str):
    """Safely evaluate a basic mathematical expression."""

    if not expression or len(expression) > 200:
        raise ValueError("Invalid expression length.")

    try:
        tree = ast.parse(expression, mode="eval")

        if sum(1 for _ in ast.walk(tree)) > 50:
            raise ValueError("Expression is too complex.")

        result = evaluate_node(tree.body)

        if not math.isfinite(result):
            raise ValueError("Result must be finite.")

        return result

    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"Could not evaluate expression: {exc}") from exc
