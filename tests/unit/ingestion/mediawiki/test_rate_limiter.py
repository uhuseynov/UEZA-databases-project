import pytest

from src.ingestion.mediawiki.rate_limiter import RateLimiter


def test_first_request_does_not_sleep(
    monkeypatch,
) -> None:
    sleeps: list[float] = []

    monkeypatch.setattr(
        "src.ingestion.mediawiki.rate_limiter.time.monotonic",
        lambda: 10.0,
    )

    monkeypatch.setattr(
        "src.ingestion.mediawiki.rate_limiter.time.sleep",
        sleeps.append,
    )

    limiter = RateLimiter(2.0)

    limiter.wait()

    assert sleeps == []


def test_waits_between_requests(
    monkeypatch,
) -> None:
    times = iter(
        [
            10.0,
            10.0,
            10.2,
            10.5,
        ]
    )

    sleeps: list[float] = []

    monkeypatch.setattr(
        "src.ingestion.mediawiki.rate_limiter.time.monotonic",
        lambda: next(times),
    )

    monkeypatch.setattr(
        "src.ingestion.mediawiki.rate_limiter.time.sleep",
        sleeps.append,
    )

    limiter = RateLimiter(2.0)

    limiter.wait()
    limiter.wait()

    assert sleeps == pytest.approx([0.3])
