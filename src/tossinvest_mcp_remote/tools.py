"""Read-only MCP tool implementations backed by public TossInvest SDK APIs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from tossinvest import Account, CandleInterval, CurrencyCode, OrderListStatus

from .accounts import find_account_by_number
from .client_factory import ClientContextFactory

type AccountResolver = Callable[[str | int | None], str | int | None]
type AccountListCacheGetter = Callable[[], list[Account] | None]
type AccountListObserver = Callable[[list[Account]], None]


@dataclass(frozen=True, slots=True)
class TossInvestRemoteTools:
    """Read-only TossInvest operations exposed through MCP."""

    client_factory: ClientContextFactory
    account_resolver: AccountResolver | None = None
    account_list_cache_getter: AccountListCacheGetter | None = None
    account_list_observer: AccountListObserver | None = None

    def list_accounts(self) -> list[dict[str, object]]:
        """List accounts available to the authenticated OAuth client."""
        cached_accounts = self._cached_accounts()
        if cached_accounts is not None:
            return _dump_model_list(cached_accounts)
        with self.client_factory() as client:
            accounts = client.accounts.list_accounts()
            self._observe_accounts(accounts)
            return _dump_model_list(accounts)

    def find_account_by_number(self, account_no: str) -> dict[str, object]:
        """Return the account matching an official accountNo."""
        cached_accounts = self._cached_accounts()
        if cached_accounts is not None:
            return _dump_model(find_account_by_number(cached_accounts, account_no))
        with self.client_factory() as client:
            accounts = client.accounts.list_accounts()
            self._observe_accounts(accounts)
            account = find_account_by_number(accounts, account_no)
            return _dump_model(account)

    def get_stock(self, symbol: str) -> dict[str, object]:
        """Return one stock master record."""
        with self.client_factory() as client:
            return _dump_model(client.stocks.get_stock(symbol))

    def get_stocks(self, symbols: Sequence[str]) -> list[dict[str, object]]:
        """Return stock master records for one or more symbols."""
        with self.client_factory() as client:
            return _dump_model_list(client.stocks.get_stocks(symbols))

    def get_stock_warnings(self, symbol: str) -> list[dict[str, object]]:
        """Return trading warnings for a symbol."""
        with self.client_factory() as client:
            return _dump_model_list(client.stocks.get_stock_warnings(symbol))

    def get_orderbook(self, symbol: str) -> dict[str, object]:
        """Return the current orderbook for a symbol."""
        with self.client_factory() as client:
            return _dump_model(client.market_data.get_orderbook(symbol))

    def get_price(self, symbol: str) -> dict[str, object]:
        """Return the current price for one symbol."""
        with self.client_factory() as client:
            return _dump_model(client.market_data.get_price(symbol))

    def get_prices(self, symbols: Sequence[str]) -> list[dict[str, object]]:
        """Return current prices for one or more symbols."""
        with self.client_factory() as client:
            return _dump_model_list(client.market_data.get_prices(symbols))

    def get_trades(self, symbol: str, count: int | None = None) -> list[dict[str, object]]:
        """Return recent trades for a symbol."""
        with self.client_factory() as client:
            return _dump_model_list(client.market_data.get_trades(symbol, count=count))

    def get_price_limit(self, symbol: str) -> dict[str, object]:
        """Return upper and lower price limits for a symbol."""
        with self.client_factory() as client:
            return _dump_model(client.market_data.get_price_limit(symbol))

    def get_candles(
        self,
        symbol: str,
        *,
        interval: CandleInterval,
        count: int | None = None,
        before: str | None = None,
        adjusted: bool | None = None,
    ) -> dict[str, object]:
        """Return candle data for a symbol and interval."""
        with self.client_factory() as client:
            return _dump_model(
                client.market_data.get_candles(
                    symbol,
                    interval=interval,
                    count=count,
                    before=before,
                    adjusted=adjusted,
                )
            )

    def get_exchange_rate(
        self,
        *,
        base_currency: CurrencyCode,
        quote_currency: CurrencyCode,
        date_time: str | None = None,
    ) -> dict[str, object]:
        """Return an exchange rate between two supported currencies."""
        with self.client_factory() as client:
            return _dump_model(
                client.market_info.get_exchange_rate(
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    date_time=date_time,
                )
            )

    def get_kr_market_calendar(self, date: str | None = None) -> dict[str, object]:
        """Return Korean market calendar information."""
        with self.client_factory() as client:
            return _dump_model(client.market_info.get_kr_market_calendar(date=date))

    def get_us_market_calendar(self, date: str | None = None) -> dict[str, object]:
        """Return US market calendar information."""
        with self.client_factory() as client:
            return _dump_model(client.market_info.get_us_market_calendar(date=date))

    def get_holdings(
        self,
        symbol: str | None = None,
        account_seq: str | int | None = None,
    ) -> dict[str, object]:
        """Return holdings for the configured or overridden accountSeq."""
        account = self._account_for_tool(account_seq)
        with self.client_factory() as client:
            return _dump_model(client.assets.get_holdings(symbol=symbol, account=account))

    def list_orders(
        self,
        *,
        status: OrderListStatus = "OPEN",
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        account_seq: str | int | None = None,
    ) -> dict[str, object]:
        """List orders for the configured or overridden accountSeq."""
        account = self._account_for_tool(account_seq)
        with self.client_factory() as client:
            return _dump_model(
                client.orders.list_orders(
                    status=status,
                    symbol=symbol,
                    from_date=from_date,
                    to_date=to_date,
                    cursor=cursor,
                    limit=limit,
                    account=account,
                )
            )

    def get_order(self, order_id: str, account_seq: str | int | None = None) -> dict[str, object]:
        """Return one order by server order identifier."""
        account = self._account_for_tool(account_seq)
        with self.client_factory() as client:
            return _dump_model(client.orders.get_order(order_id, account=account))

    def get_buying_power(
        self,
        *,
        currency: CurrencyCode,
        account_seq: str | int | None = None,
    ) -> dict[str, object]:
        """Return cash buying power for the requested currency."""
        account = self._account_for_tool(account_seq)
        with self.client_factory() as client:
            return _dump_model(client.orders.get_buying_power(currency=currency, account=account))

    def get_sellable_quantity(
        self,
        *,
        symbol: str,
        account_seq: str | int | None = None,
    ) -> dict[str, object]:
        """Return the sellable quantity for a symbol."""
        account = self._account_for_tool(account_seq)
        with self.client_factory() as client:
            return _dump_model(client.orders.get_sellable_quantity(symbol=symbol, account=account))

    def get_commissions(self, account_seq: str | int | None = None) -> list[dict[str, object]]:
        """Return commission rules for the configured or overridden accountSeq."""
        account = self._account_for_tool(account_seq)
        with self.client_factory() as client:
            return _dump_model_list(client.orders.get_commissions(account=account))

    def _account_for_tool(self, account_seq: str | int | None) -> str | int | None:
        if self.account_resolver is None:
            return account_seq
        return self.account_resolver(account_seq)

    def _cached_accounts(self) -> list[Account] | None:
        if self.account_list_cache_getter is None:
            return None
        return self.account_list_cache_getter()

    def _observe_accounts(self, accounts: list[Account]) -> None:
        if self.account_list_observer is not None:
            self.account_list_observer(accounts)


def _dump_model(value: object) -> dict[str, object]:
    dumped = _dump_value(value)
    if not isinstance(dumped, dict):
        msg = "Expected a model-like SDK result."
        raise TypeError(msg)
    return cast(dict[str, object], dumped)


def _dump_model_list(value: object) -> list[dict[str, object]]:
    dumped = _dump_value(value)
    if not isinstance(dumped, list):
        msg = "Expected a list-like SDK result."
        raise TypeError(msg)
    return cast(list[dict[str, object]], dumped)


def _dump_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return cast(object, value.model_dump(by_alias=True, exclude_none=True))
    if isinstance(value, list | tuple):
        return [_dump_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _dump_value(item) for key, item in value.items()}
    return value
