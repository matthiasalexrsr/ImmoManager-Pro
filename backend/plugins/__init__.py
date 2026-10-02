"""Plugin system for ImmoManager Pro.

Plugins are Python packages that contain a class inheriting from Plugin.
They are discovered from directories listed in settings.plugin_dirs.
"""

import hashlib
import importlib.util
import logging
import re
import sys
from pathlib import Path

from .base import Plugin

logger = logging.getLogger(__name__)

_plugins: list[Plugin] = []


def discover_plugins(plugin_dirs: list[str]) -> list[Plugin]:
    """Scan directories for plugin packages and instantiate them."""
    discovered: list[Plugin] = []
    for dir_path in plugin_dirs:
        p = Path(dir_path)
        if not p.is_dir():
            logger.warning("Plugin directory not found: %s", dir_path)
            continue
        for child in sorted(p.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                try:
                    identity = hashlib.sha256(str(child.resolve()).encode()).hexdigest()[:20]
                    module_name = f"_immo_local_plugin_{identity}"
                    spec = importlib.util.spec_from_file_location(
                        module_name, child / "__init__.py",
                        submodule_search_locations=[str(child)],
                    )
                    if spec is None or spec.loader is None:
                        raise ValueError("Plugin package cannot be loaded")
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)
                    # Look for a Plugin subclass
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, Plugin)
                            and attr is not Plugin
                        ):
                            plugin = attr()
                            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", plugin.name):
                                raise ValueError("Invalid plugin identifier")
                            if any(item.name == plugin.name for item in discovered):
                                raise ValueError("Duplicate plugin identifier")
                            discovered.append(plugin)
                            logger.info(
                                "Discovered plugin: %s v%s",
                                plugin.name, plugin.version,
                            )
                            break
                except Exception:
                    logger.exception("Failed to load plugin from %s", child.name)
    return discovered


def load_plugins(plugin_dirs: list[str]) -> list[Plugin]:
    """Discover, validate, and store plugins."""
    global _plugins
    _plugins = discover_plugins(plugin_dirs)
    return _plugins


def get_plugins() -> list[Plugin]:
    """Return list of loaded plugins."""
    return list(_plugins)


def start_plugins(app, plugins: list[Plugin]) -> None:
    """Stage each plugin independently; failed startup publishes no routes."""
    from fastapi import FastAPI

    from .runtime import AuthenticatedPlugin

    for plugin in plugins:
        plugin._runtime_status = "starting"  # type: ignore[attr-defined]
        try:
            isolated = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
            plugin.register_routes(isolated, "")
            plugin.on_startup()
            prefix = f"/api/v1/plugins/{plugin.name}"
            app.mount(prefix, AuthenticatedPlugin(isolated), name=f"local-plugin-{plugin.name}")
            # Startup occurs after the frontend catch-all was registered.
            app.routes.insert(0, app.routes.pop())
            plugin._runtime_status = "active"  # type: ignore[attr-defined]
        except Exception:
            plugin._runtime_status = "failed"  # type: ignore[attr-defined]
            logger.exception("Failed to start plugin: %s", plugin.name)
            try:
                plugin.on_shutdown()
            except Exception:
                logger.exception("Failed to clean up plugin: %s", plugin.name)


def stop_plugins(app, plugins: list[Plugin]) -> None:
    """Shutdown only started plugins, in reverse order, removing owned mounts."""
    for plugin in reversed(plugins):
        if getattr(plugin, "_runtime_status", None) != "active":
            continue
        try:
            plugin.on_shutdown()
            plugin._runtime_status = "stopped"  # type: ignore[attr-defined]
        except Exception:
            plugin._runtime_status = "shutdown_failed"  # type: ignore[attr-defined]
            logger.exception("Error shutting down plugin: %s", plugin.name)
        app.routes[:] = [route for route in app.routes if getattr(route, "name", None) != f"local-plugin-{plugin.name}"]
