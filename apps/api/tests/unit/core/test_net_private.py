"""With private endpoints disallowed, a public-looking name that resolves inside the
network is refused too, not only a private host string."""

from __future__ import annotations

import pytest

from dataquality.core.net import resolves_safely

pytestmark = pytest.mark.asyncio


async def test_a_name_resolving_to_loopback_is_refused_when_private_is_off() -> None:
    assert await resolves_safely("http://localhost:11434/v1", allow_private=True) is True
    assert await resolves_safely("http://localhost:11434/v1", allow_private=False) is False


async def test_metadata_is_refused_either_way() -> None:
    assert await resolves_safely("http://169.254.169.254/latest", allow_private=True) is False
