"""Singleton FastMCP instance shared by every tool module. All
@mcp.tool() definitions across the package register on this same instance,
so server.py can simply import every tool module and call mcp.run().

Tools are registered through two thin wrappers around ``mcp.tool`` that
attach MCP 2025-06-18 ``ToolAnnotations`` so clients can tell reads from
writes without calling them:

  * ``@read_tool()``  — pure query, no state mutation (``readOnlyHint=True``).
  * ``@write_tool()`` — mutates state (``readOnlyHint=False``); pass
    ``destructive=True`` for delete/overwrite/kill tools and
    ``idempotent=True`` where a repeat call is a no-op.

This static metadata layer is what a confirmation/elicitation client reads
to decide which calls warrant a prompt (roadmap #67; substrate for #26).
"""
try:  # MCP 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # MCP 2.x renamed FastMCP to MCPServer.
    from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from .tool_profiles import environment_selection

mcp = FastMCP("thread-keeper")
_active_tool_names: frozenset[str] = frozenset()


def active_tool_names() -> frozenset[str]:
    """Return the tools actually exposed by this server instance."""
    return _active_tool_names or frozenset(mcp._tool_manager._tools)


def configure_tool_profile() -> frozenset[str]:
    """Remove tools outside the configured profile before ``tools/list`` runs."""
    global _active_tool_names
    from .config import settings

    registered = frozenset(mcp._tool_manager._tools)
    selected = environment_selection(
        registered,
        profile=settings.tool_profile,
        include=settings.tool_include,
        exclude=settings.tool_exclude,
        parent_allowlist=settings.tool_parent_allowlist or None,
    )
    remove_tool = getattr(mcp, "remove_tool", mcp._tool_manager.remove_tool)
    for name in registered - selected:
        remove_tool(name)
    _active_tool_names = selected
    return selected


def read_tool(**kwargs):
    """Register a read-only MCP tool (``readOnlyHint=True``).

    Use for pure queries that do not modify thread-keeper state — briefs,
    searches, status snapshots, listings. Extra kwargs pass through to
    ``mcp.tool`` (e.g. ``name=``)."""
    return mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
        **kwargs,
    )


def write_tool(*, destructive: bool = False, idempotent: bool = False, **kwargs):
    """Register a state-mutating MCP tool (``readOnlyHint=False``).

    ``destructive=True`` sets ``destructiveHint=True`` for tools that delete,
    overwrite, archive, or kill (``compost`` excluded — it only reads).
    ``idempotent=True`` sets ``idempotentHint=True`` where repeating the call
    is a no-op (closing an already-closed thread, deleting a missing key)."""
    return mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=destructive,
            idempotentHint=idempotent,
        ),
        **kwargs,
    )


def structured_result(text: str, model: BaseModel) -> CallToolResult:
    """Build a CallToolResult that carries BOTH the legacy human-readable
    ``text`` block AND ``model`` as machine-readable ``structuredContent``.

    The tool's return annotation (a pydantic model) supplies the advertised
    ``outputSchema`` in ``tools/list``; this helper keeps the serialized text
    block for backward compatibility, as the MCP 2025-06-18 spec recommends
    for tools that emit structured content."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=model.model_dump(mode="json", by_alias=True),
    )
