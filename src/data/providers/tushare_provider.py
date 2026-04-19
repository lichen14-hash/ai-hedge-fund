"""Tushare Pro data provider for A-share and HK stock markets."""

import logging
import os
import time

import pandas as pd

from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    MarketType,
    Price,
    detect_market,
)

logger = logging.getLogger(__name__)

# Rate-limit delay (seconds) between Tushare API calls
_API_CALL_DELAY = 0.5


def _fmt_date(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' to Tushare 'YYYYMMDD' format."""
    return date_str.replace("-", "")


def _parse_date(date_str: str) -> str:
    """Convert Tushare 'YYYYMMDD' to 'YYYY-MM-DD' format."""
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def _safe_float(value) -> float | None:
    """Convert a value to float, returning None on failure."""
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> int:
    """Convert a value to int, returning 0 on failure."""
    try:
        if pd.isna(value):
            return 0
        return int(value)
    except (ValueError, TypeError):
        return 0


class TushareProvider:
    """Data provider that fetches A-share and HK stock data via Tushare Pro."""

    def __init__(self, token: str = None):
        """Initialize TushareProvider with API token.

        Args:
            token: Tushare Pro API token. If None, reads from TUSHARE_TOKEN env var.

        Raises:
            ValueError: If token is not provided and TUSHARE_TOKEN env var is not set.
            ImportError: If tushare package is not installed.
        """
        try:
            import tushare as ts
        except ImportError as e:
            raise ImportError("tushare package is required. Install with: poetry add tushare") from e

        self.token = token or os.getenv("TUSHARE_TOKEN")
        if not self.token:
            raise ValueError("TUSHARE_TOKEN not configured")

        self.pro = ts.pro_api(self.token)
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "daily",
        **kwargs,
    ) -> list[Price]:
        """Fetch OHLCV price data.

        Args:
            ticker: Stock ticker (e.g. '600519.SH', '0700.HK')
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            interval: 'daily' | '1min' | '5min' | '15min' | '30min' | '60min'

        Returns:
            List of Price objects.
        """
        market = detect_market(ticker)

        try:
            if market in (MarketType.CN_SH, MarketType.CN_SZ):
                df = self._get_a_share_prices(ticker, start_date, end_date, interval)
            elif market == MarketType.HK:
                df = self._get_hk_prices(ticker, start_date, end_date, interval)
            else:
                self.logger.warning("TushareProvider does not support US ticker: %s", ticker)
                return []
        except Exception as e:
            self.logger.warning("Failed to fetch prices for %s: %s", ticker, e)
            return []

        if df is None or df.empty:
            return []

        return self._df_to_prices(df, ticker)

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        """Fetch financial analysis indicators.

        Uses Tushare fina_indicator API to retrieve financial metrics.

        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'
            period: 'ttm' | 'annual' | 'quarterly'
            limit: Max number of records

        Returns:
            List of FinancialMetrics objects.
        """
        market = detect_market(ticker)
        if market not in (MarketType.CN_SH, MarketType.CN_SZ):
            self.logger.warning("Tushare financial metrics only support A-share tickers, got: %s", ticker)
            return []

        try:
            time.sleep(_API_CALL_DELAY)
            df = self.pro.fina_indicator(
                ts_code=ticker,
                end_date=_fmt_date(end_date),
                limit=limit,
            )
        except Exception as e:
            self.logger.warning("Failed to fetch financial metrics for %s: %s", ticker, e)
            return []

        if df is None or df.empty:
            return []

        return self._parse_financial_metrics(df, ticker, end_date, period, limit)

    def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int = 50,
    ) -> list[CompanyNews]:
        """Fetch company news.

        Tushare does not provide a direct company news API.
        Returns empty list to let other providers handle news.

        Args:
            ticker: Stock ticker
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            limit: Max number of news items

        Returns:
            Empty list (Tushare does not support company news API).
        """
        # Tushare does not have a direct company news API
        self.logger.debug("Tushare does not support company news API, returning empty list")
        return []

    def get_insider_trades(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int = 50,
    ) -> list[InsiderTrade]:
        """Fetch insider trade data.

        Uses Tushare stk_holdertrade API to retrieve shareholder trade data.

        Args:
            ticker: Stock ticker
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            limit: Max number of records

        Returns:
            List of InsiderTrade objects.
        """
        market = detect_market(ticker)
        if market not in (MarketType.CN_SH, MarketType.CN_SZ):
            self.logger.warning("Tushare insider trades only support A-share tickers, got: %s", ticker)
            return []

        try:
            time.sleep(_API_CALL_DELAY)
            df = self.pro.stk_holdertrade(
                ts_code=ticker,
                start_date=_fmt_date(start_date),
                end_date=_fmt_date(end_date),
                limit=limit,
            )
        except Exception as e:
            self.logger.warning("Failed to fetch insider trades for %s: %s", ticker, e)
            return []

        if df is None or df.empty:
            return []

        return self._parse_insider_trades(df, ticker, start_date, end_date, limit)

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Fetch total market capitalization.

        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'

        Returns:
            Market cap as float (in CNY), or None if unavailable.
        """
        market = detect_market(ticker)

        try:
            if market in (MarketType.CN_SH, MarketType.CN_SZ):
                return self._get_a_share_market_cap(ticker, end_date)
            elif market == MarketType.HK:
                return self._get_hk_market_cap(ticker, end_date)
            else:
                self.logger.warning("TushareProvider does not support US ticker: %s", ticker)
                return None
        except Exception as e:
            self.logger.warning("Failed to fetch market cap for %s: %s", ticker, e)
            return None

    def search_line_items(
        self,
        ticker: str,
        line_items: list[str],
        end_date: str,
        period: str = "annual",
        limit: int = 10,
    ) -> list[LineItem]:
        """Search for specific financial line items.

        Fetches income statement, balance sheet, and cash flow statement data
        from Tushare and extracts the requested items.

        Args:
            ticker: Stock ticker
            line_items: List of line item names to search for
            end_date: End date 'YYYY-MM-DD'
            period: 'annual' | 'quarterly'
            limit: Max number of records

        Returns:
            List of LineItem objects.
        """
        market = detect_market(ticker)
        if market not in (MarketType.CN_SH, MarketType.CN_SZ):
            self.logger.warning("Tushare line items only support A-share tickers, got: %s", ticker)
            return []

        # Map period to Tushare period parameter
        # Tushare uses: 'annual' for annual reports, 'quarterly' for quarterly
        # Actually Tushare income/balance sheet APIs don't have period param,
        # they return all reports, we filter by end_date

        try:
            # Fetch all three financial statements
            time.sleep(_API_CALL_DELAY)
            income_df = self.pro.income(ts_code=ticker, end_date=_fmt_date(end_date), limit=limit)
            time.sleep(_API_CALL_DELAY)
            balance_df = self.pro.balancesheet(ts_code=ticker, end_date=_fmt_date(end_date), limit=limit)
            time.sleep(_API_CALL_DELAY)
            cashflow_df = self.pro.cashflow(ts_code=ticker, end_date=_fmt_date(end_date), limit=limit)
        except Exception as e:
            self.logger.warning("Failed to fetch financial statements for %s: %s", ticker, e)
            return []

        return self._build_line_items(income_df, balance_df, cashflow_df, ticker, line_items, end_date, period, limit)

    # ------------------------------------------------------------------
    # Price helpers
    # ------------------------------------------------------------------

    def _get_a_share_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> pd.DataFrame | None:
        """Fetch A-share price data (daily or minute bars)."""
        if interval == "daily":
            time.sleep(_API_CALL_DELAY)
            df = self.pro.daily(
                ts_code=ticker,
                start_date=_fmt_date(start_date),
                end_date=_fmt_date(end_date),
            )
            if df is not None and not df.empty:
                # Rename columns to standard format
                df = df.rename(columns={
                    "trade_date": "time",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "vol": "volume",
                })
            return df

        # Minute bars
        freq_map = {
            "1min": "1min",
            "5min": "5min",
            "15min": "15min",
            "30min": "30min",
            "60min": "60min",
        }
        freq = freq_map.get(interval)
        if freq is None:
            self.logger.warning("Unsupported interval for A-share minute data: %s", interval)
            return None

        time.sleep(_API_CALL_DELAY)
        df = self.pro.stk_mins(ts_code=ticker, freq=freq)
        if df is not None and not df.empty:
            df = df.rename(columns={
                "trade_time": "time",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume",
            })
        return df

    def _get_hk_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> pd.DataFrame | None:
        """Fetch HK stock price data (daily or minute bars)."""
        if interval == "daily":
            time.sleep(_API_CALL_DELAY)
            df = self.pro.hk_daily(
                ts_code=ticker,
                start_date=_fmt_date(start_date),
                end_date=_fmt_date(end_date),
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "time",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "vol": "volume",
                })
            return df

        # Minute bars
        freq_map = {
            "1min": "1min",
            "5min": "5min",
            "15min": "15min",
            "30min": "30min",
            "60min": "60min",
        }
        freq = freq_map.get(interval)
        if freq is None:
            self.logger.warning("Unsupported interval for HK minute data: %s", interval)
            return None

        time.sleep(_API_CALL_DELAY)
        df = self.pro.hk_mins(ts_code=ticker, freq=freq)
        if df is not None and not df.empty:
            df = df.rename(columns={
                "trade_time": "time",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume",
            })
        return df

    @staticmethod
    def _df_to_prices(df: pd.DataFrame, ticker: str) -> list[Price]:
        """Convert a DataFrame with standardized columns to list[Price]."""
        prices: list[Price] = []
        for _, row in df.iterrows():
            try:
                # Parse date format
                time_val = row.get("time", "")
                if isinstance(time_val, str) and len(time_val) == 8 and time_val.isdigit():
                    time_str = _parse_date(time_val)
                else:
                    time_str = str(time_val)

                price = Price(
                    open=_safe_float(row.get("open")),
                    close=_safe_float(row.get("close")),
                    high=_safe_float(row.get("high")),
                    low=_safe_float(row.get("low")),
                    volume=_safe_int(row.get("volume")),
                    time=time_str,
                )
                # Skip rows with missing critical fields
                if price.open is None or price.close is None:
                    continue
                prices.append(price)
            except Exception:
                continue
        return prices

    # ------------------------------------------------------------------
    # Financial metrics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_financial_metrics(
        df: pd.DataFrame,
        ticker: str,
        end_date: str,
        period: str,
        limit: int,
    ) -> list[FinancialMetrics]:
        """Parse Tushare fina_indicator DataFrame into FinancialMetrics."""
        results: list[FinancialMetrics] = []

        for _, row in df.iterrows():
            if len(results) >= limit:
                break

            try:
                # Parse report date
                report_date = str(row.get("end_date", ""))
                if len(report_date) == 8:
                    report_date = _parse_date(report_date)

                # Filter by end_date
                if end_date and report_date > end_date:
                    continue

                metrics = FinancialMetrics(
                    ticker=ticker,
                    report_period=report_date,
                    period=period,
                    currency="CNY",
                    market_cap=_safe_float(row.get("total_mv")),  # total_mv is in万元
                    enterprise_value=None,
                    price_to_earnings_ratio=_safe_float(row.get("q_sales_yoy")),  # Using growth as proxy if needed
                    price_to_book_ratio=_safe_float(row.get("pb")),
                    price_to_sales_ratio=_safe_float(row.get("ps")),
                    enterprise_value_to_ebitda_ratio=None,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=None,
                    peg_ratio=None,
                    gross_margin=_safe_float(row.get("grossprofit_margin")),
                    operating_margin=_safe_float(row.get("op_yoy")),
                    net_margin=_safe_float(row.get("profit_dedt")),
                    return_on_equity=_safe_float(row.get("roe")),
                    return_on_assets=_safe_float(row.get("roa")),
                    return_on_invested_capital=_safe_float(row.get("roe_yearly")),
                    asset_turnover=_safe_float(row.get("assets_turn")),
                    inventory_turnover=_safe_float(row.get("inv_turn")),
                    receivables_turnover=_safe_float(row.get("ar_turn")),
                    days_sales_outstanding=_safe_float(row.get("days_ar_turn")),
                    operating_cycle=None,
                    working_capital_turnover=None,
                    current_ratio=_safe_float(row.get("current_ratio")),
                    quick_ratio=_safe_float(row.get("quick_ratio")),
                    cash_ratio=None,
                    operating_cash_flow_ratio=None,
                    debt_to_equity=_safe_float(row.get("debt_to_eqt")),
                    debt_to_assets=_safe_float(row.get("debt_to_assets")),
                    interest_coverage=_safe_float(row.get("int_cover")),
                    revenue_growth=_safe_float(row.get("q_sales_yoy")),
                    earnings_growth=_safe_float(row.get("q_profit_yoy")),
                    book_value_growth=None,
                    earnings_per_share_growth=None,
                    free_cash_flow_growth=None,
                    operating_income_growth=None,
                    ebitda_growth=None,
                    payout_ratio=_safe_float(row.get("div_cash_payable")),
                    earnings_per_share=_safe_float(row.get("eps")),
                    book_value_per_share=_safe_float(row.get("bps")),
                    free_cash_flow_per_share=None,
                )
                results.append(metrics)
            except Exception as e:
                logger.warning("Skipping financial metrics row for %s: %s", ticker, e)
                continue

        return results

    # ------------------------------------------------------------------
    # Insider trades helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_insider_trades(
        df: pd.DataFrame,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> list[InsiderTrade]:
        """Parse Tushare stk_holdertrade DataFrame into InsiderTrade."""
        results: list[InsiderTrade] = []
        count = 0

        for _, row in df.iterrows():
            try:
                # Parse dates
                ann_date = str(row.get("ann_date", ""))
                if len(ann_date) == 8:
                    filing_date = _parse_date(ann_date)
                else:
                    filing_date = ann_date

                # Date range filter
                if start_date and filing_date < start_date:
                    continue
                if end_date and filing_date > end_date:
                    continue

                # Parse transaction date (begin_date in Tushare)
                begin_date = str(row.get("begin_date", ""))
                if len(begin_date) == 8:
                    transaction_date = _parse_date(begin_date)
                else:
                    transaction_date = begin_date if begin_date else filing_date

                # Determine if it's a buy or sell
                change_reason = str(row.get("change_reason", ""))
                in_de = str(row.get("in_de", ""))  # IN for increase, DE for decrease

                # Calculate transaction shares (positive for buy, negative for sell)
                hold_change_vol = _safe_float(row.get("hold_change_vol", 0)) or 0
                if in_de == "DE":
                    hold_change_vol = -abs(hold_change_vol)

                trade = InsiderTrade(
                    ticker=ticker,
                    issuer=None,
                    name=str(row.get("holder_name", "")) or None,
                    title=str(row.get("holder_type", "")) or None,
                    is_board_director=None,
                    transaction_date=transaction_date or None,
                    transaction_shares=hold_change_vol if hold_change_vol != 0 else None,
                    transaction_price_per_share=_safe_float(row.get("avg_price")),
                    transaction_value=None,  # Can be calculated: hold_change_vol * avg_price
                    shares_owned_before_transaction=None,
                    shares_owned_after_transaction=_safe_float(row.get("hold_vol_after")),
                    security_title=None,
                    filing_date=filing_date,
                )
                results.append(trade)
                count += 1
                if count >= limit:
                    break
            except Exception as e:
                logger.warning("Skipping insider trade row for %s: %s", ticker, e)
                continue

        return results

    # ------------------------------------------------------------------
    # Market cap helpers
    # ------------------------------------------------------------------

    def _get_a_share_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Fetch A-share total market cap via daily_basic API.

        Note: Tushare daily_basic returns total_mv in 万元 (10k CNY).
        We convert to CNY by multiplying by 10,000.
        """
        try:
            time.sleep(_API_CALL_DELAY)
            df = self.pro.daily_basic(
                ts_code=ticker,
                trade_date=_fmt_date(end_date),
                fields="ts_code,trade_date,total_mv",
            )
        except Exception as e:
            self.logger.warning("Failed to fetch A-share market cap for %s: %s", ticker, e)
            return None

        if df is None or df.empty:
            return None

        total_mv = _safe_float(df.iloc[0].get("total_mv"))
        if total_mv is not None:
            # Convert from 万元 to CNY
            return total_mv * 10000
        return None

    def _get_hk_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Fetch HK stock total market cap.

        Tushare does not have a direct HK market cap API.
        Returns None for now.
        """
        # Tushare does not provide HK market cap directly
        # Could potentially calculate from HK daily data if needed
        self.logger.debug("Tushare HK market cap not directly available")
        return None

    # ------------------------------------------------------------------
    # Line items helpers
    # ------------------------------------------------------------------

    # Mapping from English line-item names to Tushare column names
    _LINE_ITEM_MAP: dict[str, str] = {
        # Income statement
        "revenue": "revenue",
        "total_revenue": "total_revenue",
        "cost_of_revenue": "oper_cost",
        "operating_income": "operate_profit",
        "net_income": "n_income",
        "earnings_per_share": "eps",
        "diluted_eps": "diluted_eps",
        # Balance sheet
        "total_assets": "total_assets",
        "total_liabilities": "total_liab",
        "total_equity": "total_hldr_eqy_exc_min_int",
        "cash_and_equivalents": "money_cap",
        "accounts_receivable": "accounts_receiv",
        "inventory": "inventories",
        "current_assets": "total_cur_assets",
        "current_liabilities": "total_cur_liab",
        "total_debt": "total_liab",
        # Cash flow statement
        "operating_cash_flow": "n_cashflow_act",
        "free_cash_flow": "free_cashflow",
        "capital_expenditure": "c_fix_assets",
    }

    def _build_line_items(
        self,
        income_df: pd.DataFrame | None,
        balance_df: pd.DataFrame | None,
        cashflow_df: pd.DataFrame | None,
        ticker: str,
        line_items: list[str],
        end_date: str,
        period: str,
        limit: int,
    ) -> list[LineItem]:
        """Build LineItem objects from the three financial statement DataFrames."""
        # Merge all statements by report date
        merged: dict[str, dict] = {}

        for df in (income_df, balance_df, cashflow_df):
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                # Tushare uses 'end_date' for report date
                rd = str(row.get("end_date", ""))
                if len(rd) == 8:
                    rd = _parse_date(rd)
                else:
                    rd = rd[:10]
                if rd not in merged:
                    merged[rd] = {}
                for col in row.index:
                    merged[rd][col] = row[col]

        sorted_dates = sorted(merged.keys(), reverse=True)
        results: list[LineItem] = []

        for rd in sorted_dates:
            if len(results) >= limit:
                break
            if end_date and rd > end_date:
                continue

            data = merged[rd]
            item_data: dict = {
                "ticker": ticker,
                "report_period": rd,
                "period": period,
                "currency": "CNY",
            }

            for item_name in line_items:
                ts_col = self._LINE_ITEM_MAP.get(item_name)
                if ts_col and ts_col in data:
                    item_data[item_name] = _safe_float(data[ts_col])

            try:
                results.append(LineItem(**item_data))
            except Exception as e:
                logger.warning("Skipping line item row for %s: %s", ticker, e)
                continue

        return results
