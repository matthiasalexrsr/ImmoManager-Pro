"""Plugin system for ImmoManager Pro.

Plugins are Python packages that contain a class inheriting from Plugin.
They are discovered from directories listed in settings.plugin_dirs.
"""

import hashlib
import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from .base import Plugin

logger = logging.getLogger(__name__)

_plugins: list[Plugin] = []
_discovery_errors: list[dict] = []


def discover_plugins(plugin_dirs: list[str]) -> list[Plugin]:
    """Scan directories for plugin packages and instantiate them."""
    discovered: list[Plugin] = []
    _discovery_errors.clear()
    for dir_path in plugin_dirs:
        p = Path(dir_path)
        if not p.is_dir():
            logger.warning("Plugin directory not found: %s", dir_path)
            _discovery_errors.append({"package": p.name, "status": "directory_missing"})
            continue
        for child in sorted(p.iterdir()):
            if child.is_dir() and not child.is_symlink() and (child / "__init__.py").exists():
                try:
                    from ..services.plugin_packages import package
                    declaration, _ = package(child)
                    module_name = "_immo_plugin_" + hashlib.sha256(str(child.resolve()).encode()).hexdigest()
                    spec = importlib.util.spec_from_file_location(module_name, child / "__init__.py",
                                                                 submodule_search_locations=[str(child)])
                    if spec is None or spec.loader is None:
                        raise ValueError("Pluginpaket kann nicht geladen werden")
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
                            plugin.package_declaration = declaration
                            from .lifecycle import manifest
                            manifest(plugin)
                            if (plugin.name, plugin.version) != (declaration["name"], declaration["version"]):
                                raise ValueError("Plugincode und Paketdeklaration weichen ab")
                            if any(existing.name == plugin.name for existing in discovered):
                                raise ValueError("Doppelter Pluginname")
                            discovered.append(plugin)
                            logger.info(
                                "Discovered plugin: %s v%s",
                                plugin.name, plugin.version,
                            )
                            break
                except Exception as exc:
                    _discovery_errors.append({"package": child.name, "status": "incompatible_or_invalid"})
                    logger.warning("Plugin rejected: %s (%s)", child.name, type(exc).__name__)
    return discovered


def load_plugins(plugin_dirs: list[str]) -> list[Plugin]:
    """Discover, validate, and store plugins."""
    global _plugins
    _plugins = discover_plugins(plugin_dirs)
    return _plugins


def get_plugins() -> list[Plugin]:
    """Return list of loaded plugins."""
    return list(_plugins)


def get_plugin_errors() -> list[dict]:
    return [dict(item) for item in _discovery_errors]


from .runtime import start_plugins, stop_plugins  # noqa: E402,F401
