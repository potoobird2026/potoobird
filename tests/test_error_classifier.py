"""
错误分类器测试
"""

import pytest

from src.errors.classifier import ErrorClassifier, ErrorType


@pytest.fixture
def classifier():
    return ErrorClassifier()


class TestHTTPStatusClassification:
    def test_401_auth(self, classifier):
        result = classifier.classify(Exception("401 Unauthorized"))
        assert result.error_type == ErrorType.AUTH
        assert result.retryable is False

    def test_429_rate_limit(self, classifier):
        result = classifier.classify(Exception("429 Too Many Requests"))
        assert result.error_type == ErrorType.RATE_LIMIT
        assert result.retryable is True

    def test_500_server(self, classifier):
        result = classifier.classify(Exception("500 Internal Server Error"))
        assert result.error_type == ErrorType.SERVER
        assert result.retryable is True

    def test_503_server(self, classifier):
        result = classifier.classify(Exception("503 Service Unavailable"))
        assert result.error_type == ErrorType.SERVER


class TestPatternClassification:
    def test_context_overflow(self, classifier):
        result = classifier.classify(Exception("context length exceeded maximum"))
        assert result.error_type == ErrorType.CONTEXT_OVERFLOW
        assert result.recovery_action == "compress_and_retry"

    def test_timeout(self, classifier):
        result = classifier.classify(Exception("request timed out"))
        assert result.error_type == ErrorType.TIMEOUT
        assert result.retryable is True

    def test_connection_refused(self, classifier):
        result = classifier.classify(Exception("Connection refused"))
        assert result.error_type == ErrorType.CONNECTION

    def test_auth_pattern(self, classifier):
        result = classifier.classify(Exception("Invalid API key provided"))
        assert result.error_type == ErrorType.AUTH

    def test_unknown(self, classifier):
        result = classifier.classify(Exception("something weird happened"))
        assert result.error_type == ErrorType.UNKNOWN
        assert result.retryable is False
