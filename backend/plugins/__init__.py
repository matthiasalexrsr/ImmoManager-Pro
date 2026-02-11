"""Plugin system for ImmoManager Pro.

Plugins are Python packages that contain a class inheriting from Plugin.
They are discovered from directories listed in settings.plugin_dirs.
"""

import importlib
import logging
import sys
from pathlib import Path

from .base import Plugin

logger = logging.getLogger(__name__)

_plugins: list[Plugin] = []


def discover_plugins(plugin_dirs: list[str]) -> list[Plugin]:
    """Scan directories for plugin packages and instantiate them."""
    discovered = []
    for dir_path in plugin_dirs:
        p = Path(dir_path)
        if not p.is_dir():
            logger.warning("Plugin directory not found: %s", dir_path)
            continue
        # Add to sys.path so plugins can be imported
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
        for child in sorted(p.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                try:
                    mod = importlib.import_module(child.name)
                    # Look for a Plugin subclass
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, Plugin)
                            and attr is not Plugin
                        ):
                            plugin = attr()
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
