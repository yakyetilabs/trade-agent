"""Offline evaluation harness for the trade-agent (Phase 4).

Runs a version-controlled suite of grounded cases through ``run_agent`` for both the
primary and the eval-counterpart model (whatever ``src/config.py`` currently pins),
scores each case against deterministic, data-grounded assertions, and writes cost/accuracy/latency
reports to ``eval/results/`` (gitignored). The case data (``cases.json``) stays in
version control; the generated reports do not.
"""
