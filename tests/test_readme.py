"""Tests for the README and the docs.

The README is the contract of the tool. Every claim in it must be true,
so the words that carry a promise are checked here.

No test touches the network.
"""

import os
from typing import List

import pytest

# The root of the repository.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The README of the tool.
README = os.path.join(ROOT, "README.md")

# The plan of the version.
PLAN = os.path.join(ROOT, "docs", "PLAN.md")

# The notes of the traced data sources.
DATA_SOURCES = os.path.join(ROOT, "docs", "DATA_SOURCES.md")


def read(path: str) -> str:
    """Return the text of one file of the repository."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def layout_files(text: str) -> List[str]:
    """Return the names of the files of a tree that is drawn in the text."""
    names: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("├", "└", "│")):
            continue
        cleaned = stripped.lstrip("│├└─ ")
        name = cleaned.split("#")[0].strip()
        if name:
            names.append(name)
    return names


def every_file_of_the_repo() -> List[str]:
    """Return the name of every file of the repository."""
    names: List[str] = []
    for folder, _folders, files in os.walk(ROOT):
        if ".git" in folder or "__pycache__" in folder:
            continue
        for name in files:
            names.append(name)
    return names


def every_folder_of_the_repo() -> List[str]:
    """Return the name of every folder of the repository."""
    names: List[str] = []
    for folder, folders, _files in os.walk(ROOT):
        if ".git" in folder or "__pycache__" in folder:
            continue
        for name in folders:
            names.append(name)
    return names


def test_the_readme_says_that_the_name_matcher_works_inside_one_script() -> None:
    """The README does not promise a match between two scripts."""
    text = read(README)

    assert "are compared in a fair way" not in text
    assert "one script" in text


def test_the_readme_says_that_the_position_rule_carries_a_latin_query() -> None:
    """The README says that the position rule is what carries the match."""
    text = read(README)

    assert "25 metres apart" in text
    assert "the position based" in text
    assert "25 metre rule" in text


def test_the_readme_says_that_the_25_metre_rule_holds_for_any_two_places() -> None:
    """The 25 metre rule holds for any two places."""
    text = read(README)

    assert "no matter which provider" in text


def test_the_readme_says_that_a_cluster_is_a_chain() -> None:
    """The spread of a cluster can be bigger than the distance of the match."""
    text = read(README)

    assert "chain" in text
    assert "spread_max_m" in text


def test_the_readme_shows_that_a_cached_answer_is_marked() -> None:
    """The status line shows that an answer came from the cache."""
    text = read(README)

    assert "cached" in text


def test_the_readme_names_the_tools_folder() -> None:
    """The project layout holds the tools folder."""
    text = read(README)

    assert "tools/" in text
    assert "smoke.py" in text


def test_the_readme_does_not_ask_tencent_for_the_wrong_cycling_mode() -> None:
    """The cycling mode is called bicycling for Amap and for Tencent."""
    text = read(README)

    assert "`biking`" not in text
    assert "`bicycling`" in text


def test_the_readme_does_not_show_a_rate_limit_as_a_plain_error() -> None:
    """The example of the route command keeps the rate limit."""
    text = read(README)

    assert "tencent: rate_limited" in text


def test_the_layout_of_the_readme_only_names_files_that_exist() -> None:
    """Every file of the layout of the README is in the repository."""
    names = every_file_of_the_repo()

    folders = every_folder_of_the_repo()

    for name in layout_files(read(README)):
        if name.endswith("/"):
            relative = name.rstrip("/")
            if os.path.isdir(os.path.join(ROOT, relative)):
                continue
            assert relative.split("/")[-1] in folders, "{0} is not in the repository".format(name)
            continue
        assert name in names, "{0} is not in the repository".format(name)


def test_the_layout_of_the_plan_only_names_files_that_exist() -> None:
    """Every file of the layout of the plan is in the repository."""
    names = every_file_of_the_repo()

    folders = every_folder_of_the_repo()

    for name in layout_files(read(PLAN)):
        if name.endswith("/"):
            relative = name.rstrip("/")
            if os.path.isdir(os.path.join(ROOT, relative)):
                continue
            assert relative.split("/")[-1] in folders, "{0} is not in the repository".format(name)
            continue
        assert name in names, "{0} is not in the repository".format(name)


def test_the_data_sources_point_at_a_script_that_is_in_the_repository() -> None:
    """The notes of the trace point at scripts that are really there."""
    text = read(DATA_SOURCES)

    assert "tools/trace_sources.py" in text
    assert "tools/smoke.py" in text

    # Every script the notes name must exist in the repository.
    for name in ("trace_sources.py", "smoke.py"):
        assert os.path.isfile(os.path.join(ROOT, "tools", name))


@pytest.mark.parametrize("name", ["config.toml"])
def test_the_config_file_is_never_in_the_repository(name: str) -> None:
    """The file with the keys of the user is never in the repository."""
    assert name not in every_file_of_the_repo()


def test_the_exit_codes_of_the_readme_agree_with_the_matrix_rule() -> None:
    """The exit code table says the same thing as the matrix section.

    The matrix can stop with the code 1 when every provider answered and
    simply did not find the place, so the table must not say that the
    code 1 only means "every provider failed".
    """
    text = read(README)

    assert "| 1 | Every provider failed." not in text
    assert "no provider answered with data" in text.lower()
    assert "the matrix could not find the places" in text


def test_the_plan_says_the_same_thing_about_the_exit_codes() -> None:
    """The plan and the README use the same rule for the exit codes."""
    text = read(PLAN)

    assert "`1` = all providers failed" not in text
    assert "no provider answered with data" in text


def test_the_plan_does_not_promise_a_types_filter() -> None:
    """The plan does not advertise an option that the tool does not have."""
    text = read(PLAN)

    assert "[--types T]" not in text
    # The plan says why the filter is not part of this version.
    assert "types filter" in text


def test_the_readme_says_that_the_weather_is_always_amap() -> None:
    """The weather command is an Amap command, and the README says so."""
    text = read(README)

    assert "The weather is always Amap." in text


def test_the_trees_hold_the_conftest_of_the_tests() -> None:
    """The conftest of the tests is in both trees."""
    assert "conftest.py" in layout_files(read(README))
    assert "conftest.py" in layout_files(read(PLAN))


def test_the_chinese_readme_is_in_the_repository() -> None:
    """The Chinese readme exists and covers the same ground."""
    path = os.path.join(ROOT, "README.zh-CN.md")

    assert os.path.isfile(path)
    text = read(path)

    # The sections that carry the contract must be there.
    for heading in ("## 安装", "## 命令", "## 输出格式", "## 坐标系", "## 局限与实话"):
        assert heading in text, heading

    # It must point at the same scripts as the English one.
    assert "tools/smoke.py" in text
    assert "trace_sources.py" in text

    # The tools folder must be named in the layout.
    assert "tools/" in text


def test_the_chinese_readme_holds_no_full_key() -> None:
    """The Chinese readme must not hold a full front-end key."""
    from mapquery.providers.direct_keys import (
        AMAP_FRONTEND_KEY,
        BAIDU_FRONTEND_AK,
        TENCENT_FRONTEND_KEY,
    )

    text = read(os.path.join(ROOT, "README.zh-CN.md"))

    assert AMAP_FRONTEND_KEY not in text
    assert BAIDU_FRONTEND_AK not in text
    assert TENCENT_FRONTEND_KEY not in text
