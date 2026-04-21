import pytest
from unittest.mock import AsyncMock, MagicMock

from src.config import Config
from src.codex_executor import CodexExecutor
from src.runtime_config import RuntimeConfig


@pytest.fixture
def mock_config():
    cfg = MagicMock(spec=Config)
    cfg.codex_model = "codex-5.3"
    cfg.codex_max_turns = 5
    cfg.codex_working_dir = "/tmp"
    cfg.superpos_poll_interval = 1
    cfg.telegram_chat_id = "123"
    cfg.codex_max_parallel = 3
    cfg.openai_api_key = ""
    return cfg


@pytest.fixture
def mock_superpos():
    a = AsyncMock()
    a.update_progress = AsyncMock()
    a.poll_tasks = AsyncMock(return_value=[])
    a.claim_task = AsyncMock()
    a.complete_task = AsyncMock()
    a.fail_task = AsyncMock()
    a.heartbeat = AsyncMock()
    a.update_status = AsyncMock()
    return a


@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    gw.send_message = AsyncMock()
    gw.edit_message_text = AsyncMock()
    gw.delete_message = AsyncMock()
    gw.send_chat_action = AsyncMock()
    return gw


@pytest.fixture
def mock_runtime():
    return RuntimeConfig(model="gpt-5.4", effort="high")


@pytest.fixture
def executor(mock_config, mock_runtime, mock_superpos, mock_gateway):
    return CodexExecutor(mock_config, mock_runtime, mock_superpos, mock_gateway)


@pytest.fixture
def executor_with_persona(mock_config, mock_runtime, mock_superpos, mock_gateway):
    return CodexExecutor(mock_config, mock_runtime, mock_superpos, mock_gateway, persona="You are a helpful assistant.")
