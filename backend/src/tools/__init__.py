"""Agent tools - one file per tool. Vendor scope arrives via ``ToolRuntime``.

Intentionally a plain package marker with no re-exports: each tool function
shares its name with its module, so re-exporting here would shadow the submodule
attribute. Import tools explicitly from their modules, e.g.
``from src.tools.draft_clearance_response import draft_clearance_response``.
"""
