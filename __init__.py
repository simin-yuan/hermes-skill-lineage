"""Hermes entry point for skill-lineage: registration only.

The imports live inside ``register`` so this file can be imported on its own (pytest imports a
directory's ``__init__.py`` when it collects tests below it).
"""

from __future__ import annotations


def register(ctx) -> None:
    from .skill_lineage import cli
    from .skill_lineage.hooks import Tracker

    tracker = Tracker()
    ctx.register_hook("on_session_start", tracker.on_session_start)
    ctx.register_hook("pre_llm_call", tracker.pre_llm_call)
    ctx.register_hook("pre_tool_call", tracker.pre_tool_call)
    ctx.register_hook("post_tool_call", tracker.post_tool_call)
    ctx.register_cli_command("skill-lineage", help=cli.HELP, setup_fn=cli.setup,
                             handler_fn=cli.make_handler(), description=cli.DESCRIPTION)
