from __future__ import annotations

from typing import cast

import pytest

from tossinvest_mcp_remote.config import TossInvestRemoteServerConfig
from tossinvest_mcp_remote.errors import UnsupportedLiveOrderModeError
from tossinvest_mcp_remote.server import SERVER_INSTRUCTIONS, create_server


def _property_enum(schema: dict[str, object], property_name: str) -> list[str]:
    properties = cast(dict[str, object], schema["properties"])
    enum = _schema_enum(schema, cast(dict[str, object], properties[property_name]))
    if enum is None:
        msg = f"{property_name} does not expose an enum."
        raise AssertionError(msg)
    return enum


def _schema_enum(schema: dict[str, object], property_schema: dict[str, object]) -> list[str] | None:
    enum = property_schema.get("enum")
    if isinstance(enum, list):
        return cast(list[str], enum)
    ref = property_schema.get("$ref")
    if isinstance(ref, str):
        defs = cast(dict[str, object], schema["$defs"])
        return _schema_enum(schema, cast(dict[str, object], defs[ref.removeprefix("#/$defs/")]))
    for key in ("anyOf", "oneOf"):
        options = property_schema.get(key)
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    nested_enum = _schema_enum(schema, cast(dict[str, object], option))
                    if nested_enum is not None:
                        return nested_enum
    return None


async def test_create_server_registers_read_only_tools_only() -> None:
    pytest.importorskip("mcp.server.fastmcp")

    server = create_server(TossInvestRemoteServerConfig("client-id", "client-secret"))
    tool_names = {tool.name for tool in await server.list_tools()}

    assert "list_accounts" in tool_names
    assert "find_account_by_number" in tool_names
    assert "get_price" in tool_names
    assert "get_buying_power" in tool_names
    assert {"create_order", "modify_order", "cancel_order"}.isdisjoint(tool_names)


async def test_account_scoped_tool_schema_uses_account_seq() -> None:
    pytest.importorskip("mcp.server.fastmcp")

    server = create_server(TossInvestRemoteServerConfig("client-id", "client-secret"))
    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["get_buying_power"].inputSchema

    assert "account_seq" in schema["properties"]
    assert "account" not in schema["properties"]
    assert "accountSeq" in schema["properties"]["account_seq"]["description"]
    assert "accountNo" in schema["properties"]["account_seq"]["description"]


async def test_read_only_tool_schemas_expose_sdk_enums() -> None:
    pytest.importorskip("mcp.server.fastmcp")

    server = create_server(TossInvestRemoteServerConfig("client-id", "client-secret"))
    tools = {tool.name: tool for tool in await server.list_tools()}

    list_orders_schema = tools["list_orders"].inputSchema
    assert list_orders_schema["properties"]["status"]["default"] == "OPEN"
    assert "status" not in list_orders_schema.get("required", [])
    assert _property_enum(list_orders_schema, "status") == ["OPEN", "CLOSED"]
    assert _property_enum(tools["get_candles"].inputSchema, "interval") == ["1m", "1d"]
    assert _property_enum(tools["get_exchange_rate"].inputSchema, "base_currency") == [
        "KRW",
        "USD",
    ]
    assert _property_enum(tools["get_exchange_rate"].inputSchema, "quote_currency") == [
        "KRW",
        "USD",
    ]
    assert _property_enum(tools["get_buying_power"].inputSchema, "currency") == ["KRW", "USD"]


def test_live_order_tools_are_not_implemented() -> None:
    pytest.importorskip("mcp.server.fastmcp")

    with pytest.raises(UnsupportedLiveOrderModeError):
        create_server(
            TossInvestRemoteServerConfig(
                "client-id",
                "client-secret",
                enable_live_orders=True,
            )
        )


def test_server_instructions_are_self_contained() -> None:
    assert len(SERVER_INSTRUCTIONS) <= 512
    assert "read-only" in SERVER_INSTRUCTIONS
    assert "investment advice" in SERVER_INSTRUCTIONS
    assert "accountSeq" in SERVER_INSTRUCTIONS
