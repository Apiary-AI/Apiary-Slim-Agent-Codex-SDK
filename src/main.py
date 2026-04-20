"""Entry point: runs all daemons via asyncio.gather()."""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import signal
import sys
from asyncio.subprocess import PIPE

from .apiary_client import ApiaryClient
from .apiary_poller import run_apiary_poller
from .codex_executor import CodexExecutor
from .config import Config
from .runtime_config import RuntimeConfig
from .telegram_bot import build_telegram_app, run_telegram_bot
from .telegram_gateway import TelegramGateway
from .worktree_manager import is_git_repo, prune_worktrees

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s  %(message)s"
_LOG_DIR = os.path.join(os.environ.get("HOME", "/tmp"), ".codex", "logs")

os.makedirs(_LOG_DIR, exist_ok=True)

# Console (stderr) — same as before
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, stream=sys.stderr)

# Persistent file — survives container restart via the /home/agent/.codex volume
_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(_LOG_DIR, "agent.log"),
    maxBytes=5 * 1024 * 1024,  # 5 MB per file
    backupCount=3,  # keep agent.log, agent.log.1, agent.log.2, agent.log.3
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
_file_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_file_handler)

log = logging.getLogger(__name__)


_AUTH_HELP_INVALID_KEY = """
\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557
\u2551         Codex authentication failed \u2014 cannot start          \u2551
\u2560\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2563
\u2551                                                              \u2551
\u2551  Option 1 \u2014 OAuth (codex login):                             \u2551
\u2551                                                              \u2551
\u2551    docker run -it \\                                         \u2551
\u2551      -v codex_auth:/home/agent/.codex \\                     \u2551
\u2551      --entrypoint codex slim-codex-agent login                \u2551
\u2551                                                              \u2551
\u2551    Follow the prompts to authenticate.                        \u2551
\u2551    Then restart the agent (keep the -v flag).                  \u2551
\u2551                                                              \u2551
\u2551  Option 2 \u2014 API key:                                         \u2551
\u2551                                                              \u2551
\u2551    Set OPENAI_API_KEY=sk-... in your .env file.               \u2551
\u2551                                                              \u2551
\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d
"""


def _auth_error_message(err: str) -> str | None:
    """Return the appropriate help text if err is a Codex auth failure, else None."""
    lower = err.lower()
    if "authentication" in lower or "invalid api key" in lower or "unauthorized" in lower or "invalid_api_key" in lower:
        return _AUTH_HELP_INVALID_KEY
    return None


async def _check_codex_auth() -> None:
    """Make a minimal Codex CLI call to verify credentials before starting."""
    log.info("Verifying Codex authentication...")
    try:
        env = {**os.environ}
        process = await asyncio.create_subprocess_exec(
            "codex", "exec", "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral", "--skip-git-repo-check",
            "hi",
            stdout=PIPE,
            stderr=PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=60
        )
        if process.returncode != 0:
            stderr_str = stderr.decode(errors="replace")
            msg = _auth_error_message(stderr_str)
            if msg:
                print(msg, file=sys.stderr)
                sys.exit(1)
            raise RuntimeError(f"Codex auth check failed (exit {process.returncode}): {stderr_str[:500]}")
        log.info("Codex authentication OK")
    except asyncio.TimeoutError:
        log.warning("Codex auth check timed out (60s) — proceeding anyway")
    except FileNotFoundError:
        log.critical("'codex' CLI not found on PATH. Install with: npm install -g @openai/codex")
        sys.exit(1)


async def main() -> None:
    config = Config.from_env()

    # Prune orphaned worktrees from prior runs
    if config.codex_worktree_isolation and is_git_repo(config.codex_working_dir):
        try:
            await prune_worktrees(config.codex_working_dir)
        except Exception:
            log.warning("Failed to prune worktrees on startup", exc_info=True)

    # Verify Codex auth before starting anything else
    await _check_codex_auth()

    # Apiary client (optional)
    apiary: ApiaryClient | None = None
    if config.apiary_enabled:
        apiary = ApiaryClient(config)
        log.info("Apiary integration enabled (%s)", config.apiary_base_url)
        try:
            await apiary.update_status("online")
            log.info("Agent status set to online")
        except Exception:
            log.warning("Failed to set agent status to online", exc_info=True)
    else:
        log.info("Apiary integration disabled (missing config)")

    # Telegram app + centralized gateway (optional)
    bot_app = None
    gateway = None
    if config.telegram_enabled:
        bot_app = build_telegram_app(config)
        bot = bot_app.bot
        gateway = TelegramGateway(bot)
    else:
        log.info("Telegram disabled (no TELEGRAM_BOT_TOKEN)")

    # Fetch persona at startup
    persona: str | None = None
    if apiary:
        try:
            persona = await apiary.get_persona_assembled()
            if persona:
                log.info("Persona loaded (version from assembled endpoint)")
            else:
                log.info("No persona configured for this agent")
        except Exception:
            log.warning("Could not fetch persona at startup", exc_info=True)

    # Runtime-tunable overrides (model, effort) — env defaults, persisted JSON overlays
    runtime = RuntimeConfig.load(config)
    log.info("Runtime: model=%s, effort=%s", runtime.model, runtime.effort)

    # Executor
    executor = CodexExecutor(config, runtime, apiary, gateway, persona=persona)
    log.info("Executor: max_parallel=%d, worktree_isolation=%s",
             config.codex_max_parallel, config.codex_worktree_isolation)

    # Build task list
    tasks = [executor.run()]
    if bot_app and gateway:
        tasks.append(run_telegram_bot(bot_app, executor, config, runtime))
        tasks.append(gateway.run())
    if apiary:
        tasks.append(run_apiary_poller(apiary, executor, config))

    if len(tasks) == 1:
        log.error("Neither Telegram nor Apiary is configured — nothing to do")
        sys.exit(1)

    # Graceful shutdown on SIGTERM/SIGINT
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: _shutdown(loop))

    # Auto-cleanup stale session data on startup
    if config.telegram_enabled:
        from .telegram_bot import _cleanup_stale_sessions
        counts = _cleanup_stale_sessions(max_age_hours=48)
        if counts["projects"] or counts["session_env"]:
            freed_mb = counts["bytes_freed"] / (1024 * 1024)
            log.info(
                "Startup cleanup: removed %d sessions, %d env snapshots (%.1fMB freed)",
                counts["projects"], counts["session_env"], freed_mb,
            )

    log.info("Starting %d tasks", len(tasks))
    try:
        await asyncio.gather(*tasks)
    finally:
        if apiary:
            try:
                await apiary.update_status("offline")
                log.info("Agent status set to offline")
            except Exception:
                log.debug("Failed to set agent status to offline (shutdown)")
            await apiary.close()


def _shutdown(loop: asyncio.AbstractEventLoop) -> None:
    log.info("Received shutdown signal")
    for task in asyncio.all_tasks(loop):
        task.cancel()


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
