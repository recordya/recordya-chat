import os
from src.llm.policies import ModelPolicy


def test_model_policy_agent_openai_defaults():
    """Test agent params for standard OpenAI models (no reasoning_effort)."""
    policy = ModelPolicy()
    params = policy.for_purpose(model="openai/gpt-4o", purpose="agent")
    assert params["max_tokens"] == 8000
    assert params["temperature"] == 0
    assert params["seed"] == 42
    assert "reasoning_effort" not in params  # Only for reasoning models


def test_model_policy_agent_reasoning_model():
    """Test agent params for reasoning models (o1, o3, gpt-5)."""
    policy = ModelPolicy()
    params = policy.for_purpose(model="openai/o1", purpose="agent")
    assert params["max_tokens"] == 8000
    assert params["reasoning_effort"] == "low"


def test_model_policy_summary_non_openai_defaults():
    os.environ["SUMMARY_TEMPERATURE"] = "0.7"
    policy = ModelPolicy()
    params = policy.for_purpose(model="google/gemini-1.5", purpose="summary")
    assert params["max_tokens"] == 4000
    assert params["temperature"] == 0.7
