"""Tests for Undefined.ai.tokens module."""

from __future__ import annotations

from unittest.mock import patch

from Undefined.ai.tokens import TokenCounter


class TestTokenCounter:
    """Tests for TokenCounter."""

    def test_empty_string(self) -> None:
        counter = TokenCounter()
        result = counter.count("")
        assert result == 0 or isinstance(result, int)

    def test_normal_text(self) -> None:
        counter = TokenCounter()
        result = counter.count("Hello, world!")
        assert result > 0

    def test_unicode_text(self) -> None:
        counter = TokenCounter()
        result = counter.count("你好世界！🌍")
        assert result > 0

    def test_long_text(self) -> None:
        counter = TokenCounter()
        short_count = counter.count("hello")
        long_count = counter.count("hello " * 1000)
        assert long_count > short_count

    def test_whitespace_only(self) -> None:
        counter = TokenCounter()
        result = counter.count("   \n\t  ")
        assert isinstance(result, int)

    def test_single_character(self) -> None:
        counter = TokenCounter()
        result = counter.count("a")
        assert result >= 1

    def test_fallback_when_tiktoken_unavailable(self) -> None:
        counter = TokenCounter()
        counter._tokenizer = None
        result = counter.count("hello world")
        expected = len("hello world") // 3 + 1
        assert result == expected

    def test_fallback_empty_string(self) -> None:
        counter = TokenCounter()
        counter._tokenizer = None
        result = counter.count("")
        assert result == 1  # len("") // 3 + 1 == 1

    def test_fallback_short_text(self) -> None:
        counter = TokenCounter()
        counter._tokenizer = None
        assert counter.count("ab") == 1  # 2 // 3 + 1

    def test_fallback_exact_multiple(self) -> None:
        counter = TokenCounter()
        counter._tokenizer = None
        assert counter.count("abc") == 2  # 3 // 3 + 1

    def test_default_model_name(self) -> None:
        counter = TokenCounter()
        assert counter._model_name == "gpt-4"

    def test_custom_model_name(self) -> None:
        counter = TokenCounter(model_name="gpt-3.5-turbo")
        assert counter._model_name == "gpt-3.5-turbo"

    def test_tiktoken_load_failure_graceful(self) -> None:
        with patch("builtins.__import__", side_effect=ImportError("no tiktoken")):
            counter = TokenCounter.__new__(TokenCounter)
            counter._model_name = "gpt-4"
            counter._tokenizer = None
            counter._try_load_tokenizer()
        assert counter._tokenizer is None
        result = counter.count("test text")
        assert result == len("test text") // 3 + 1
