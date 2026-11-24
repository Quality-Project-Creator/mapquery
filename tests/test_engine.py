"""Tests for the concurrent engine."""

import time

from mapquery.engine import run_many
from mapquery.models import Channel, ProviderError, ProviderResult, ProviderStatus


def _slow(value: str, delay: float) -> str:
    """Sleep for a while, then return a value."""
    time.sleep(delay)
    return value


def test_results_keep_the_input_order() -> None:
    """The result order follows the input order, not the finish order."""
    tasks = {
        "baidu": lambda: _slow("baidu", 0.05),
        "amap": lambda: _slow("amap", 0.01),
        "tencent": lambda: _slow("tencent", 0.03),
    }
    results = run_many(tasks, jobs=3)

    assert list(results.keys()) == ["baidu", "amap", "tencent"]
    assert results["baidu"].data == "baidu"
    assert results["amap"].data == "amap"
    assert results["tencent"].data == "tencent"


def test_one_failure_does_not_break_the_others() -> None:
    """A broken task only breaks its own result."""
    def broken() -> str:
        raise ValueError("this task is broken")

    tasks = {"baidu": broken, "amap": lambda: "amap", "tencent": lambda: "tencent"}
    results = run_many(tasks, jobs=3)

    assert results["baidu"].status == ProviderStatus.ERROR
    assert results["baidu"].error is not None
    assert "broken" in results["baidu"].error
    assert results["amap"].status == ProviderStatus.OK
    assert results["amap"].data == "amap"
    assert results["tencent"].status == ProviderStatus.OK


def test_a_timeout_becomes_the_timeout_status() -> None:
    """A timeout error is reported as a timeout, not as a plain error."""
    def too_slow() -> str:
        raise TimeoutError("the request timed out")

    results = run_many({"baidu": too_slow}, jobs=1)

    assert results["baidu"].status == ProviderStatus.TIMEOUT
    assert results["baidu"].data is None


def test_every_result_has_a_time_and_a_count() -> None:
    """Each result carries the elapsed time and the attempt count."""
    results = run_many({"baidu": lambda: "ok"}, jobs=1)

    result = results["baidu"]
    assert result.status == ProviderStatus.OK
    assert result.attempts == 1
    assert result.elapsed_ms >= 0


def test_an_empty_task_list_gives_an_empty_result() -> None:
    """Nothing to do means nothing to return."""
    assert run_many({}, jobs=4) == {}


def test_a_failure_keeps_the_channel_of_the_provider() -> None:
    """A provider that fails on its official channel says so."""
    def broken() -> str:
        raise ProviderError("the provider rate limit was hit", ProviderStatus.RATE_LIMITED)

    results = run_many(
        {"baidu": broken},
        jobs=1,
        channels={"baidu": Channel.OFFICIAL},
    )

    assert results["baidu"].status == ProviderStatus.RATE_LIMITED
    assert results["baidu"].channel == Channel.OFFICIAL


def test_an_answer_keeps_the_channel_of_the_provider() -> None:
    """The channel of the provider is the one that was used."""
    results = run_many(
        {"baidu": lambda: "ok"},
        jobs=1,
        channels={"baidu": Channel.OFFICIAL},
    )

    assert results["baidu"].channel == Channel.OFFICIAL
    assert results["baidu"].status == ProviderStatus.OK


def test_the_channel_is_direct_when_it_is_not_given() -> None:
    """A provider without a channel uses the direct one."""
    results = run_many({"baidu": lambda: "ok"}, jobs=1)

    assert results["baidu"].channel == Channel.DIRECT


def test_a_result_of_the_task_keeps_the_channel_of_the_provider() -> None:
    """A task that gives its own result still gets the channel of the map.

    The result of a task carries no channel of its own, so it must not
    keep the default one when the provider really used the official
    channel.
    """
    def task() -> ProviderResult:
        """Return a result of its own."""
        return ProviderResult(provider="amap", status=ProviderStatus.OK, data="ok")

    results = run_many(
        {"amap": task},
        jobs=1,
        channels={"amap": Channel.OFFICIAL},
    )

    assert results["amap"].channel == Channel.OFFICIAL
    assert results["amap"].status == ProviderStatus.OK
    assert results["amap"].data == "ok"


def test_a_result_of_the_task_keeps_the_direct_channel() -> None:
    """A result of a task on the direct channel stays on it."""
    def task() -> ProviderResult:
        """Return a result of its own."""
        return ProviderResult(provider="amap", status=ProviderStatus.OK, data="ok")

    results = run_many({"amap": task}, jobs=1, channels={"amap": Channel.DIRECT})

    assert results["amap"].channel == Channel.DIRECT


def test_a_provider_that_made_no_request_reports_zero_attempts() -> None:
    """A result that holds a failure, not an answer, made no request."""
    from mapquery.engine import run_many
    from mapquery.models import Channel, ProviderResult, ProviderStatus

    def task() -> ProviderResult:
        return ProviderResult(
            provider="amap",
            status=ProviderStatus.NOT_CONFIGURED,
            data=None,
            error="needs a key",
        )

    results = run_many({"amap": task}, jobs=2, channels={"amap": Channel.DIRECT})

    assert results["amap"].attempts == 0
    assert results["amap"].status == ProviderStatus.NOT_CONFIGURED
