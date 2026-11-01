import pytest

from app.tools import create_default_registry


@pytest.fixture
def registry():
    return create_default_registry()


def test_calculator_basic_arithmetic(registry):
    result = registry.execute(
        "calculator",
        {"expression": "25 * (10 + 5)"},
    )

    assert result == 375


def test_calculator_division(registry):
    result = registry.execute(
        "calculator",
        {"expression": "100 / 4"},
    )

    assert result == 25


def test_calculator_rejects_division_by_zero(registry):
    with pytest.raises(ValueError):
        registry.execute(
            "calculator",
            {"expression": "10 / 0"},
        )


def test_calculator_rejects_python_code(registry):
    with pytest.raises(ValueError):
        registry.execute(
            "calculator",
            {"expression": "__import__('os').system('whoami')"},
        )


def test_calculator_rejects_unknown_operations(registry):
    with pytest.raises(ValueError):
        registry.execute(
            "calculator",
            {"expression": "2 ** 100"},
        )