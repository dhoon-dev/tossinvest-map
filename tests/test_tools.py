from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from types import TracebackType
from typing import cast

from tossinvest import (
    Account,
    BuyingPowerResponse,
    HoldingsOverview,
    PaginatedOrderResponse,
    PriceResponse,
)

from tossinvest_mcp_remote.client_factory import ClientContextFactory
from tossinvest_mcp_remote.config import TossInvestRemoteServerConfig
from tossinvest_mcp_remote.tools import TossInvestRemoteTools


class _Accounts:
    calls = 0

    def list_accounts(self) -> list[Account]:
        self.calls += 1
        return [
            Account.model_validate(
                {"accountNo": "12345678901", "accountSeq": 1, "accountType": "BROKERAGE"}
            )
        ]


class _MarketData:
    def get_price(self, symbol: str) -> PriceResponse:
        return PriceResponse.model_validate(
            {"symbol": symbol, "lastPrice": "72000", "currency": "KRW"}
        )

    def get_prices(self, symbols: Sequence[str]) -> list[PriceResponse]:
        return [
            PriceResponse.model_validate(
                {"symbol": symbol, "lastPrice": "72000", "currency": "KRW"}
            )
            for symbol in symbols
        ]


class _Assets:
    account: str | int | None = None

    def get_holdings(
        self,
        *,
        symbol: str | None = None,
        account: str | int | None = None,
    ) -> HoldingsOverview:
        self.account = account
        assert symbol is None
        return HoldingsOverview.model_validate(
            {
                "totalPurchaseAmount": {"krw": "1000"},
                "marketValue": {"amount": {"krw": "1100"}, "amountAfterCost": {"krw": "1090"}},
                "profitLoss": {
                    "amount": {"krw": "100"},
                    "amountAfterCost": {"krw": "90"},
                    "rate": "10",
                    "rateAfterCost": "9",
                },
                "dailyProfitLoss": {"amount": {"krw": "10"}, "rate": "1"},
                "items": [],
            }
        )


class _Orders:
    account: str | int | None = None
    listed_status: str | None = None

    def list_orders(
        self,
        *,
        status: str = "OPEN",
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        account: str | int | None = None,
    ) -> PaginatedOrderResponse:
        assert symbol is None
        assert from_date is None
        assert to_date is None
        assert cursor is None
        assert limit is None
        self.account = account
        self.listed_status = status
        return PaginatedOrderResponse.model_validate(
            {"orders": [], "nextCursor": None, "hasNext": False}
        )

    def get_buying_power(
        self,
        *,
        currency: str,
        account: str | int | None = None,
    ) -> BuyingPowerResponse:
        self.account = account
        return BuyingPowerResponse.model_validate(
            {"currency": currency, "cashBuyingPower": "100000"}
        )


class _FakeClient:
    def __init__(self) -> None:
        self.accounts = _Accounts()
        self.market_data = _MarketData()
        self.assets = _Assets()
        self.orders = _Orders()
        self.closed = False


class _FakeClientContext(AbstractContextManager[_FakeClient]):
    def __init__(self, client: _FakeClient) -> None:
        self.client = client

    def __enter__(self) -> _FakeClient:
        return self.client

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.client.closed = True


def test_tools_dump_sdk_models_with_official_aliases() -> None:
    client = _FakeClient()
    tools = TossInvestRemoteTools(cast(ClientContextFactory, lambda: _FakeClientContext(client)))

    account_result = tools.list_accounts()
    matched_account = tools.find_account_by_number("12345678901")
    price_result = tools.get_price("005930")
    prices_result = tools.get_prices(["005930", "000660"])

    assert account_result == [
        {"accountNo": "12345678901", "accountSeq": 1, "accountType": "BROKERAGE"}
    ]
    assert matched_account == {
        "accountNo": "12345678901",
        "accountSeq": 1,
        "accountType": "BROKERAGE",
    }
    assert price_result == {"symbol": "005930", "lastPrice": "72000", "currency": "KRW"}
    assert prices_result[1]["symbol"] == "000660"
    assert client.closed is True


def test_market_data_tool_does_not_discover_accounts() -> None:
    client = _FakeClient()
    tools = TossInvestRemoteTools(cast(ClientContextFactory, lambda: _FakeClientContext(client)))

    assert tools.get_price("005930")["lastPrice"] == "72000"

    assert client.accounts.calls == 0


def test_account_scoped_tools_forward_account_override() -> None:
    client = _FakeClient()
    tools = TossInvestRemoteTools(cast(ClientContextFactory, lambda: _FakeClientContext(client)))

    result = tools.get_buying_power(currency="KRW", account_seq="7")

    assert result == {"currency": "KRW", "cashBuyingPower": "100000"}
    assert client.orders.account == "7"


def test_list_orders_defaults_to_open_status() -> None:
    client = _FakeClient()
    tools = TossInvestRemoteTools(cast(ClientContextFactory, lambda: _FakeClientContext(client)))

    result = tools.list_orders(account_seq="7")

    assert result == {"orders": [], "hasNext": False}
    assert client.orders.listed_status == "OPEN"
    assert client.orders.account == "7"


def test_tools_reuse_account_list_cache_for_account_resolution() -> None:
    client = _FakeClient()
    config = TossInvestRemoteServerConfig(
        client_id="client-id",
        client_secret="client-secret",
        account_number="12345678901",
    )
    tools = TossInvestRemoteTools(
        cast(ClientContextFactory, lambda: _FakeClientContext(client)),
        account_resolver=config.account_seq_for_tool,
        account_list_cache_getter=config.cached_account_list,
        account_list_observer=config.cache_account_list,
    )

    assert tools.list_accounts()[0]["accountSeq"] == 1
    assert tools.get_holdings()["items"] == []

    assert client.accounts.calls == 1
    assert client.assets.account == 1
