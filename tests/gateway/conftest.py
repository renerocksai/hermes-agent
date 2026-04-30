"""Shared fixtures for gateway tests.

The ``_ensure_telegram_mock`` helper guarantees that a minimal mock of
the ``telegram`` package is registered in :data:`sys.modules` **before**
any test file triggers ``from gateway.platforms.telegram import ...``.

Without this, ``pytest-xdist`` workers that happen to collect
``test_telegram_caption_merge.py`` (bare top-level import, no per-file
mock) first will cache ``ChatType = None`` from the production
ImportError fallback, causing 30+ downstream test failures wherever
``ChatType.GROUP`` / ``ChatType.SUPERGROUP`` is accessed.

Individual test files may still call their own ``_ensure_telegram_mock``
— it short-circuits when the mock is already present.
"""

import sys
from unittest.mock import AsyncMock, MagicMock


def _ensure_telegram_mock() -> None:
    """Install a comprehensive telegram mock in sys.modules.

    Idempotent — skips when the real library is already imported.
    Uses ``sys.modules[name] = mod`` (overwrite) instead of
    ``setdefault`` so it wins even if a partial/broken import
    already cached a module with ``ChatType = None``.
    """
    if "telegram" in sys.modules and hasattr(sys.modules["telegram"], "__file__"):
        return  # Real library is installed — nothing to mock

    mod = MagicMock()
    mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
    mod.constants.ParseMode.MARKDOWN = "Markdown"
    mod.constants.ParseMode.MARKDOWN_V2 = "MarkdownV2"
    mod.constants.ParseMode.HTML = "HTML"
    mod.constants.ChatType.PRIVATE = "private"
    mod.constants.ChatType.GROUP = "group"
    mod.constants.ChatType.SUPERGROUP = "supergroup"
    mod.constants.ChatType.CHANNEL = "channel"

    # Real exception classes so ``except (NetworkError, ...)`` clauses
    # in production code don't blow up with TypeError.
    mod.error.NetworkError = type("NetworkError", (OSError,), {})
    mod.error.TimedOut = type("TimedOut", (OSError,), {})
    mod.error.BadRequest = type("BadRequest", (Exception,), {})
    mod.error.Forbidden = type("Forbidden", (Exception,), {})
    mod.error.InvalidToken = type("InvalidToken", (Exception,), {})
    mod.error.RetryAfter = type("RetryAfter", (Exception,), {"retry_after": 1})
    mod.error.Conflict = type("Conflict", (Exception,), {})

    # Update.ALL_TYPES used in start_polling()
    mod.Update.ALL_TYPES = []

    for name in (
        "telegram",
        "telegram.ext",
        "telegram.constants",
        "telegram.request",
    ):
        sys.modules[name] = mod
    sys.modules["telegram.error"] = mod.error


def _ensure_discord_mock() -> None:
    """Install a comprehensive discord mock in sys.modules.

    Idempotent — skips when the real library is already imported.
    Uses ``sys.modules[name] = mod`` (overwrite) instead of
    ``setdefault`` so it wins even if a partial/broken import already
    cached the module.

    This mock is comprehensive — it includes **all** attributes needed by
    every gateway discord test file.  Individual test files should call
    this function (it short-circuits when already present) rather than
    maintaining their own mock setup.
    """
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return  # Real library is installed — nothing to mock

    from types import SimpleNamespace

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.Interaction = object
    discord_mod.Embed = MagicMock
    discord_mod.ui = SimpleNamespace(
        View=object,
        button=lambda *a, **k: (lambda fn: fn),
        Button=object,
    )
    discord_mod.ButtonStyle = SimpleNamespace(
        success=1, primary=2, secondary=2, danger=3,
        green=1, grey=2, blurple=2, red=3,
    )
    discord_mod.Color = SimpleNamespace(
        orange=lambda: 1, green=lambda: 2, blue=lambda: 3,
        red=lambda: 4, purple=lambda: 5,
    )

    # app_commands — needed by _register_slash_commands auto-registration
    class _FakeGroup:
        def __init__(self, *, name, description, parent=None):
            self.name = name
            self.description = description
            self.parent = parent
            self._children: dict = {}
            if parent is not None:
                parent.add_command(self)

        def add_command(self, cmd):
            self._children[cmd.name] = cmd

    class _FakeCommand:
        def __init__(self, *, name, description, callback, parent=None):
            self.name = name
            self.description = description
            self.callback = callback
            self.parent = parent

    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
        Group=_FakeGroup,
        Command=_FakeCommand,
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    for name in ("discord", "discord.ext", "discord.ext.commands"):
        sys.modules[name] = discord_mod
    sys.modules["discord.ext"] = ext_mod
    sys.modules["discord.ext.commands"] = commands_mod


def _ensure_synadia_agents_mock() -> None:
    """Install a minimal synadia_ai.agents mock in sys.modules.

    Idempotent — skips when the real SDK is already imported. Mirrors the
    Telegram/Discord pattern so gateway tests can import the NATS adapter
    module without requiring synadia-ai-agents to be installed.

    Also mocks ``nats`` (nats-py): the adapter calls ``nats.connect(...)``
    directly because the SDK explicitly does NOT own NATS connections
    (callers build the client and hand it to ``AgentService``).
    """
    # Mock each submodule independently so a partial install (e.g. one SDK
    # ships on PyPI before the other) doesn't cause the mock for the
    # already-installed module to clobber the real one. The earlier
    # combined guard would fall through if EITHER module was missing,
    # then unconditionally overwrite ``sys.modules["synadia_ai.agents"]``
    # with a MagicMock — silently breaking any production code path that
    # imported the real SDK in the same process.
    need_client_mock = not (
        "synadia_ai.agents" in sys.modules
        and hasattr(sys.modules["synadia_ai.agents"], "__file__")
    )
    need_agent_service_mock = not (
        "synadia_ai.agent_service" in sys.modules
        and hasattr(sys.modules["synadia_ai.agent_service"], "__file__")
    )

    if not need_client_mock and not need_agent_service_mock:
        return  # Both real SDKs are installed — nothing to mock

    if need_client_mock:
        mod = MagicMock()

        # Context-options helper that the adapter uses for the `context` path
        # (no return shape needed beyond "a dict that splats into nats.connect").
        mod.load_context_options = MagicMock(return_value={"servers": ["nats://stub:4222"]})

        # Real exception classes so ``except sdk.QueryTimeout`` works.
        mod.QueryTimeout = type("QueryTimeout", (Exception,), {})
        mod.ProtocolError = type("ProtocolError", (Exception,), {})

        # Envelope / Attachment / chunk types — pydantic-ish stand-ins.
        class _FakeAttachment:
            def __init__(self, filename: str = "", content: str = ""):
                self.filename = filename
                self.content = content

            def to_bytes(self) -> bytes:
                return b""

            @classmethod
            def from_path(cls, path):
                instance = cls(filename=str(path))
                return instance

            @classmethod
            def from_bytes(cls, filename, data):
                return cls(filename=filename)

        mod.Attachment = _FakeAttachment
        mod.Envelope = MagicMock
        # ResponseChunk / StatusChunk are constructed via kwargs (text=..., status=...).
        # Use simple stand-ins that accept kwargs and remember them — tests assert
        # on ``.text`` / ``.status`` to verify the adapter wrapped outgoing content
        # correctly.
        class _FakeResponseChunk:
            def __init__(self, *, text: str = "", attachments=None):
                self.text = text
                self.attachments = attachments

        class _FakeStatusChunk:
            def __init__(self, *, status: str):
                self.status = status

        mod.ResponseChunk = _FakeResponseChunk
        mod.StatusChunk = _FakeStatusChunk
    else:
        mod = sys.modules["synadia_ai.agents"]

    if need_agent_service_mock:
        # Host-side surface — AgentService / PromptStream / PromptHandler.
        agent_service_mod = MagicMock()
        agent_service_mod.AgentService = MagicMock()
        agent_service_mod.AgentService.return_value.start = AsyncMock()
        agent_service_mod.AgentService.return_value.stop = AsyncMock()
        agent_service_mod.PromptStream = MagicMock()
        agent_service_mod.PromptHandler = MagicMock  # forward-looking; hermes never imports it
    else:
        agent_service_mod = sys.modules["synadia_ai.agent_service"]

    # Register only the modules we actually mocked. Re-anchor the parent
    # package via a MagicMock if missing, but never clobber an already-real
    # submodule with our stand-in.
    parent = sys.modules.get("synadia_ai") or MagicMock()
    parent.agents = mod
    parent.agent_service = agent_service_mod
    sys.modules["synadia_ai"] = parent
    if need_client_mock:
        sys.modules["synadia_ai.agents"] = mod
    if need_agent_service_mock:
        sys.modules["synadia_ai.agent_service"] = agent_service_mod

    # ``nats`` (nats-py) is the connection factory the adapter calls
    # directly. Mock it only if the real package isn't installed — most
    # CI / dev installs have nats-py since it's a transitive dep of
    # synadia-ai-agents itself.
    if "nats" not in sys.modules or not hasattr(sys.modules["nats"], "__file__"):
        nats_mod = MagicMock()
        nats_mod.connect = AsyncMock()
        nats_mod.connect.return_value.close = AsyncMock()
        sys.modules["nats"] = nats_mod


# Run at collection time — before any test file's module-level imports.
_ensure_telegram_mock()
_ensure_discord_mock()
_ensure_synadia_agents_mock()
