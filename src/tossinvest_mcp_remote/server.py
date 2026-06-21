"""Shared MCP server creation and tool registration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations
from pydantic import Field
from tossinvest import (
    CandleInterval,
    CurrencyCode,
    OrderListStatus,
    OrderSide,
    OrderTimeInForce,
    OrderType,
)

from .client_factory import ClientContextFactory
from .config import TossInvestRemoteServerConfig
from .errors import TossInvestMCPRemoteConfigError
from .tools import TossInvestRemoteTools

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken, TokenVerifier
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.fastmcp import FastMCP

ACCOUNT_SEQ_DESCRIPTION = (
    "Optional accountSeq override. Omit when the server was started with --account or "
    "--account-seq. Use accountSeq as account_seq for overrides, not accountNo."
)
ACCOUNT_NO_DESCRIPTION = (
    "Official accountNo from list_accounts. Resolving accountNo calls the ACCOUNT-rate-limited "
    "accounts endpoint."
)
SERVER_INSTRUCTIONS = (
    "This server exposes read-only TossInvest account and market data tools by default. "
    "Live order tools are registered only when explicitly enabled. "
    "It does not provide investment advice. Account-scoped tools use configured accountSeq "
    "unless account_seq is explicitly supplied. Avoid unnecessary account discovery because "
    "account APIs are rate-limited."
)
READ_ONLY_TOOL_ANNOTATIONS = ToolAnnotations(readOnlyHint=True)
LIVE_ORDER_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


def create_server(
    config: TossInvestRemoteServerConfig,
    *,
    client_factory: ClientContextFactory | None = None,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastMCP:
    """Create a TossInvest MCP server."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    if (
        config.enable_live_orders
        and not config.allow_stdio_live_orders
        and not config.live_order_required_scopes
    ):
        raise TossInvestMCPRemoteConfigError(
            "Live order tools require at least one --live-order-required-scope "
            "or --allow-stdio-live-orders."
        )

    tools = TossInvestRemoteTools(
        client_factory or config.create_client,
        account_resolver=config.account_seq_for_tool,
        account_list_cache_getter=config.cached_account_list,
        account_list_observer=config.cache_account_list,
    )
    server = FastMCP(
        name="TossInvest MCP Remote",
        instructions=SERVER_INSTRUCTIONS,
        stateless_http=True,
        auth=auth,
        token_verifier=token_verifier,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    _register_account_tools(server, tools)
    _register_stock_tools(server, tools)
    _register_market_data_tools(server, tools)
    _register_market_info_tools(server, tools)
    _register_account_scoped_tools(server, tools)
    if config.enable_live_orders:
        _register_live_order_tools(
            server,
            tools,
            required_scopes=config.live_order_required_scopes,
            allow_local_live_orders=config.allow_stdio_live_orders,
        )
    return server


def _register_account_tools(server: FastMCP, tools: TossInvestRemoteTools) -> None:
    """Register account lookup tools."""
    read_only_annotations = READ_ONLY_TOOL_ANNOTATIONS

    @server.tool(annotations=read_only_annotations)
    def list_accounts() -> list[dict[str, object]]:
        """List accounts only when account discovery is needed."""
        return tools.list_accounts()

    @server.tool(annotations=read_only_annotations)
    def find_account_by_number(
        account_no: str = Field(description=ACCOUNT_NO_DESCRIPTION),
    ) -> dict[str, object]:
        """Return the account matching accountNo, including its accountSeq."""
        return tools.find_account_by_number(account_no)


def _register_stock_tools(server: FastMCP, tools: TossInvestRemoteTools) -> None:
    """Register stock information tools."""
    read_only_annotations = READ_ONLY_TOOL_ANNOTATIONS

    @server.tool(annotations=read_only_annotations)
    def get_stock(symbol: str) -> dict[str, object]:
        """Return one stock master record."""
        return tools.get_stock(symbol)

    @server.tool(annotations=read_only_annotations)
    def get_stocks(symbols: list[str]) -> list[dict[str, object]]:
        """Return stock master records for one or more symbols."""
        return tools.get_stocks(symbols)

    @server.tool(annotations=read_only_annotations)
    def get_stock_warnings(symbol: str) -> list[dict[str, object]]:
        """Return trading warnings for a symbol."""
        return tools.get_stock_warnings(symbol)


def _register_market_data_tools(server: FastMCP, tools: TossInvestRemoteTools) -> None:
    """Register market data tools."""
    read_only_annotations = READ_ONLY_TOOL_ANNOTATIONS

    @server.tool(annotations=read_only_annotations)
    def get_orderbook(symbol: str) -> dict[str, object]:
        """Return the current orderbook for a symbol."""
        return tools.get_orderbook(symbol)

    @server.tool(annotations=read_only_annotations)
    def get_price(symbol: str) -> dict[str, object]:
        """Return the current price for one symbol."""
        return tools.get_price(symbol)

    @server.tool(annotations=read_only_annotations)
    def get_prices(symbols: list[str]) -> list[dict[str, object]]:
        """Return current prices for one or more symbols."""
        return tools.get_prices(symbols)

    @server.tool(annotations=read_only_annotations)
    def get_trades(symbol: str, count: int | None = None) -> list[dict[str, object]]:
        """Return recent trades for a symbol."""
        return tools.get_trades(symbol, count=count)

    @server.tool(annotations=read_only_annotations)
    def get_price_limit(symbol: str) -> dict[str, object]:
        """Return upper and lower price limits for a symbol."""
        return tools.get_price_limit(symbol)

    @server.tool(annotations=read_only_annotations)
    def get_candles(
        symbol: str,
        interval: CandleInterval,
        *,
        count: int | None = None,
        before: str | None = None,
        adjusted: bool | None = None,
    ) -> dict[str, object]:
        """Return candle data for a symbol and interval."""
        return tools.get_candles(
            symbol,
            interval=interval,
            count=count,
            before=before,
            adjusted=adjusted,
        )


def _register_market_info_tools(server: FastMCP, tools: TossInvestRemoteTools) -> None:
    """Register market information tools."""
    read_only_annotations = READ_ONLY_TOOL_ANNOTATIONS

    @server.tool(annotations=read_only_annotations)
    def get_exchange_rate(
        base_currency: CurrencyCode,
        quote_currency: CurrencyCode,
        date_time: str | None = None,
    ) -> dict[str, object]:
        """Return an exchange rate between two supported currencies."""
        return tools.get_exchange_rate(
            base_currency=base_currency,
            quote_currency=quote_currency,
            date_time=date_time,
        )

    @server.tool(annotations=read_only_annotations)
    def get_kr_market_calendar(date: str | None = None) -> dict[str, object]:
        """Return Korean market calendar information."""
        return tools.get_kr_market_calendar(date=date)

    @server.tool(annotations=read_only_annotations)
    def get_us_market_calendar(date: str | None = None) -> dict[str, object]:
        """Return US market calendar information."""
        return tools.get_us_market_calendar(date=date)


def _register_account_scoped_tools(server: FastMCP, tools: TossInvestRemoteTools) -> None:
    """Register read-only account-scoped tools."""
    read_only_annotations = READ_ONLY_TOOL_ANNOTATIONS

    @server.tool(annotations=read_only_annotations)
    def get_holdings(
        symbol: str | None = None,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Return holdings using the configured default accountSeq or an account_seq override."""
        return tools.get_holdings(symbol=symbol, account_seq=account_seq)

    @server.tool(annotations=read_only_annotations)
    def list_orders(
        status: OrderListStatus = "OPEN",
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """List orders using the configured default accountSeq or an account_seq override."""
        return tools.list_orders(
            status=status,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            cursor=cursor,
            limit=limit,
            account_seq=account_seq,
        )

    @server.tool(annotations=read_only_annotations)
    def get_order(
        order_id: str,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Return one order using the configured default accountSeq or an account_seq override."""
        return tools.get_order(order_id, account_seq=account_seq)

    @server.tool(annotations=read_only_annotations)
    def get_buying_power(
        currency: CurrencyCode,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Return cash buying power using the configured default accountSeq or an override."""
        return tools.get_buying_power(currency=currency, account_seq=account_seq)

    @server.tool(annotations=read_only_annotations)
    def get_sellable_quantity(
        symbol: str,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Return sellable quantity using the configured default accountSeq or an override."""
        return tools.get_sellable_quantity(symbol=symbol, account_seq=account_seq)

    @server.tool(annotations=read_only_annotations)
    def get_commissions(
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> list[dict[str, object]]:
        """Return commissions using the configured default accountSeq or an account_seq override."""
        return tools.get_commissions(account_seq=account_seq)


def _register_live_order_tools(
    server: FastMCP,
    tools: TossInvestRemoteTools,
    *,
    required_scopes: Sequence[str],
    allow_local_live_orders: bool,
) -> None:
    """Register live order tools that execute immediately after authorization."""

    @server.tool(annotations=LIVE_ORDER_TOOL_ANNOTATIONS)
    def create_order(
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        *,
        quantity: str | None = None,
        order_amount: str | None = None,
        price: str | None = None,
        time_in_force: OrderTimeInForce | None = None,
        client_order_id: str | None = None,
        confirm_high_value_order: bool | None = None,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Submit a live order using the configured default accountSeq or an override."""
        _authorize_live_order(required_scopes, allow_local_live_orders=allow_local_live_orders)
        return tools.create_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            order_amount=order_amount,
            price=price,
            time_in_force=time_in_force,
            client_order_id=client_order_id,
            confirm_high_value_order=confirm_high_value_order,
            account_seq=account_seq,
        )

    @server.tool(annotations=LIVE_ORDER_TOOL_ANNOTATIONS)
    def modify_order(
        order_id: str,
        order_type: OrderType,
        *,
        quantity: str | None = None,
        price: str | None = None,
        confirm_high_value_order: bool | None = None,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Modify a live order using the configured default accountSeq or an override."""
        _authorize_live_order(required_scopes, allow_local_live_orders=allow_local_live_orders)
        return tools.modify_order(
            order_id,
            order_type=order_type,
            quantity=quantity,
            price=price,
            confirm_high_value_order=confirm_high_value_order,
            account_seq=account_seq,
        )

    @server.tool(annotations=LIVE_ORDER_TOOL_ANNOTATIONS)
    def cancel_order(
        order_id: str,
        account_seq: str | None = Field(default=None, description=ACCOUNT_SEQ_DESCRIPTION),
    ) -> dict[str, object]:
        """Cancel a live order using the configured default accountSeq or an override."""
        _authorize_live_order(required_scopes, allow_local_live_orders=allow_local_live_orders)
        return tools.cancel_order(order_id, account_seq=account_seq)


def _authorize_live_order(
    required_scopes: Sequence[str],
    *,
    allow_local_live_orders: bool,
) -> str:
    """Authorize one live order tool call."""
    if allow_local_live_orders:
        return "local-stdio"
    access_token = _require_oauth_scopes(required_scopes)
    return _access_token_authorization_key(access_token)


def _require_oauth_scopes(required_scopes: Sequence[str]) -> AccessToken:
    """Require the current OAuth access token to contain every configured scope."""
    access_token = get_access_token()
    if access_token is None:
        msg = "Live order tools require an OAuth access token."
        raise PermissionError(msg)
    granted_scopes = set(access_token.scopes)
    missing_scopes = [scope for scope in required_scopes if scope not in granted_scopes]
    if missing_scopes:
        msg = "Live order tools require OAuth scope(s): " + ", ".join(missing_scopes)
        raise PermissionError(msg)
    return access_token


def _access_token_authorization_key(access_token: AccessToken) -> str:
    subject = access_token.subject or ""
    resource = access_token.resource or ""
    return f"oauth:{access_token.client_id}:{subject}:{resource}"
