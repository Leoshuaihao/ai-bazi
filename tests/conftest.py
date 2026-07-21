"""pytest configuration for async tests."""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as an async test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )


@pytest.fixture(scope="session")
def anyio_backend():
    """Use asyncio backend for pytest-asyncio."""
    return "asyncio"


# Auto-detect async tests (no need for @pytest.mark.asyncio if using --asyncio-mode=auto)
def pytest_collection_modifyitems(config, items):
    """Add asyncio marker to all async test functions."""
    for item in items:
        if hasattr(item, 'obj') and hasattr(item.obj, '__code__'):
            if hasattr(item.obj.__code__, 'co_flags'):
                # CO_COROUTINE flag (0x100) indicates async function
                if item.obj.__code__.co_flags & 0x100:
                    item.add_marker(pytest.mark.asyncio)
