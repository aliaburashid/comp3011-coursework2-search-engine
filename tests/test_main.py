"""Tests for :mod:`main` — CLI orchestration with mocked crawl and temp index path."""

from __future__ import annotations

import pytest

import main as main_mod


@pytest.fixture(autouse=True)
def reset_loaded_index() -> None:
    main_mod._loaded_index = None
    yield
    main_mod._loaded_index = None


def test_build_writes_index_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex.test/doc", "hello world hello")],
    )
    assert main_mod.main(["build"]) == 0
    path = tmp_path / "index.json"
    assert path.is_file()
    restored = main_mod._load_json_index(path)
    posting = restored.get_postings_for_term("hello")["http://ex.test/doc"]
    assert posting.frequency == 2


def test_load_missing_file_exits_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "missing.json")
    assert main_mod.main(["load"]) == 1


def test_load_reads_existing_file(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://x/", "one two")],
    )
    assert main_mod.main(["build"]) == 0
    main_mod._loaded_index = None
    assert main_mod.main(["load"]) == 0
    captured = capsys.readouterr().out
    assert "Loaded index" in captured
    assert main_mod._loaded_index is not None


def test_print_autoloads_after_new_process(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "alpha beta gamma")],
    )
    assert main_mod.main(["build"]) == 0
    main_mod._loaded_index = None
    assert main_mod.main(["print", "gamma"]) == 0
    out = capsys.readouterr().out
    assert "gamma" in out
    assert "http://ex/" in out


def test_print_no_index_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "nope.json")
    assert main_mod.main(["print", "word"]) == 1


def test_find_no_index_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "nope.json")
    assert main_mod.main(["find", "any", "terms"]) == 1


def test_print_uses_in_memory_index_after_build(tmp_path, monkeypatch, capsys) -> None:
    """After build, print should use _loaded_index without reloading JSON from disk."""
    monkeypatch.setattr(main_mod, "INDEX_FILE", tmp_path / "index.json")

    def boom_load(_path: object) -> None:
        raise AssertionError("should use in-memory index, not disk")

    monkeypatch.setattr(main_mod, "_load_json_index", boom_load)
    monkeypatch.setattr(
        main_mod,
        "crawl_to_indexer_payload",
        lambda **kwargs: [("http://ex/", "hello there")],
    )
    assert main_mod.main(["build"]) == 0
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
    assert out == ["http://a/"]


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
    assert "2 pages" in out
    assert "unique terms" in out
    # hello, world, only -> 3 distinct tokens across corpus
    assert "3 unique terms" in out
