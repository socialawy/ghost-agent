"""Shared fixtures for Ghost Agent tests."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def ghost_dir(tmp_path):
    """Create a temporary .ghost/ directory structure."""
    state_dir = tmp_path / ".ghost"
    state_dir.mkdir()
    (state_dir / "topics").mkdir()
    return state_dir


@pytest.fixture
def mock_config():
    """Minimal single-provider config for testing."""
    return {
        "provider": "openai",
        "api_key": "test-key-123",
        "base_url": "https://api.example.com/v1",
        "model": "test-model",
        "max_tokens": 1024,
        "temperature": 0.5,
        "min_interval": 0,
        "json_mode_supported": True,
    }


@pytest.fixture
def cascade_config():
    """Multi-provider cascade config for testing."""
    return {
        "providers": [
            {
                "provider": "openai",
                "api_key": "key-1",
                "base_url": "https://provider1.example.com/v1",
                "model": "model-1",
                "max_tokens": 1024,
                "temperature": 0.3,
                "min_interval": 0,
            },
            {
                "provider": "openai",
                "api_key": "key-2",
                "base_url": "https://provider2.example.com/v1",
                "model": "model-2",
                "max_tokens": 2048,
                "temperature": 0.3,
                "min_interval": 0,
            },
        ]
    }


@pytest.fixture
def sample_orient_result():
    """Canned Orient phase output."""
    return {
        "deltas": [
            {
                "type": "new_fact",
                "summary": "User has 107 registered projects",
                "confidence": "high",
                "relevant_topics": ["co-workspace"],
                "source_role": "user",
            }
        ],
        "topics_to_load": ["co-workspace"],
        "topics_to_create": [],
        "orient_summary": "User injected workspace metadata",
    }


@pytest.fixture
def sample_consolidate_result():
    """Canned Consolidate phase output."""
    return {
        "topic_updates": [
            {
                "topic": "co-workspace",
                "action": "update",
                "content": "## Registry\n107 registered projects\n- Active: 5\n- Idle: 50",
            }
        ],
        "index_graph": {
            "nodes": [
                {"id": "co-workspace", "label": "Co Workspace", "type": "project"}
            ],
            "edges": [],
        },
        "active_context": "Updated workspace registry info",
        "pending_observations": [],
        "verifications": [],
        "consolidate_log": "Updated co-workspace with registry data",
    }
