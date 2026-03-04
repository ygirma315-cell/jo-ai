from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation
import ast


class CalculatorError(Exception):
    """Raised when user input is invalid or unsafe for the calculator."""


class CalculatorService:
    MAX_EXPRESSION_LENGTH = 120

    def evaluate(self, expression: str) -> str:
        cleaned = expression.strip()
        if not cleaned:
            raise CalculatorError("Please enter an expression. Example: 5 * (3 + 2)")
        if len(cleaned) > self.MAX_EXPRESSION_LENGTH:
            raise CalculatorError("That expression is too long. Please keep it under 120 characters.")

        try:
            parsed = ast.parse(cleaned, mode="eval")
        except SyntaxError as exc:
            raise CalculatorError("I could not parse that expression. Example: 12 / (2 + 4)") from exc

        try:
            value = self._eval_node(parsed.body)
        except DivisionByZero as exc:
            raise CalculatorError("Division by zero is not allowed.") from exc
        except (InvalidOperation, OverflowError) as exc:
            raise CalculatorError("That calculation is not valid.") from exc
        except CalculatorError:
            raise

        return self._format_decimal(value)

    def _eval_node(self, node: ast.AST) -> Decimal:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return Decimal(str(node.value))

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._eval_node(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value

        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise DivisionByZero("Division by zero")
            return left / right

        raise CalculatorError(
            "Only +, -, *, /, parentheses, and decimals are supported. "
            "Example: 7.5 * (4 - 1)"
        )

    def _format_decimal(self, value: Decimal) -> str:
        if value == value.to_integral():
            return str(value.quantize(Decimal("1")))

        text = format(value.normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
