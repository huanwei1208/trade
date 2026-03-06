# trade_py: Python bindings for the C++ quantitative trading system
# All computation is done in C++; Python is used for visualization and Jupyter interaction.

__version__ = "0.1.0"

try:
    import trade_py as _cpp
    HAS_CPP = True
except ImportError:
    _cpp = None
    HAS_CPP = False


def check_cpp():
    """Check if C++ bindings are available."""
    if not HAS_CPP:
        raise RuntimeError(
            "C++ bindings not available. Build with:\n"
            "  cmake --preset default -DBUILD_PYTHON_BINDINGS=ON\n"
            "  cmake --build build/default --target trade_py"
        )
    return _cpp
