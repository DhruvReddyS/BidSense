"""Session-wide test environment.

Two things belong here rather than in individual modules.

**The reviewer invitation code.** Several modules register a reviewer with the
literal code `development-reviewer`, while `.env.example` ships
`replace-with-a-private-invitation-code`. The suite therefore passed only if the
developer happened to have guessed that exact value, and otherwise failed with
`403 A valid reviewer invitation code is required` from a *fixture*, which reads
like a broken auth layer rather than a misconfigured environment. Forcing it
here makes the suite hermetic: it tests the code, not the contents of someone's
.env.

**The embedding-model probe.** A single place that answers "can we load BGE?",
so a test needing it skips with a reason instead of raising a 30-line
HuggingFace traceback. The probe is cached because it is slow to fail.
"""

from __future__ import annotations

import os

# Must be set before anything imports app.config, which snapshots the
# environment into a cached Settings object.
os.environ["REVIEWER_REGISTRATION_CODE"] = "development-reviewer"
os.environ.setdefault("AUTH_SECRET", "test-only-secret-0123456789abcdefghijkl")
# Fail fast when the weights are not already cached: without this, a denied
# huggingface.co turns every model probe into a long retry loop.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def embeddings_available() -> bool:
    return _embeddings_available()


def _embeddings_available() -> bool:
    """True when the BGE weights can actually be loaded."""
    try:
        from app.vector.embeddings import get_model

        get_model()
        return True
    except Exception:
        return False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "needs_embeddings: requires the BGE weights to be loadable locally",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip embedding-marked tests once, rather than failing each."""
    if not any(item.get_closest_marker("needs_embeddings") for item in items):
        return
    if _embeddings_available():
        return
    skip = pytest.mark.skip(
        reason="BGE weights unavailable (offline, or huggingface.co denied)"
    )
    for item in items:
        if item.get_closest_marker("needs_embeddings"):
            item.add_marker(skip)
