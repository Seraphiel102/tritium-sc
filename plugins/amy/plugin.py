# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AmyCommanderPlugin — Phase 4 plugin for the Amy AI Commander.

This wraps the existing src/amy/ code WITHOUT moving any files. It provides
a PluginInterface-compliant wrapper so Amy can be discovered, configured,
and managed through the plugin system alongside other plugins.

Phase 1 (done): Plugin shell wrapping existing code.
Phase 2 (done): Move Amy router registration into this plugin.
Phase 3 (done): Move Amy lifecycle (create/start/stop) fully into plugin.
Phase 4 (current): Move EventBus subscriptions into the plugin.
    - start_amy_event_bridge (sim_telemetry, fleet.ble_presence,
      meshtastic:nodes_updated) — the WebSocket event bridge that forwards
      Amy EventBus events to the browser.
    - WarAnnouncer — game event commentary via TTS.
    These were previously wired in main.py's lifespan. Now the plugin owns
    all Amy-related EventBus wiring. main.py only calls plugin.start().
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from engine.plugins.base import PluginInterface, PluginContext

log = logging.getLogger("amy-plugin")


class AmyCommanderPlugin(PluginInterface):
    """Plugin wrapper around the existing Amy AI Commander.

    Phase 4: This plugin now OWNS Amy's full lifecycle AND EventBus wiring:
    - configure(): Registers routes, stores references.
    - start(): Creates the Amy Commander instance, starts the thinking
      loop in a background thread, wires EventBus bridge to WebSocket,
      starts the WarAnnouncer, and publishes app.state.amy.
    - stop(): Shuts down Amy, announcer, clears app.state.amy.

    main.py lifespan delegates to this plugin instead of managing Amy directly.
    """

    def __init__(self) -> None:
        self._amy_instance: Any = None
        self._amy_thread: Optional[threading.Thread] = None
        self._announcer: Any = None
        self._app: Any = None
        self._settings: Any = None
        self._simulation_engine: Any = None
        self._event_loop: Any = None
        self._logger = log
        self._running = False

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.amy-commander"

    @property
    def name(self) -> str:
        return "Amy AI Commander"

    @property
    def version(self) -> str:
        return "4.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai", "routes", "ui", "background"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references, register routes.

        Note: Amy is NOT created here — that happens in start().
        This is because other plugins may need to configure first.
        """
        self._app = ctx.app
        self._simulation_engine = ctx.simulation_engine
        self._event_loop = getattr(ctx, "event_loop", None)
        self._logger = ctx.logger or self._logger

        # Import settings lazily to avoid circular imports at module level
        try:
            from app.config import settings
            self._settings = settings
        except Exception as e:
            self._logger.warning("Could not import settings: %s", e)

        # Register Amy's routes through the plugin system
        self._register_routes()

    def _register_routes(self) -> None:
        """Register Amy's FastAPI routes on the app.

        Imports and includes the router from src/amy/router.py. This
        replaces the direct `app.include_router(amy_router)` call that
        was previously in src/app/main.py.
        """
        if self._app is None:
            self._logger.warning("No app reference, cannot register Amy routes")
            return

        try:
            from amy.router import router as amy_router
            self._app.include_router(amy_router)
            self._logger.info("Amy router registered: /api/amy/*")
        except Exception as exc:
            self._logger.error("Failed to register Amy routes: %s", exc)

    def start(self) -> None:
        """Create and start the Amy AI Commander.

        Phase 4: This plugin now owns Amy's full lifecycle AND EventBus
        wiring. Creates the Commander instance, starts the background
        thinking loop, wires the EventBus bridge to WebSocket for
        real-time browser updates (sim_telemetry, fleet.ble_presence,
        meshtastic:nodes_updated), starts the WarAnnouncer for game
        commentary, and publishes the instance to app.state.amy.
        """
        self._running = True

        if self._settings is None or not getattr(self._settings, "amy_enabled", False):
            self._logger.info(
                "Amy Commander plugin started (Amy disabled in config)"
            )
            return

        # Check for existing Amy instance (backward compat — main.py may
        # have created Amy before plugin system started)
        if self._app is not None:
            existing = getattr(self._app.state, "amy", None)
            if existing is not None:
                self._amy_instance = existing
                self._start_event_bridge()
                self._start_announcer()
                self._logger.info(
                    "Amy Commander plugin started (wrapping pre-existing instance, "
                    "Phase 4 — event bridge + announcer plugin-owned)"
                )
                return

        # Create Amy
        try:
            from amy import create_amy

            self._logger.info("Creating Amy AI Commander...")
            self._amy_instance = create_amy(
                self._settings,
                simulation_engine=self._simulation_engine,
            )

            # Re-wire simulation engine to Amy's event bus
            if self._simulation_engine is not None:
                self._simulation_engine.set_event_bus(self._amy_instance.event_bus)

            # Launch thinking loop in background thread
            self._amy_thread = threading.Thread(
                target=self._amy_instance.run,
                daemon=True,
                name="amy",
            )
            self._amy_thread.start()

            # Publish to app.state so other subsystems can find Amy
            if self._app is not None:
                self._app.state.amy = self._amy_instance

            # Phase 4: Wire EventBus bridge and announcer
            self._start_event_bridge()
            self._start_announcer()

            self._logger.info("Amy AI Commander started (Phase 4 — plugin-owned)")

        except Exception as e:
            self._logger.error("Amy Commander failed to start: %s", e)
            self._amy_instance = None
            if self._app is not None:
                self._app.state.amy = None

    def _start_event_bridge(self) -> None:
        """Wire Amy's EventBus to the WebSocket broadcast system.

        Phase 4: This was previously done in main.py's lifespan via
        start_amy_event_bridge(). Now the plugin owns this wiring.
        """
        if self._amy_instance is None:
            return
        try:
            import asyncio
            from app.routers.ws import start_amy_event_bridge

            loop = self._event_loop or asyncio.get_event_loop()
            start_amy_event_bridge(self._amy_instance, loop)
            self._logger.info("Amy event bridge started (Phase 4 — plugin-owned)")
        except Exception as e:
            self._logger.warning("Amy event bridge failed: %s", e)

    def _start_announcer(self) -> None:
        """Start the WarAnnouncer for game event commentary.

        Phase 4: This was previously done in main.py's lifespan.
        Now the plugin owns it.
        """
        if self._amy_instance is None or self._simulation_engine is None:
            return
        try:
            from amy.actions.announcer import WarAnnouncer
            self._announcer = WarAnnouncer(
                self._amy_instance.event_bus,
                speaker=getattr(self._amy_instance, "speaker", None),
            )
            self._announcer.start()
            if self._app is not None:
                self._app.state.announcer = self._announcer
            self._logger.info("War announcer started (Phase 4 — plugin-owned)")
        except Exception as e:
            self._logger.warning("War announcer failed to start: %s", e)

    def stop(self) -> None:
        """Shut down Amy AI Commander.

        Phase 4: Stops announcer, shuts down Amy, and clears references.
        """
        self._running = False

        # Stop announcer first
        if self._announcer is not None:
            try:
                self._announcer.stop()
                self._logger.info("War announcer stopped")
            except Exception as e:
                self._logger.warning("Announcer stop error: %s", e)
            self._announcer = None

        if self._amy_instance is not None:
            self._logger.info("Shutting down Amy AI Commander...")
            try:
                self._amy_instance.shutdown()
            except Exception as e:
                self._logger.error("Amy shutdown error: %s", e)
            self._amy_instance = None

        if self._amy_thread is not None:
            self._amy_thread = None

        # Clear app.state references
        if self._app is not None:
            try:
                self._app.state.amy = None
                self._app.state.announcer = None
            except Exception:
                pass

        self._logger.info("Amy Commander plugin stopped (Phase 4)")

    @property
    def healthy(self) -> bool:
        """Report health based on Amy's actual state."""
        if not self._running:
            return False
        if self._amy_instance is not None:
            return getattr(self._amy_instance, "running", self._running)
        return self._running

    # -- Amy accessors (for plugin-to-plugin communication) ----------------

    @property
    def amy(self) -> Any:
        """Return the wrapped Amy commander instance, or None."""
        # Lazy lookup in case Amy was initialized after us
        if self._amy_instance is None and self._app is not None:
            self._amy_instance = getattr(self._app.state, "amy", None)
        return self._amy_instance

    def get_status(self) -> dict:
        """Return Amy status summary for plugin dashboard integration."""
        amy = self.amy
        if amy is None:
            return {
                "plugin_id": self.plugin_id,
                "status": "not_initialized",
                "running": False,
            }

        return {
            "plugin_id": self.plugin_id,
            "status": "running" if getattr(amy, "running", False) else "stopped",
            "running": getattr(amy, "running", False),
            "mode": getattr(amy, "_mode", "unknown"),
            "think_count": getattr(amy, "_think_count", 0),
            "node_count": len(getattr(amy, "nodes", {})),
        }
