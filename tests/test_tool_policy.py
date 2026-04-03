"""Tests for task-start tool visibility policy."""

import inspect
import pathlib
import tempfile

import ouroboros.loop as loop_mod
from ouroboros.tool_policy import CORE_TOOL_NAMES, initial_tool_schemas, list_non_core_tools
from ouroboros.tools.registry import ToolRegistry


def _build_registry() -> ToolRegistry:
    tmp = pathlib.Path(tempfile.mkdtemp())
    return ToolRegistry(repo_dir=tmp, drive_root=tmp)


def test_core_surface_includes_user_message_and_media():
    assert "send_photo" in CORE_TOOL_NAMES
    assert "send_user_message" in CORE_TOOL_NAMES


def test_initial_tool_schemas_include_media_and_meta_tools():
    registry = _build_registry()
    names = {schema["function"]["name"] for schema in initial_tool_schemas(registry)}
    assert "send_photo" in names
    assert "list_available_tools" in names
    assert "enable_tools" in names


def test_non_core_listing_excludes_core_media_tools():
    registry = _build_registry()
    names = {entry["name"] for entry in list_non_core_tools(registry)}
    assert "send_photo" not in names
    assert "multi_model_review" in names


def test_loop_bootstraps_from_tool_policy():
    source = inspect.getsource(loop_mod)
    assert "initial_tool_schemas(tools)" in source
    assert "schemas(core_only=True)" not in source
