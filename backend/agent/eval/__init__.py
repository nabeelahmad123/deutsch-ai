"""Offline evaluation of the agent's planning loop (not the scheduler).

``cases`` holds labelled natural-language requests; ``harness`` runs the real
agent on each and scores three axes -- intent parsing, tool-call sequence, and
session sanity (checked against the DB, not the model's word for it). See
``docs/AGENT_EVAL.md`` for the latest run.
"""
