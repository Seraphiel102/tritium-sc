# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Addon loader — discovers addons from directories, resolves dependencies, manages lifecycle."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from tritium_lib.sdk import AddonBase
from tritium_lib.sdk.manifest import AddonManifest, load_manifest, validate_manifest

try:
    from tritium_lib.sdk import AddonContext, AddonEventBus
    _HAS_ADDON_CONTEXT = True
except ImportError:
    _HAS_ADDON_CONTEXT = False

log = logging.getLogger("addons.loader")


class AddonEntry:
    """Internal tracking for a discovered addon."""

    def __init__(self, manifest: AddonManifest, path: Path):
        self.manifest = manifest
        self.path = path
        self.instance: AddonBase | None = None
        self.enabled = False
        self.error: str | None = None
        self.crash_count = 0


class AddonLoader:
    """Discovers, loads, enables, and disables addons.

    Usage::

        loader = AddonLoader(["addons/", "~/.tritium/addons/"], app)
        loader.discover()
        await loader.enable("meshtastic")
        # ... later ...
        await loader.disable("meshtastic")
    """

    def __init__(self, addon_dirs: list[str], app: Any = None):
        self.addon_dirs = [Path(d).expanduser().resolve() for d in addon_dirs]
        self.app = app
        self.registry: dict[str, AddonEntry] = {}
        self.enabled: set[str] = set()

    def _build_context(self) -> "AddonContext | None":
        """Build an AddonContext from SC app internals.

        Returns None if AddonContext is not available (import error).
        """
        if not _HAS_ADDON_CONTEXT:
            return None

        app = self.app
        if app is None:
            return None

        # Extract services from SC's app.state
        amy = getattr(getattr(app, 'state', None), 'amy', None)
        target_tracker = None
        event_bus = None
        if amy:
            target_tracker = getattr(amy, 'target_tracker', None)
            event_bus = getattr(amy, 'event_bus', None)
        if target_tracker is None:
            target_tracker = getattr(app, 'target_tracker', None)
        if event_bus is None:
            event_bus = getattr(app, 'event_bus', None)

        mqtt_client = getattr(getattr(app, 'state', None), 'mqtt_bridge', None)
        site_id = getattr(
            app, 'site_id',
            getattr(getattr(app, 'state', None), 'site_id', 'home'),
        )

        # Router handler — wraps app.include_router
        router_handler = app if hasattr(app, 'include_router') else None

        # Addon event bus (shared across all addons)
        if not hasattr(self, '_addon_event_bus'):
            self._addon_event_bus = AddonEventBus(event_bus=event_bus)

        # Persistent state dict (survives hot-reload, per-addon)
        if not hasattr(app, 'state'):
            from types import SimpleNamespace
            app.state = SimpleNamespace()
        addon_states = getattr(app.state, '_addon_states', {})
        app.state._addon_states = addon_states

        return AddonContext(
            target_tracker=target_tracker,
            event_bus=event_bus,
            mqtt_client=mqtt_client,
            router_handler=router_handler,
            site_id=site_id,
            data_dir=str(Path("data")),
            state=addon_states,
            addon_event_bus=self._addon_event_bus,
            app=app,
        )

    def discover(self) -> list[str]:
        """Scan addon directories for tritium_addon.toml manifests.

        Returns:
            List of discovered addon IDs.
        """
        discovered = []
        for d in self.addon_dirs:
            if not d.exists():
                continue
            for manifest_path in d.glob("*/tritium_addon.toml"):
                try:
                    manifest = load_manifest(manifest_path)
                    errors = validate_manifest(manifest)
                    if errors:
                        log.warning(f"Invalid manifest {manifest_path}: {errors}")
                        continue
                    self.registry[manifest.id] = AddonEntry(manifest, manifest_path.parent)
                    discovered.append(manifest.id)
                    log.info(f"Discovered addon: {manifest.id} v{manifest.version} at {manifest_path.parent}")
                except Exception as e:
                    log.warning(f"Failed to load manifest {manifest_path}: {e}")

        return discovered

    async def enable(self, addon_id: str) -> bool:
        """Enable an addon: import module, instantiate, register with app.

        Args:
            addon_id: ID from the addon's manifest.

        Returns:
            True if successfully enabled.
        """
        entry = self.registry.get(addon_id)
        if not entry:
            log.error(f"Unknown addon: {addon_id}")
            return False

        if addon_id in self.enabled:
            log.info(f"Addon already enabled: {addon_id}")
            return True

        # Check dependencies
        for dep in entry.manifest.requires:
            dep_id = dep.split(">=")[0].split("<")[0].strip()
            if dep_id not in self.enabled:
                log.error(f"Addon '{addon_id}' requires '{dep_id}' which is not enabled")
                return False

        # Add addon's module path to sys.path
        module_path = entry.path
        addon_module_dir = str(module_path)
        if addon_module_dir not in sys.path:
            sys.path.insert(0, addon_module_dir)

        # Import the addon module
        try:
            module_name = entry.manifest.module
            if not module_name:
                module_name = f"{addon_id.replace('-', '_')}_addon"
            module = importlib.import_module(module_name)
        except ImportError as e:
            log.error(f"Failed to import addon module '{module_name}': {e}")
            entry.error = str(e)
            return False

        # Find the AddonBase subclass
        addon_class = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and issubclass(attr, AddonBase)
                    and attr is not AddonBase and not attr.__name__.startswith("_")):
                addon_class = attr
                break

        if not addon_class:
            log.error(f"No AddonBase subclass found in {module_name}")
            entry.error = "No AddonBase subclass found"
            return False

        # Instantiate and register
        try:
            instance = addon_class()

            # Build AddonContext if available, with per-addon state namespace
            addon_context = None
            base_context = self._build_context()
            if base_context is not None:
                addon_state_key = f"_addon_{addon_id}"
                if addon_state_key not in base_context.state:
                    base_context.state[addon_state_key] = {}
                addon_context = AddonContext(
                    target_tracker=base_context.target_tracker,
                    event_bus=base_context.event_bus,
                    mqtt_client=base_context.mqtt_client,
                    router_handler=base_context.router_handler,
                    site_id=base_context.site_id,
                    data_dir=base_context.data_dir,
                    state=base_context.state[addon_state_key],
                    addon_event_bus=base_context.addon_event_bus,
                    app=base_context.app,
                )

            if addon_context is not None:
                await instance.register(app=self.app, context=addon_context)
            else:
                await instance.register(self.app)

            entry.instance = instance
            entry.enabled = True
            entry.error = None
            self.enabled.add(addon_id)
            log.info(f"Enabled addon: {addon_id} ({addon_class.__name__})")
            return True
        except Exception as e:
            log.error(f"Failed to register addon '{addon_id}': {e}")
            entry.error = str(e)
            entry.crash_count += 1
            return False

    async def disable(self, addon_id: str) -> bool:
        """Disable an addon: unregister, cleanup.

        Args:
            addon_id: ID of the addon to disable.

        Returns:
            True if successfully disabled.
        """
        entry = self.registry.get(addon_id)
        if not entry or not entry.instance:
            return False

        try:
            await entry.instance.unregister(self.app)
        except Exception as e:
            log.warning(f"Addon unregister error for '{addon_id}': {e}")

        entry.instance = None
        entry.enabled = False
        self.enabled.discard(addon_id)
        log.info(f"Disabled addon: {addon_id}")
        return True

    def get_manifests(self) -> list[dict]:
        """Return frontend-compatible manifest data for all enabled addons."""
        result = []
        for addon_id in self.enabled:
            entry = self.registry.get(addon_id)
            if entry and entry.manifest:
                data = entry.manifest.to_frontend_json()
                data["enabled"] = True
                data["healthy"] = entry.instance.health_check()["status"] == "ok" if entry.instance else False
                result.append(data)
        return result

    def get_all_addons(self) -> list[dict]:
        """Return info about all discovered addons (enabled or not)."""
        result = []
        for addon_id, entry in self.registry.items():
            result.append({
                "id": addon_id,
                "name": entry.manifest.name,
                "version": entry.manifest.version,
                "description": entry.manifest.description,
                "category": entry.manifest.category_window,
                "enabled": entry.enabled,
                "error": entry.error,
                "crash_count": entry.crash_count,
                "path": str(entry.path),
            })
        return result

    async def reload(self, addon_id: str) -> bool:
        """Hot-reload an addon: disable, purge Python module cache, re-import, re-enable.

        This is the key operation for development — change addon code, call reload,
        see changes without restarting the server.
        """
        entry = self.registry.get(addon_id)
        if not entry:
            log.error(f"Unknown addon: {addon_id}")
            return False

        was_enabled = addon_id in self.enabled

        # 1. Disable if running
        if was_enabled:
            await self.disable(addon_id)

        # 2. Re-read manifest (picks up TOML changes)
        manifest_path = entry.path / "tritium_addon.toml"
        if manifest_path.exists():
            try:
                new_manifest = load_manifest(manifest_path)
                errors = validate_manifest(new_manifest)
                if errors:
                    log.warning(f"Invalid manifest after reload: {errors}")
                else:
                    entry.manifest = new_manifest
                    log.info(f"Reloaded manifest for {addon_id}")
            except Exception as e:
                log.warning(f"Failed to reload manifest for {addon_id}: {e}")

        # 3. Purge Python module cache for this addon
        module_name = entry.manifest.module or f"{addon_id.replace('-', '_')}_addon"
        to_remove = [k for k in sys.modules if k == module_name or k.startswith(module_name + ".")]
        for k in to_remove:
            del sys.modules[k]
            log.debug(f"Purged module: {k}")

        # 4. Re-enable if it was running
        if was_enabled:
            ok = await self.enable(addon_id)
            if ok:
                log.info(f"Hot-reloaded addon: {addon_id}")
            else:
                log.error(f"Failed to re-enable addon {addon_id} after reload")
            return ok

        log.info(f"Reloaded addon manifest: {addon_id} (not re-enabled)")
        return True

    def rediscover(self) -> list[str]:
        """Re-scan addon directories for new or changed addons.

        Finds new addons that weren't present at boot. Does NOT touch
        already-loaded addons — use reload() for those.

        Returns list of newly discovered addon IDs.
        """
        new_ids = []
        for d in self.addon_dirs:
            if not d.exists():
                continue
            for manifest_path in d.glob("*/tritium_addon.toml"):
                try:
                    manifest = load_manifest(manifest_path)
                    errors = validate_manifest(manifest)
                    if errors:
                        continue
                    if manifest.id not in self.registry:
                        self.registry[manifest.id] = AddonEntry(manifest, manifest_path.parent)
                        new_ids.append(manifest.id)
                        log.info(f"Discovered new addon: {manifest.id}")
                except Exception:
                    pass
        return new_ids

    def get_health(self) -> dict:
        """Overall addon system health."""
        return {
            "discovered": len(self.registry),
            "enabled": len(self.enabled),
            "healthy": sum(1 for aid in self.enabled
                          if self.registry[aid].instance
                          and self.registry[aid].instance.health_check()["status"] == "ok"),
            "errors": sum(1 for e in self.registry.values() if e.error),
        }
