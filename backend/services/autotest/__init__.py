"""Self-testing framework for ImmoManager Pro.

Provides comprehensive automated testing that the application can run against
itself in developer mode. Tests cover API routes, authentication, data integrity,
security posture, configuration, frontend contract compliance, and more.

Results are formatted as structured Markdown reports designed to be consumed
by Claude Code for automated issue detection and resolution.
"""

from .runner import AutotestRunner, run_all_tests

__all__ = ["AutotestRunner", "run_all_tests"]
