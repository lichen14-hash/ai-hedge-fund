"""AKShare data provider for A-share and HK stock markets."""

import logging
import time
from json import JSONDecodeError

import akshare as ak
import pandas as pd
from http.client import RemoteDisconnected
from requests.exceptions import ConnectionError, ReadTimeout

from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    MarketType,
    Price,
    detect_market,
    normalize_ticker,
)

logger = logging.getLogger(__name__)




def _fmt_date(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' to AKShare 'YYYYMMDD' format."""
    return date_str.replace("-", "")


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


def _parse_chinese_quantity(s: str) -> float | None:
    """Parse a Chinese quantity string like '增持4.16万', '5.82亿' into a float.

    Supports: 万 (10^4), 亿 (10^8).
    """
    try:
        s = str(s).strip()
        if not s:
            return None
        # Remove leading Chinese action words (增持/减持)
        import re
        s = re.sub(r"^[增减]持", "", s)
        if "亿" in s:
            return float(s.replace("亿", "")) * 1e8
        elif "万" in s:
            return float(s.replace("万", "")) * 1e4
        else:
            return float(s)
    except (ValueError, TypeError):
        return None


class AKShareProvider:
    """Data provider that fetches A-share and HK stock data via AKShare."""

    _MAX_RETRIES = 3
    _BASE_DELAY = 3  # Base delay in seconds between API calls

    def _call_with_retry(self, func, *args, description="", **kwargs):
        """带指数退避的重试包装器。

        对 AKShare API 调用进行重试，遇到 JSONDecodeError、ConnectionError、
        RemoteDisconnected、ReadTimeout 等临时性错误时自动重试，最多重试
        ``_MAX_RETRIES`` 次，每次重试间隔按指数退避递增。

        Args:
            func: 要调用的 AKShare API 函数
            *args: 位置参数，传递给 func
            description: 调用描述，用于日志输出
            **kwargs: 关键字参数，传递给 func

        Returns:
            func 的返回值

        Raises:
            最后一次重试失败的异常
        """
        last_exception = None
        for attempt in range(self._MAX_RETRIES):
            try:
                if attempt > 0:
                    delay = self._BASE_DELAY * (2 ** (attempt - 1))  # 3s, 6s
                    logger.info(
                        "Retry %d/%d for %s, waiting %ds...",
                        attempt, self._MAX_RETRIES, description, delay,
                    )
                    time.sleep(delay)
                else:
                    time.sleep(self._BASE_DELAY)  # 首次调用也等待基础延迟

                result = func(*args, **kwargs)
                return result
            except (JSONDecodeError, ConnectionError, RemoteDisconnected, ReadTimeout) as e:
                last_exception = e
                error_name = type(e).__name__
                logger.warning(
                    "Attempt %d/%d failed for %s: %s: %s",
                    attempt + 1, self._MAX_RETRIES, description, error_name, e,
                )
                continue
            except Exception as e:
                # 对于未预期的异常也进行重试（AKShare 可能抛出各种运行时错误）
                last_exception = e
                error_name = type(e).__name__
                logger.warning(
                    "Attempt %d/%d failed for %s: %s: %s",
                    attempt + 1, self._MAX_RETRIES, description, error_name, e,
                )
                continue

        logger.error("All %d attempts failed for %s", self._MAX_RETRIES, description)
        raise last_exception

    # ------------------------------------------------------------------
    # A-share / HK price column mappings (AKShare returns Chinese headers)
    # ------------------------------------------------------------------
    _A_DAILY_COLS = {
        "日期": "time",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    _A_MIN_COLS = {
        "时间": "time",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    _HK_DAILY_COLS = {
        "日期": "time",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    _HK_MIN_COLS = {
        "时间": "time",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }

    # Interval string -> AKShare minute-period string
    _MIN_INTERVAL_MAP: dict[str, str] = {
        "1min": "1",
        "5min": "5",
        "15min": "15",
        "30min": "30",
        "60min": "60",
    }

    # Mapping from English line-item names to AKShare Chinese column names
    # across the three financial statements (利润表/资产负债表/现金流量表).
    _LINE_ITEM_MAP: dict[str, str] = {
        # Income statement
        "revenue": "营业收入",
        "total_revenue": "营业总收入",
        "cost_of_revenue": "营业成本",
        "operating_income": "营业利润",
        "net_income": "净利润",
        "earnings_per_share": "基本每股收益",
        "diluted_eps": "稀释每股收益",
        # Balance sheet
        "total_assets": "总资产",
        "total_liabilities": "总负债",
        "total_equity": "所有者权益(或股东权益)合计",
        "cash_and_equivalents": "货币资金",
        "accounts_receivable": "应收账款",
        "inventory": "存货",
        "current_assets": "流动资产合计",
        "current_liabilities": "流动负债合计",
        "total_debt": "负债合计",
        # Cash flow statement
        "operating_cash_flow": "经营活动产生的现金流量",
        "free_cash_flow": "自由现金流量",
        "capital_expenditure": "资本开支",
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "daily",
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
        raw_ticker = normalize_ticker(ticker, target="akshare")

        try:
            if market in (MarketType.CN_SH, MarketType.CN_SZ):
                df = self._get_a_share_prices(raw_ticker, start_date, end_date, interval)
            elif market == MarketType.HK:
                df = self._get_hk_prices(raw_ticker, start_date, end_date, interval)
            else:
                logger.warning("AKShareProvider does not support US ticker: %s", ticker)
                return []
        except Exception as e:
            logger.warning("Failed to fetch prices for %s: %s", ticker, e)
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

        Uses ``ak.stock_financial_report_sina`` to retrieve the income statement
        and balance sheet, then derives common financial metrics.

        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'
            period: 'ttm' | 'annual' | 'quarterly'
            limit: Max number of records

        Returns:
            List of FinancialMetrics objects (fields not available via AKShare set to None).
        """
        market = detect_market(ticker)
        if market not in (MarketType.CN_SH, MarketType.CN_SZ):
            logger.warning("AKShare financial metrics only support A-share tickers, got: %s", ticker)
            return []

        raw_ticker = normalize_ticker(ticker, target="akshare")

        # Fetch income statement and balance sheet
        income_df = self._fetch_financial_report(raw_ticker, "利润表")
        balance_df = self._fetch_financial_report(raw_ticker, "资产负债表")

        if (income_df is None or income_df.empty) and (balance_df is None or balance_df.empty):
            return []

        return self._build_financial_metrics(income_df, balance_df, ticker, end_date, period, limit)

    def get_company_news(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int = 50,
    ) -> list[CompanyNews]:
        """Fetch company news.

        Args:
            ticker: Stock ticker
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            limit: Max number of news items

        Returns:
            List of CompanyNews objects.
        """
        market = detect_market(ticker)
        if market not in (MarketType.CN_SH, MarketType.CN_SZ):
            logger.warning("AKShare company news only supports A-share tickers, got: %s", ticker)
            return []

        raw_ticker = normalize_ticker(ticker, target="akshare")

        try:
            df = self._call_with_retry(
                ak.stock_news_em,
                symbol=raw_ticker,
                description=f"company news for {raw_ticker}",
            )
        except Exception as e:
            logger.warning("Failed to fetch company news for %s: %s", ticker, e)
            return []

        if df is None or df.empty:
            return []

        return self._parse_company_news(df, ticker, start_date, end_date, limit)

    def get_insider_trades(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int = 50,
    ) -> list[InsiderTrade]:
        """Fetch insider trade data.

        For A-shares this attempts to get shareholder position change data via
        ``ak.stock_shareholder_change_ths``.  Falls back to empty list if unavailable.

        Args:
            ticker: Stock ticker
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            limit: Max number of records

        Returns:
            List of InsiderTrade objects (may be empty).
        """
        market = detect_market(ticker)
        if market not in (MarketType.CN_SH, MarketType.CN_SZ):
            logger.warning("AKShare insider trades only support A-share tickers, got: %s", ticker)
            return []

        raw_ticker = normalize_ticker(ticker, target="akshare")

        # Try stock_shareholder_change_ths (同花顺-股东持股变动)
        try:
            df = self._call_with_retry(
                ak.stock_shareholder_change_ths,
                symbol=raw_ticker,
                description=f"insider trades for {raw_ticker}",
            )
        except Exception as e:
            logger.warning("Failed to fetch insider trades for %s: %s", ticker, e)
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
            Market cap as float, or None if unavailable.
        """
        market = detect_market(ticker)
        raw_ticker = normalize_ticker(ticker, target="akshare")

        if market in (MarketType.CN_SH, MarketType.CN_SZ):
            return self._get_a_share_market_cap(raw_ticker)
        elif market == MarketType.HK:
            return self._get_hk_market_cap(raw_ticker)
        else:
            logger.warning("AKShareProvider does not support US ticker: %s", ticker)
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
        from AKShare and extracts the requested items.

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
            logger.warning("AKShare line items only support A-share tickers, got: %s", ticker)
            return []

        raw_ticker = normalize_ticker(ticker, target="akshare")

        # Fetch all three financial statements
        income_df = self._fetch_financial_report(raw_ticker, "利润表")
        balance_df = self._fetch_financial_report(raw_ticker, "资产负债表")
        cashflow_df = self._fetch_financial_report(raw_ticker, "现金流量表")

        if (income_df is None or income_df.empty) and \
           (balance_df is None or balance_df.empty) and \
           (cashflow_df is None or cashflow_df.empty):
            return []

        return self._build_line_items(income_df, balance_df, cashflow_df, ticker, line_items, end_date, period, limit)

    # ------------------------------------------------------------------
    # Price helpers
    # ------------------------------------------------------------------

    def _get_a_share_prices(
        self,
        raw_ticker: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> pd.DataFrame | None:
        """Fetch A-share price data (daily or minute bars)."""
        if interval == "daily":
            df = self._call_with_retry(
                ak.stock_zh_a_hist,
                symbol=raw_ticker,
                period="daily",
                start_date=_fmt_date(start_date),
                end_date=_fmt_date(end_date),
                adjust="qfq",
                description=f"A-share daily prices for {raw_ticker}",
            )
            if df is not None and not df.empty:
                df = df.rename(columns=self._A_DAILY_COLS)
            return df

        # Minute bars
        ak_period = self._MIN_INTERVAL_MAP.get(interval)
        if ak_period is None:
            logger.warning("Unsupported interval for A-share minute data: %s", interval)
            return None

        df = self._call_with_retry(
            ak.stock_zh_a_hist_min_em,
            symbol=raw_ticker, period=ak_period,
            description=f"A-share {interval} prices for {raw_ticker}",
        )
        if df is not None and not df.empty:
            df = df.rename(columns=self._A_MIN_COLS)
        return df

    def _get_hk_prices(
        self,
        raw_ticker: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> pd.DataFrame | None:
        """Fetch HK stock price data (daily or minute bars)."""
        if interval == "daily":
            df = self._call_with_retry(
                ak.stock_hk_hist,
                symbol=raw_ticker,
                period="daily",
                start_date=_fmt_date(start_date),
                end_date=_fmt_date(end_date),
                adjust="qfq",
                description=f"HK daily prices for {raw_ticker}",
            )
            if df is not None and not df.empty:
                df = df.rename(columns=self._HK_DAILY_COLS)
            return df

        # Minute bars
        ak_period = self._MIN_INTERVAL_MAP.get(interval)
        if ak_period is None:
            logger.warning("Unsupported interval for HK minute data: %s", interval)
            return None

        df = self._call_with_retry(
            ak.stock_hk_hist_min_em,
            symbol=raw_ticker, period=ak_period,
            description=f"HK {interval} prices for {raw_ticker}",
        )
        if df is not None and not df.empty:
            df = df.rename(columns=self._HK_MIN_COLS)
        return df

    @staticmethod
    def _df_to_prices(df: pd.DataFrame, ticker: str) -> list[Price]:
        """Convert a DataFrame with standardised columns to list[Price]."""
        prices: list[Price] = []
        for _, row in df.iterrows():
            try:
                price = Price(
                    open=_safe_float(row.get("open")),
                    close=_safe_float(row.get("close")),
                    high=_safe_float(row.get("high")),
                    low=_safe_float(row.get("low")),
                    volume=_safe_int(row.get("volume")),
                    time=str(row.get("time", "")),
                )
                # Skip rows with missing critical fields
                if price.open is None or price.close is None:
                    continue
                prices.append(price)
            except Exception:
                continue
        return prices

    # ------------------------------------------------------------------
    # Financial report fetcher
    # ------------------------------------------------------------------

    def _fetch_financial_report(self, raw_ticker: str, symbol: str) -> pd.DataFrame | None:
        """Fetch a financial statement from AKShare.

        Args:
            raw_ticker: Stock code without suffix (e.g. '600519')
            symbol: One of '利润表', '资产负债表', '现金流量表'

        Returns:
            DataFrame or None on failure.
        """
        try:
            return self._call_with_retry(
                ak.stock_financial_report_sina,
                stock=raw_ticker, symbol=symbol,
                description=f"{symbol} for {raw_ticker}",
            )
        except Exception as e:
            logger.warning("Failed to fetch %s for %s: %s", symbol, raw_ticker, e)
            return None

    # ------------------------------------------------------------------
    # Financial metrics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_financial_metrics(
        income_df: pd.DataFrame | None,
        balance_df: pd.DataFrame | None,
        ticker: str,
        end_date: str,
        period: str,
        limit: int,
    ) -> list[FinancialMetrics]:
        """Build FinancialMetrics from income statement and balance sheet DataFrames."""
        results: list[FinancialMetrics] = []

        # Merge income and balance on report date
        # Both DataFrames have a '报告日' column
        merged: dict[str, dict] = {}  # report_date -> {col: value}

        if income_df is not None and not income_df.empty:
            for _, row in income_df.iterrows():
                rd = str(row.get("报告日", ""))[:10]
                if rd not in merged:
                    merged[rd] = {}
                for col in row.index:
                    merged[rd][col] = row[col]

        if balance_df is not None and not balance_df.empty:
            for _, row in balance_df.iterrows():
                rd = str(row.get("报告日", ""))[:10]
                if rd not in merged:
                    merged[rd] = {}
                for col in row.index:
                    merged[rd][col] = row[col]

        # Sort by report date descending
        sorted_dates = sorted(merged.keys(), reverse=True)

        for rd in sorted_dates:
            if len(results) >= limit:
                break

            # Filter by end_date
            if end_date and rd > end_date:
                continue

            data = merged[rd]

            # Derive metrics from the raw financial statement data
            total_revenue = _safe_float(data.get("营业总收入"))
            revenue = _safe_float(data.get("营业收入"))
            net_income = _safe_float(data.get("净利润"))
            total_assets = _safe_float(data.get("总资产"))
            total_equity = _safe_float(data.get("所有者权益(或股东权益)合计"))
            total_liabilities = _safe_float(data.get("负债合计"))
            current_assets = _safe_float(data.get("流动资产合计"))
            current_liabilities = _safe_float(data.get("流动负债合计"))
            operating_profit = _safe_float(data.get("营业利润"))
            basic_eps = _safe_float(data.get("基本每股收益"))

            # Compute derived ratios
            gross_margin = None
            operating_margin = None
            net_margin = None
            return_on_equity = None
            return_on_assets = None
            current_ratio = None
            debt_to_assets = None
            debt_to_equity = None
            asset_turnover = None

            if revenue is not None and net_income is not None and revenue != 0:
                net_margin = net_income / revenue
            if revenue is not None and operating_profit is not None and revenue != 0:
                operating_margin = operating_profit / revenue
            if total_equity is not None and net_income is not None and total_equity != 0:
                return_on_equity = net_income / total_equity
            if total_assets is not None and net_income is not None and total_assets != 0:
                return_on_assets = net_income / total_assets
            if current_assets is not None and current_liabilities is not None and current_liabilities != 0:
                current_ratio = current_assets / current_liabilities
            if total_assets is not None and total_liabilities is not None and total_assets != 0:
                debt_to_assets = total_liabilities / total_assets
            if total_equity is not None and total_liabilities is not None and total_equity != 0:
                debt_to_equity = total_liabilities / total_equity
            if total_assets is not None and revenue is not None and total_assets != 0:
                asset_turnover = revenue / total_assets

            try:
                metrics = FinancialMetrics(
                    ticker=ticker,
                    report_period=rd,
                    period=period,
                    currency="CNY",
                    market_cap=None,
                    enterprise_value=None,
                    price_to_earnings_ratio=None,
                    price_to_book_ratio=None,
                    price_to_sales_ratio=None,
                    enterprise_value_to_ebitda_ratio=None,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=None,
                    peg_ratio=None,
                    gross_margin=gross_margin,
                    operating_margin=operating_margin,
                    net_margin=net_margin,
                    return_on_equity=return_on_equity,
                    return_on_assets=return_on_assets,
                    return_on_invested_capital=None,
                    asset_turnover=asset_turnover,
                    inventory_turnover=None,
                    receivables_turnover=None,
                    days_sales_outstanding=None,
                    operating_cycle=None,
                    working_capital_turnover=None,
                    current_ratio=current_ratio,
                    quick_ratio=None,
                    cash_ratio=None,
                    operating_cash_flow_ratio=None,
                    debt_to_equity=debt_to_equity,
                    debt_to_assets=debt_to_assets,
                    interest_coverage=None,
                    revenue_growth=None,
                    earnings_growth=None,
                    book_value_growth=None,
                    earnings_per_share_growth=None,
                    free_cash_flow_growth=None,
                    operating_income_growth=None,
                    ebitda_growth=None,
                    payout_ratio=None,
                    earnings_per_share=basic_eps,
                    book_value_per_share=None,
                    free_cash_flow_per_share=None,
                )
                results.append(metrics)
            except Exception as e:
                logger.warning("Skipping financial metrics row for %s: %s", ticker, e)
                continue

        return results

    # ------------------------------------------------------------------
    # Company news helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_company_news(
        df: pd.DataFrame,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> list[CompanyNews]:
        """Parse AKShare stock news DataFrame into CompanyNews.

        AKShare stock_news_em columns:
        关键词, 新闻标题, 新闻内容, 发布时间, 文章来源, 新闻链接
        """
        results: list[CompanyNews] = []
        count = 0

        for _, row in df.iterrows():
            try:
                news_date = str(row.get("发布时间", ""))[:10]  # Take date part
                source = row.get("文章来源", row.get("新闻来源", ""))
                news = CompanyNews(
                    ticker=ticker,
                    title=str(row.get("新闻标题", "")),
                    author=None,
                    source=str(source),
                    date=news_date,
                    url=str(row.get("新闻链接", "")),
                    sentiment=None,
                )
                # Date range filter
                if start_date and news.date < start_date:
                    continue
                if end_date and news.date > end_date:
                    continue
                results.append(news)
                count += 1
                if count >= limit:
                    break
            except Exception as e:
                logger.warning("Skipping news row for %s: %s", ticker, e)
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
        """Parse shareholder position change data into InsiderTrade.

        AKShare stock_shareholder_change_ths columns:
        公告日期, 变动股东, 变动数量, 交易均价, 剩余股份总数, 变动期间, 变动途径
        """
        results: list[InsiderTrade] = []
        count = 0

        for _, row in df.iterrows():
            try:
                # Use 公告日期 (announcement date) as the primary date
                filing_date = str(row.get("公告日期", ""))[:10]
                # Also try to extract a transaction date from 变动期间
                change_period = str(row.get("变动期间", ""))
                # 变动期间 format: "2024.01.01-2024.01.31", take the start date
                tx_date = change_period.split("-")[0].replace(".", "-") if change_period else filing_date

                # Date range filter (use filing_date for filtering)
                if start_date and filing_date < start_date:
                    continue
                if end_date and filing_date > end_date:
                    continue

                # Parse 变动数量 - may contain Chinese chars like "增持4.16万"
                change_qty_str = str(row.get("变动数量", ""))
                transaction_shares = _parse_chinese_quantity(change_qty_str)

                trade = InsiderTrade(
                    ticker=ticker,
                    issuer=None,
                    name=str(row.get("变动股东", "")) or None,
                    title=None,
                    is_board_director=None,
                    transaction_date=tx_date or None,
                    transaction_shares=transaction_shares,
                    transaction_price_per_share=_safe_float(row.get("交易均价")),
                    transaction_value=None,
                    shares_owned_before_transaction=None,
                    shares_owned_after_transaction=_parse_chinese_quantity(str(row.get("剩余股份总数", ""))),
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

    def _get_a_share_market_cap(self, raw_ticker: str) -> float | None:
        """Fetch A-share total market cap via stock_individual_info_em."""
        try:
            df = self._call_with_retry(
                ak.stock_individual_info_em,
                symbol=raw_ticker,
                description=f"A-share info for market cap: {raw_ticker}",
            )
        except Exception as e:
            logger.warning("Failed to fetch A-share info for market cap: %s", e)
            return None

        if df is None or df.empty:
            return None

        # stock_individual_info_em returns two columns: item, value
        row = df[df["item"] == "总市值"]
        if row.empty:
            return None

        return _safe_float(row.iloc[0]["value"])

    def _get_hk_market_cap(self, raw_ticker: str) -> float | None:
        """Fetch HK stock total market cap via stock_hk_spot_em."""
        try:
            df = self._call_with_retry(
                ak.stock_hk_spot_em,
                description="HK spot data for market cap",
            )
        except Exception as e:
            logger.warning("Failed to fetch HK spot data for market cap: %s", e)
            return None

        if df is None or df.empty:
            return None

        # stock_hk_spot_em columns include: 代码, 总市值
        row = df[df["代码"] == raw_ticker]
        if row.empty:
            return None

        value = row.iloc[0].get("总市值")
        return _safe_float(value)

    # ------------------------------------------------------------------
    # Line items helpers
    # ------------------------------------------------------------------

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
                rd = str(row.get("报告日", ""))[:10]
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
                cn_col = self._LINE_ITEM_MAP.get(item_name)
                if cn_col and cn_col in data:
                    item_data[item_name] = _safe_float(data[cn_col])

            try:
                results.append(LineItem(**item_data))
            except Exception as e:
                logger.warning("Skipping line item row for %s: %s", ticker, e)
                continue

        return results
