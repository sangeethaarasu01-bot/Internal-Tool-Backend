from app.llm.mock_fallback import should_use_offline_fallback


def test_should_fallback_on_gemini_503_high_demand() -> None:
    exc = RuntimeError(
        'Gemini API error 503: {"error": {"message": "high demand. Please try again later."}}'
    )
    assert should_use_offline_fallback(exc) is True
