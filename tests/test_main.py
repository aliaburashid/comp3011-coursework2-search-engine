"""Tests for :mod:`main` — CLI orchestration with mocked crawl and temp index path."""

# allows newer type hint styles to work on older Python versions
# Docs: https://peps.python.org/pep-0563/
from __future__ import annotations

# pytest is the test framework; fixtures and monkeypatch come from it
# Docs: https://docs.pytest.org/en/stable/
import pytest

# import the main module so we can call its functions and patch its internals
import main as main_mod


# autouse=True means this fixture runs automatically before and after every test in this file
# it resets the in-memory index so tests don't affect each other
# Docs: https://docs.pytest.org/en/stable/how-to/fixtures.html
@pytest.fixture(autouse=True)
def reset_loaded_index() -> None:
    main_mod._loaded_index = None
    yield
    main_mod._loaded_index = None


def test_build_writes_index_json(tmp_path, monkeypatch) -> None:
    # redirect the index file to a temporary folder so we don't write to the real data/ folder
    # monkeypatch.setattr replaces an attribute on a module for the duration of the test
    # Docs: https://docs.pytest.org/en/stable/how-to/monkeypatch.html
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    # replace the real crawler with a fake one that returns one page immediately
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex.test/doc", "hello world hello")],
    )
    # running build should succeed (return code 0)
    assert main_mod.main(["build"]) == 0
    path = tmp_path / "index.json"
    # the index file should have been created
    assert path.is_file()
    # load the file back and check the postings are correct
    restored = main_mod._load_json_index(path)
    posting = restored.get_postings_for_term("hello")["http://ex.test/doc"]
    # "hello" appears twice in "hello world hello"
    assert posting.frequency == 2


def test_load_missing_file_exits_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "missing.json")
    # loading when there is no file should fail with a non-zero return code
    assert main_mod.main(["load"]) == 1


def test_load_then_print_same_process_uses_memory_not_disk(tmp_path, monkeypatch, capsys) -> None:
    """After ``load``, ``print`` must use ``_loaded_index`` and not call ``_load_json_index`` again."""
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "alpha beta gamma")],
    )
    # build and save the index first
    assert main_mod.main(["build"]) == 0
    main_mod._loaded_index = None
    # load it into memory
    assert main_mod.main(["load"]) == 0
    capsys.readouterr()

    # replace _load_json_index with a function that crashes if called
    # this proves that print uses the in-memory index instead of reading the file again
    def boom_load(_path: object) -> None:
        raise AssertionError("print should reuse in-memory index after load, not reload JSON")

    monkeypatch.setattr(main_mod, "_load_json_index", boom_load)
    # print should work using the in-memory index without touching disk
    assert main_mod.main(["print", "gamma"]) == 0
    out = capsys.readouterr().out
    assert "gamma" in out
    assert "http://ex/" in out

    # find should also work using the in-memory index
    assert main_mod.main(["find", "alpha", "beta"]) == 0
    find_out = capsys.readouterr().out.strip().splitlines()
    assert len(find_out) == 1
    assert find_out[0].endswith(" http://ex/")


def test_load_reads_existing_file(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://x/", "one two")],
    )
    assert main_mod.main(["build"]) == 0
    main_mod._loaded_index = None
    # load should succeed and print a confirmation message
    assert main_mod.main(["load"]) == 0
    captured = capsys.readouterr().out
    assert "Loaded index" in captured
    # the in-memory index should now be set
    assert main_mod._loaded_index is not None


def test_print_autoloads_after_new_process(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "alpha beta gamma")],
    )
    assert main_mod.main(["build"]) == 0
    # clear the in-memory index to simulate a fresh process
    main_mod._loaded_index = None
    # print should auto-load from disk when no index is in memory
    assert main_mod.main(["print", "gamma"]) == 0
    out = capsys.readouterr().out
    assert "gamma" in out
    assert "http://ex/" in out


def test_print_no_index_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "nope.json")
    # print should fail if there is no index file and no in-memory index
    assert main_mod.main(["print", "word"]) == 1


def test_find_no_index_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "nope.json")
    # find should also fail if there is no index available
    assert main_mod.main(["find", "any", "terms"]) == 1


def test_print_uses_in_memory_index_after_build(tmp_path, monkeypatch, capsys) -> None:
    """After build, print should use _loaded_index without reloading JSON from disk."""
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")

    # if _load_json_index is called after build, something is wrong
    def boom_load(_path: object) -> None:
        raise AssertionError("should use in-memory index, not disk")

    monkeypatch.setattr(main_mod, "_load_json_index", boom_load)
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "hello there")],
    )
    assert main_mod.main(["build"]) == 0
    # print should use the index kept in memory by build, not reload from disk
    assert main_mod.main(["print", "hello"]) == 0
    assert "hello" in capsys.readouterr().out


def test_print_unknown_word_message(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "only these tokens")],
    )
    main_mod.main(["build"])
    main_mod._loaded_index = None
    capsys.readouterr()
    assert main_mod.main(["print", "ghostword"]) == 0
    out = capsys.readouterr().out
    # a word that was never indexed should produce a "No postings" message
    assert "No postings for 'ghostword'" in out


def test_find_no_terms_message(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://x/", "a b")],
    )
    main_mod.main(["build"])
    main_mod._loaded_index = None
    # running find with no words should print a helpful message, not crash
    assert main_mod.main(["find"]) == 0
    assert "No query terms" in capsys.readouterr().out


def test_find_matches_and_intersection(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [
            ("http://a/", "alpha beta"),
            ("http://b/", "beta only"),
        ],
    )
    main_mod.main(["build"])
    main_mod._loaded_index = None
    capsys.readouterr()
    assert main_mod.main(["find", "alpha", "beta"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    # only page a has both "alpha" and "beta" so there should be one result
    assert len(out) == 1
    assert out[0].endswith(" http://a/")
    # the score should be a decimal number with 4 decimal places
    score_text = out[0].split(" ", 1)[0]
    assert "." in score_text
    assert len(score_text.split(".", 1)[1]) == 4


def test_find_no_matching_pages_message(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "alpha beta")],
    )
    main_mod.main(["build"])
    main_mod._loaded_index = None
    capsys.readouterr()
    assert main_mod.main(["find", "alpha", "nope"]) == 0
    # "nope" is not in the index so there should be no matching pages
    assert "No matching pages." in capsys.readouterr().out


def test_build_stdout_reports_pages_and_unique_terms(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [
            ("http://p1/", "hello world hello"),
            ("http://p2/", "world only"),
        ],
    )
    assert main_mod.main(["build"]) == 0
    out = capsys.readouterr().out
    # the build output should mention how many pages were indexed
    assert "2 pages" in out
    assert "unique terms" in out
    # hello, world, only -> 3 distinct tokens across corpus
    assert "3 unique terms" in out