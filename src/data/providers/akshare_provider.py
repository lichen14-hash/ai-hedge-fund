"""AKShare data provider for A-share and HK stock markets."""

import logging
import time
from datetime import datetime, timedelta
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
        # === 利润表 (Income Statement) ===
        "revenue": "营业收入",
        "total_revenue": "营业总收入",
        "cost_of_revenue": "营业成本",
        "operating_income": "营业利润",
        "net_income": "净利润",
        "earnings_per_share": "基本每股收益",
        "diluted_eps": "稀释每股收益",
        "interest_expense": "财务费用",
        "research_and_development": "研发费用",
        "income_tax_expense": "所得税费用",
        "total_operating_expenses": "营业总成本",
        "selling_general_and_admin": "销售费用",
        "general_and_admin": "管理费用",
        "income_before_tax": "利润总额",
        "net_income_to_parent": "归属于母公司所有者的净利润",
        "minority_interest_income": "少数股东损益",

        # === 资产负债表 (Balance Sheet) ===
        "total_assets": "资产总计",
        "total_liabilities": "负债合计",
        "total_equity": "所有者权益(或股东权益)合计",
        "cash_and_equivalents": "货币资金",
        "accounts_receivable": "应收账款",
        "inventory": "存货",
        "current_assets": "流动资产合计",
        "current_liabilities": "流动负债合计",
        "total_debt": "负债合计",
        "goodwill": "商誉",
        "intangible_assets": "无形资产",
        "outstanding_shares": "实收资本(或股本)",
        "retained_earnings": "未分配利润",
        "fixed_assets_net": "固定资产净值",
        "accumulated_depreciation": "累计折旧",

        # === 现金流量表 (Cash Flow Statement) ===
        "operating_cash_flow": "经营活动产生的现金流量净额",
        "capital_expenditure": "购建固定资产、无形资产和其他长期资产所支付的现金",
        "dividends_paid": "分配股利、利润或偿付利息所支付的现金",
        "investing_cash_flow": "投资活动产生的现金流量净额",
        "financing_cash_flow": "筹资活动产生的现金流量净额",
        "free_cash_flow": "自由现金流量",
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

        # Fetch income statement, balance sheet, and cash flow statement
        income_df = self._fetch_financial_report(raw_ticker, "利润表")
        balance_df = self._fetch_financial_report(raw_ticker, "资产负债表")
        cashflow_df = self._fetch_financial_report(raw_ticker, "现金流量表")

        if (income_df is None or income_df.empty) and \
           (balance_df is None or balance_df.empty) and \
           (cashflow_df is None or cashflow_df.empty):
            return []

        # Get market cap for valuation ratios
        market_cap = self.get_market_cap(ticker, end_date)

        return self._build_financial_metrics(
            income_df, balance_df, cashflow_df,
            ticker, end_date, period, limit, market_cap,
        )

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

    def get_valuation_params(self, ticker: str) -> dict:
        """Get dynamic valuation parameters (beta, risk-free rate).

        Args:
            ticker: Stock ticker (e.g. '600519.SH')

        Returns:
            Dict with 'beta', 'risk_free_rate', 'market_risk_premium'.
        """
        market = detect_market(ticker)
        if market in (MarketType.CN_SH, MarketType.CN_SZ):
            raw_ticker = normalize_ticker(ticker, target="akshare")
            beta = self._get_beta(raw_ticker)
            risk_free_rate = self._get_risk_free_rate()
        else:
            beta = None
            risk_free_rate = None

        return {
            "beta": beta if beta is not None else 1.0,
            "risk_free_rate": risk_free_rate if risk_free_rate is not None else 0.045,
            "market_risk_premium": 0.06,  # 中国A股长期ERP
        }

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
        cashflow_df: pd.DataFrame | None = None,
        ticker: str = "",
        end_date: str = "",
        period: str = "ttm",
        limit: int = 10,
        market_cap: float | None = None,
    ) -> list[FinancialMetrics]:
        """Build FinancialMetrics from income statement, balance sheet, and cash flow DataFrames."""
        results: list[FinancialMetrics] = []
        raw_values: list[tuple] = []  # For YoY growth calculations

        # Merge income, balance, and cash flow on report date
        # All DataFrames have a '报告日' column
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

        if cashflow_df is not None and not cashflow_df.empty:
            for _, row in cashflow_df.iterrows():
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

            # === Extract income statement fields ===
            total_revenue = _safe_float(data.get("营业总收入"))
            revenue = _safe_float(data.get("营业收入"))
            net_income = _safe_float(data.get("净利润"))
            operating_profit = _safe_float(data.get("营业利润"))
            basic_eps = _safe_float(data.get("基本每股收益"))
            cost_of_rev = _safe_float(data.get("营业成本"))
            interest_exp = _safe_float(data.get("财务费用"))

            # === Extract balance sheet fields ===
            total_assets = _safe_float(data.get("资产总计"))  # Fixed: was "总资产"
            total_equity = _safe_float(data.get("所有者权益(或股东权益)合计"))
            total_liabilities = _safe_float(data.get("负债合计"))
            current_assets = _safe_float(data.get("流动资产合计"))
            current_liabilities = _safe_float(data.get("流动负债合计"))
            shares = _safe_float(data.get("实收资本(或股本)"))

            # === Working capital calculation ===
            working_capital = None
            if current_assets is not None and current_liabilities is not None:
                working_capital = current_assets - current_liabilities

            # === Extract cash flow fields ===
            operating_cf = _safe_float(data.get("经营活动产生的现金流量净额"))
            capex = _safe_float(data.get("购建固定资产、无形资产和其他长期资产所支付的现金"))

            # === Derived calculations ===

            # Gross margin
            gross_margin = None
            if revenue is not None and cost_of_rev is not None and revenue != 0:
                gross_margin = (revenue - cost_of_rev) / revenue

            # Operating margin
            operating_margin = None
            if revenue is not None and operating_profit is not None and revenue != 0:
                operating_margin = operating_profit / revenue

            # Net margin
            net_margin = None
            if revenue is not None and net_income is not None and revenue != 0:
                net_margin = net_income / revenue

            # Return on equity
            return_on_equity = None
            if total_equity is not None and net_income is not None and total_equity != 0:
                return_on_equity = net_income / total_equity

            # Return on assets
            return_on_assets = None
            if total_assets is not None and net_income is not None and total_assets != 0:
                return_on_assets = net_income / total_assets

            # Current ratio
            current_ratio = None
            if current_assets is not None and current_liabilities is not None and current_liabilities != 0:
                current_ratio = current_assets / current_liabilities

            # Debt to assets
            debt_to_assets = None
            if total_assets is not None and total_liabilities is not None and total_assets != 0:
                debt_to_assets = total_liabilities / total_assets

            # Debt to equity
            debt_to_equity = None
            if total_equity is not None and total_liabilities is not None and total_equity != 0:
                debt_to_equity = total_liabilities / total_equity

            # Asset turnover
            asset_turnover = None
            if total_assets is not None and revenue is not None and total_assets != 0:
                asset_turnover = revenue / total_assets

            # Free cash flow
            free_cash_flow_val = None
            if operating_cf is not None and capex is not None:
                free_cash_flow_val = operating_cf - abs(capex)

            # Interest coverage
            interest_coverage_val = None
            if operating_profit is not None and interest_exp is not None and interest_exp != 0:
                interest_coverage_val = operating_profit / abs(interest_exp)

            # ROIC = NOPAT / Invested Capital
            roic = None
            operating_income_val = _safe_float(data.get("营业利润"))
            tax_val = _safe_float(data.get("所得税费用"))
            income_before_tax_val = _safe_float(data.get("利润总额"))
            total_equity_val = _safe_float(data.get("所有者权益(或股东权益)合计"))
            total_debt_val = _safe_float(data.get("负债合计"))
            cash_val = _safe_float(data.get("货币资金"))

            if operating_income_val is not None and income_before_tax_val and income_before_tax_val != 0:
                effective_tax_rate = (tax_val / income_before_tax_val) if tax_val is not None else 0.25
                nopat = operating_income_val * (1 - effective_tax_rate)
                invested_capital = (total_equity_val or 0) + (total_debt_val or 0) - (cash_val or 0)
                if invested_capital > 0:
                    roic = nopat / invested_capital

            # Book value per share
            book_value_per_share_val = None
            if total_equity is not None and shares is not None and shares > 0:
                book_value_per_share_val = total_equity / shares

            # Free cash flow per share
            fcf_per_share = None
            if free_cash_flow_val is not None and shares is not None and shares > 0:
                fcf_per_share = free_cash_flow_val / shares

            # === Valuation multiples ===
            price_to_earnings = None
            price_to_book = None
            price_to_sales = None
            fcf_yield = None

            # Enterprise Value = market_cap + total_debt - cash
            enterprise_value = None
            if market_cap is not None and market_cap > 0:
                total_debt_val = total_liabilities or 0
                cash_val = _safe_float(data.get("货币资金")) or 0
                enterprise_value = market_cap + total_debt_val - cash_val

            # EV/EBITDA ratio
            ev_to_ebitda = None
            if enterprise_value is not None and enterprise_value > 0:
                # Calculate EBITDA if not already available
                ebitda_val = None
                operating_income_val = _safe_float(data.get("营业利润"))
                da_val = _safe_float(data.get("累计折旧"))
                if operating_income_val is not None:
                    if da_val is not None:
                        ebitda_val = operating_income_val + abs(da_val)
                    else:
                        ebitda_val = operating_income_val
                if ebitda_val is not None and ebitda_val > 0:
                    ev_to_ebitda = enterprise_value / ebitda_val

            if market_cap and market_cap > 0:
                if net_income and net_income > 0:
                    price_to_earnings = market_cap / net_income
                if total_equity and total_equity > 0:
                    price_to_book = market_cap / total_equity
                if revenue and revenue > 0:
                    price_to_sales = market_cap / revenue
                if free_cash_flow_val and free_cash_flow_val != 0:
                    fcf_yield = free_cash_flow_val / market_cap

            # Save raw values for YoY growth calculation
            raw_values.append(
                (revenue, net_income, operating_profit, basic_eps, free_cash_flow_val, total_equity)
            )

            try:
                metrics = FinancialMetrics(
                    ticker=ticker,
                    report_period=rd,
                    period=period,
                    currency="CNY",
                    market_cap=market_cap,
                    enterprise_value=enterprise_value,
                    price_to_earnings_ratio=price_to_earnings,
                    price_to_book_ratio=price_to_book,
                    price_to_sales_ratio=price_to_sales,
                    enterprise_value_to_ebitda_ratio=ev_to_ebitda,
                    enterprise_value_to_revenue_ratio=None,
                    free_cash_flow_yield=fcf_yield,
                    peg_ratio=None,
                    gross_margin=gross_margin,
                    operating_margin=operating_margin,
                    net_margin=net_margin,
                    return_on_equity=return_on_equity,
                    return_on_assets=return_on_assets,
                    return_on_invested_capital=roic,
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
                    interest_coverage=interest_coverage_val,
                    revenue_growth=None,  # Filled in post-processing
                    earnings_growth=None,
                    book_value_growth=None,
                    earnings_per_share_growth=None,
                    free_cash_flow_growth=None,
                    operating_income_growth=None,
                    ebitda_growth=None,
                    payout_ratio=None,
                    earnings_per_share=basic_eps,
                    book_value_per_share=book_value_per_share_val,
                    free_cash_flow_per_share=fcf_per_share,
                )
                results.append(metrics)
            except Exception as e:
                logger.warning("Skipping financial metrics row for %s: %s", ticker, e)
                # Remove corresponding raw_values entry to keep indices aligned
                if raw_values and len(raw_values) > len(results):
                    raw_values.pop()
                continue

        # === YoY growth post-processing ===
        for i in range(len(results) - 1):
            curr_raw = raw_values[i]
            prev_raw = raw_values[i + 1]

            updates: dict = {}

            # revenue_growth
            if prev_raw[0] and prev_raw[0] != 0 and curr_raw[0] is not None:
                updates["revenue_growth"] = (curr_raw[0] - prev_raw[0]) / abs(prev_raw[0])

            # earnings_growth
            if prev_raw[1] and prev_raw[1] != 0 and curr_raw[1] is not None:
                updates["earnings_growth"] = (curr_raw[1] - prev_raw[1]) / abs(prev_raw[1])

            # operating_income_growth
            if prev_raw[2] and prev_raw[2] != 0 and curr_raw[2] is not None:
                updates["operating_income_growth"] = (curr_raw[2] - prev_raw[2]) / abs(prev_raw[2])

            # earnings_per_share_growth
            if prev_raw[3] and prev_raw[3] != 0 and curr_raw[3] is not None:
                updates["earnings_per_share_growth"] = (curr_raw[3] - prev_raw[3]) / abs(prev_raw[3])

            # free_cash_flow_growth
            if prev_raw[4] and prev_raw[4] != 0 and curr_raw[4] is not None:
                updates["free_cash_flow_growth"] = (curr_raw[4] - prev_raw[4]) / abs(prev_raw[4])

            # book_value_growth
            if prev_raw[5] and prev_raw[5] != 0 and curr_raw[5] is not None:
                updates["book_value_growth"] = (curr_raw[5] - prev_raw[5]) / abs(prev_raw[5])

            if updates:
                results[i] = results[i].model_copy(update=updates)

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
        """Fetch A-share total market cap with multi-level fallback.
    
        Level 1: stock_individual_info_em \u2014 direct \u603b\u5e02\u503c field
        Level 2: stock_zh_a_spot_em \u2014 \u5168\u5e02\u573a\u884c\u60c5\u603b\u5e02\u503c
        Level 3: Sina stock_zh_a_daily \u2014 close \u00d7 outstanding_share (\u6d41\u901a\u5e02\u503c\u8fd1\u4f3c)
        Level 4: Tencent stock_zh_a_hist_tx \u2014 close \u00d7 \u603b\u80a1\u672c from balance sheet
        Level 5: stock_zh_a_hist \u2014 close \u00d7 \u603b\u80a1\u672c (original _compute_market_cap)
        Level 6: Tushare pro.daily \u2014 close \u00d7 \u603b\u80a1\u672c from balance sheet
        """
        # Level 1: stock_individual_info_em (original method)
        try:
            df = self._call_with_retry(
                ak.stock_individual_info_em,
                symbol=raw_ticker,
                description=f"A-share info for market cap: {raw_ticker}",
            )
            if df is not None and not df.empty:
                row = df[df["item"] == "总市值"]
                if not row.empty:
                    cap = _safe_float(row.iloc[0]["value"])
                    if cap is not None and cap > 0:
                        logger.info("Got market cap for %s via stock_individual_info_em: %s", raw_ticker, cap)
                        return cap
        except Exception as e:
            logger.warning("Level 1 (stock_individual_info_em) failed for %s: %s", raw_ticker, e)

        # Level 2: stock_zh_a_spot_em (real-time spot data from East Money)
        try:
            df = self._call_with_retry(
                ak.stock_zh_a_spot_em,
                description=f"A-share spot for market cap: {raw_ticker}",
            )
            if df is not None and not df.empty:
                row = df[df["代码"] == raw_ticker]
                if not row.empty:
                    cap = _safe_float(row.iloc[0].get("总市值"))
                    if cap is not None and cap > 0:
                        logger.info("Got market cap for %s via stock_zh_a_spot_em: %s", raw_ticker, cap)
                        return cap
        except Exception as e:
            logger.warning("Level 2 (stock_zh_a_spot_em) failed for %s: %s", raw_ticker, e)

        # Level 3: Sina Finance \u2014 close \u00d7 outstanding_share (\u6d41\u901a\u5e02\u503c\u8fd1\u4f3c)
        try:
            prefix = self._sina_symbol_prefix(raw_ticker)
            symbol = f"{prefix}{raw_ticker}"
            df = ak.stock_zh_a_daily(symbol=symbol, adjust="")  # \u4e0d\u590d\u6743
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                close = _safe_float(latest.get("close"))
                outstanding = _safe_float(latest.get("outstanding_share"))
                if close is not None and outstanding is not None and close > 0 and outstanding > 0:
                    market_cap = close * outstanding
                    logger.info("Level 3 (Sina) market cap for %s: %.2f", raw_ticker, market_cap)
                    return market_cap
        except Exception as e:
            logger.warning("Level 3 (Sina) market cap failed for %s: %s", raw_ticker, e)
        
        # Level 4: Tencent Finance \u2014 close \u00d7 shares from balance sheet
        try:
            prefix = self._sina_symbol_prefix(raw_ticker)
            symbol = f"{prefix}{raw_ticker}"
            df = ak.stock_zh_a_hist_tx(symbol=symbol)
            if df is not None and not df.empty:
                latest_price = _safe_float(df.iloc[-1].get("close"))
                if latest_price is not None and latest_price > 0:
                    shares = self._get_total_shares(raw_ticker)
                    if shares is not None and shares > 0:
                        market_cap = latest_price * shares
                        logger.info("Level 4 (Tencent) market cap for %s: %.2f", raw_ticker, market_cap)
                        return market_cap
        except Exception as e:
            logger.warning("Level 4 (Tencent) market cap failed for %s: %s", raw_ticker, e)
        
        # Level 5: Compute from stock_zh_a_hist price \u00d7 balance sheet shares
        try:
            cap = self._compute_market_cap(raw_ticker)
            if cap is not None and cap > 0:
                logger.info("Got market cap for %s via computation: %s", raw_ticker, cap)
                return cap
        except Exception as e:
            logger.warning("Level 5 (computation) failed for %s: %s", raw_ticker, e)
        
        # Level 6: Tushare pro.daily \u2014 close \u00d7 shares from balance sheet
        try:
            import os
            from dotenv import load_dotenv
            load_dotenv()
            token = os.environ.get("TUSHARE_TOKEN")
            if token:
                import tushare as ts
                pro = ts.pro_api(token)
                ts_code = f"{raw_ticker}.SZ" if raw_ticker[0] in ("0", "3") else f"{raw_ticker}.SH"
                start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
                df = pro.daily(ts_code=ts_code, start_date=start_date)
                if df is not None and not df.empty:
                    latest_price = _safe_float(df.iloc[0].get("close"))
                    if latest_price is not None and latest_price > 0:
                        shares = self._get_total_shares(raw_ticker)
                        if shares is not None and shares > 0:
                            market_cap = latest_price * shares
                            logger.info("Level 6 (Tushare) market cap for %s: %.2f", raw_ticker, market_cap)
                            return market_cap
        except Exception as e:
            logger.warning("Level 6 (Tushare) market cap failed for %s: %s", raw_ticker, e)
        
        logger.warning("All methods failed to get market cap for %s", raw_ticker)
        return None

    def _get_total_shares(self, raw_ticker: str) -> float | None:
        """Fetch total shares (\u5b9e\u6536\u8d44\u672c/\u80a1\u672c) from the latest balance sheet.
    
        Returns:
            Total shares as float, or None if unavailable.
        """
        try:
            balance_df = self._fetch_financial_report(raw_ticker, "\u8d44\u4ea7\u8d1f\u503a\u8868")
            if balance_df is None or balance_df.empty:
                return None
            shares = _safe_float(balance_df.iloc[0].get("\u5b9e\u6536\u8d44\u672c(\u6216\u80a1\u672c)"))
            return shares
        except Exception as e:
            logger.warning("Failed to get total shares for %s: %s", raw_ticker, e)
            return None
    
    def _compute_market_cap(self, raw_ticker: str) -> float | None:
        """Compute market cap = latest close price \u00d7 outstanding shares."""
        try:
            # Get latest price using existing method
            today = datetime.now().strftime("%Y%m%d")
            # Try to get recent price (last 5 trading days to handle holidays)
            start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            df_price = self._call_with_retry(
                ak.stock_zh_a_hist,
                symbol=raw_ticker,
                period="daily",
                start_date=start,
                end_date=today,
                adjust="",
                description=f"Price for market cap computation: {raw_ticker}",
            )
            if df_price is None or df_price.empty:
                return None
            latest_close = _safe_float(df_price.iloc[-1].get("\u6536\u76d8"))
            if latest_close is None or latest_close <= 0:
                return None
    
            # Get shares outstanding from balance sheet
            shares = self._get_total_shares(raw_ticker)
            if shares is None or shares <= 0:
                return None
    
            return latest_close * shares
        except Exception as e:
            logger.warning("Error computing market cap for %s: %s", raw_ticker, e)
            return None

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
    # Beta calculation with multi-source fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _sina_symbol_prefix(raw_ticker: str) -> str:
        """Return Sina-style prefix for a raw A-share ticker.

        0/3开头 → 'sz', 6开头 → 'sh'.
        """
        code = raw_ticker.lstrip("shsz")[:1]  # strip any existing prefix
        return "sz" if code in ("0", "3") else "sh"

    def _try_eastmoney_stock(
        self, raw_ticker: str, start_str: str, end_str: str,
    ) -> pd.Series | None:
        """Level 1: fetch stock close prices via Eastmoney (ak.stock_zh_a_hist)."""
        try:
            df = self._call_with_retry(
                ak.stock_zh_a_hist,
                symbol=raw_ticker,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
                description=f"Eastmoney stock hist for beta: {raw_ticker}",
            )
            if df is not None and len(df) >= 60:
                series = df.set_index("日期")["收盘"].astype(float)
                series.index = pd.to_datetime(series.index).strftime("%Y-%m-%d")
                logger.info("Got %d stock prices via Eastmoney for %s", len(series), raw_ticker)
                return series
        except Exception as e:
            logger.warning("Level 1 (Eastmoney stock) failed for %s: %s", raw_ticker, e)
        return None

    def _try_sina_stock(
        self, raw_ticker: str, start: datetime,
    ) -> pd.Series | None:
        """Level 2: fetch stock close prices via Sina (ak.stock_zh_a_daily)."""
        try:
            prefix = self._sina_symbol_prefix(raw_ticker)
            symbol = f"{prefix}{raw_ticker}"
            df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
            if df is not None and not df.empty:
                # Sina returns full history; filter by start date
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                start_str = start.strftime("%Y-%m-%d")
                df = df[df["date"] >= start_str]
                if len(df) >= 60:
                    series = df.set_index("date")["close"].astype(float)
                    logger.info("Got %d stock prices via Sina for %s", len(series), raw_ticker)
                    return series
        except Exception as e:
            logger.warning("Level 2 (Sina stock) failed for %s: %s", raw_ticker, e)
        return None

    def _try_tencent_stock(
        self, raw_ticker: str, start: datetime,
    ) -> pd.Series | None:
        """Level 3: Tencent Finance stock daily via ak.stock_zh_a_hist_tx"""
        try:
            prefix = self._sina_symbol_prefix(raw_ticker)  # 复用，前缀规则相同
            symbol = f"{prefix}{raw_ticker}"
            df = ak.stock_zh_a_hist_tx(symbol=symbol)
            if df is None or df.empty:
                return None
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["date"] >= start]
            if len(df) < 60:
                return None
            prices = df.set_index("date")["close"].sort_index().astype(float)
            logger.info("Tencent stock data OK for %s: %d rows", raw_ticker, len(prices))
            return prices
        except Exception as e:
            logger.warning("Level 3 (Tencent stock) failed for %s: %s", raw_ticker, e)
            return None

    def _try_tushare_stock(
        self, raw_ticker: str, start_str: str, end_str: str,
    ) -> pd.Series | None:
        """Level 4: fetch stock close prices via Tushare (pro.daily)."""
        try:
            import os
            from dotenv import load_dotenv
            load_dotenv()
            token = os.environ.get("TUSHARE_TOKEN")
            if not token:
                logger.info("Level 4 (Tushare stock) skipped: no TUSHARE_TOKEN")
                return None
            import tushare as ts
            pro = ts.pro_api(token)
            # Tushare uses 'XXXXXX.SH' / 'XXXXXX.SZ' format
            prefix = self._sina_symbol_prefix(raw_ticker).upper()
            ts_code = f"{raw_ticker}.{prefix}"
            df = pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
            if df is not None and not df.empty:
                # trade_date format: '20260421' → convert to '2026-04-21'
                df["date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
                df = df.sort_values("date")
                if len(df) >= 60:
                    series = df.set_index("date")["close"].astype(float)
                    logger.info("Got %d stock prices via Tushare for %s", len(series), raw_ticker)
                    return series
        except Exception as e:
            logger.warning("Level 4 (Tushare stock) failed for %s: %s", raw_ticker, e)
        return None

    def _try_eastmoney_index(
        self, start_str: str, end_str: str,
    ) -> pd.Series | None:
        """Level 1: fetch CSI 300 index close prices via Eastmoney."""
        try:
            df = self._call_with_retry(
                ak.stock_zh_index_daily_em,
                symbol="sh000300",
                start_date=start_str,
                end_date=end_str,
                description="Eastmoney CSI300 for beta",
            )
            if df is not None and len(df) >= 60:
                series = df.set_index("date")["close"].astype(float)
                series.index = pd.to_datetime(series.index).strftime("%Y-%m-%d")
                logger.info("Got %d index prices via Eastmoney", len(series))
                return series
        except Exception as e:
            logger.warning("Level 1 (Eastmoney index) failed: %s", e)
        return None

    def _try_sina_index(self, start: datetime) -> pd.Series | None:
        """Level 2/3: fetch CSI 300 index close prices via Sina."""
        try:
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if df is not None and not df.empty:
                # Sina returns full history; filter by start date
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                start_str = start.strftime("%Y-%m-%d")
                df = df[df["date"] >= start_str]
                if len(df) >= 60:
                    series = df.set_index("date")["close"].astype(float)
                    logger.info("Got %d index prices via Sina", len(series))
                    return series
        except Exception as e:
            logger.warning("Level 2 (Sina index) failed: %s", e)
        return None

    def _try_tencent_index(self, start: datetime) -> pd.Series | None:
        """Level 3: Tencent Finance CSI300 index daily via ak.stock_zh_index_daily_tx"""
        try:
            df = ak.stock_zh_index_daily_tx(symbol="sh000300")
            if df is None or df.empty:
                return None
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["date"] >= start]
            if len(df) < 60:
                return None
            prices = df.set_index("date")["close"].sort_index().astype(float)
            logger.info("Tencent CSI300 index data OK: %d rows", len(prices))
            return prices
        except Exception as e:
            logger.warning("Level 3 (Tencent index) failed: %s", e)
            return None

    def _get_beta(self, raw_ticker: str, years: int = 3) -> float | None:
        """Calculate stock beta against CSI 300 index using historical returns.

        Tries multiple data sources with fallback:
          Level 1: Eastmoney (ak.stock_zh_a_hist + ak.stock_zh_index_daily_em)
          Level 2: Sina (ak.stock_zh_a_daily + ak.stock_zh_index_daily)
          Level 3: Tencent (ak.stock_zh_a_hist_tx + ak.stock_zh_index_daily_tx)
          Level 4: Tushare (pro.daily) + Sina (ak.stock_zh_index_daily)
        """
        import numpy as np

        try:
            end = datetime.now()
            start = end - timedelta(days=years * 365)
            start_str = start.strftime("%Y%m%d")
            end_str = end.strftime("%Y%m%d")

            # --- 获取个股日线 (逐级降级) ---
            stock_prices: pd.Series | None = None

            # Level 1: 东方财富
            stock_prices = self._try_eastmoney_stock(raw_ticker, start_str, end_str)

            # Level 2: 新浪
            if stock_prices is None:
                stock_prices = self._try_sina_stock(raw_ticker, start)

            # Level 3: 腾讯
            if stock_prices is None:
                stock_prices = self._try_tencent_stock(raw_ticker, start)

            # Level 4: Tushare
            if stock_prices is None:
                stock_prices = self._try_tushare_stock(raw_ticker, start_str, end_str)

            if stock_prices is None or len(stock_prices) < 60:
                logger.warning("All stock data sources failed for beta: %s", raw_ticker)
                return None

            # --- 获取沪深300指数日线 (逐级降级) ---
            index_prices: pd.Series | None = None

            # Level 1: 东方财富
            index_prices = self._try_eastmoney_index(start_str, end_str)

            # Level 2: 新浪（最可靠）
            if index_prices is None:
                index_prices = self._try_sina_index(start)

            # Level 3: 腾讯
            if index_prices is None:
                index_prices = self._try_tencent_index(start)

            if index_prices is None or len(index_prices) < 60:
                logger.warning("All index data sources failed for beta")
                return None

            # --- 计算 Beta ---
            stock_returns = stock_prices.pct_change().dropna()
            index_returns = index_prices.pct_change().dropna()

            # Align on common dates
            common = stock_returns.index.intersection(index_returns.index)
            if len(common) < 60:
                logger.warning(
                    "Insufficient overlapping dates for beta: %d (need 60)", len(common),
                )
                return None

            sr = stock_returns.loc[common].values.astype(float)
            ir = index_returns.loc[common].values.astype(float)

            cov = np.cov(sr, ir)[0][1]
            var = np.var(ir, ddof=1)
            if var == 0:
                return None

            beta = cov / var
            logger.info(
                "Calculated beta for %s: %.4f (from %d observations)",
                raw_ticker, beta, len(common),
            )
            return round(beta, 4)
        except Exception as e:
            logger.warning("Failed to calculate beta for %s: %s", raw_ticker, e)
            return None

    def _get_risk_free_rate(self) -> float | None:
        """Get China 10-year government bond yield as risk-free rate."""
        try:
            # end_date - start_date should be < 1 year per AKShare docs
            end = datetime.now()
            start = end - timedelta(days=30)
            start_str = start.strftime("%Y%m%d")
            end_str = end.strftime("%Y%m%d")

            df = self._call_with_retry(
                ak.bond_china_yield,
                start_date=start_str,
                end_date=end_str,
                description="China bond yield for risk-free rate",
            )
            if df is None or df.empty:
                return None

            # Get latest value; df is sorted ascending by date
            latest = df.iloc[-1]
            rate = _safe_float(latest.get("10年"))
            if rate is not None and rate > 0:
                # Value is in percentage, convert to decimal
                risk_free = rate / 100.0
                logger.info("Got risk-free rate (10Y bond yield): %.4f", risk_free)
                return risk_free

            return None
        except Exception as e:
            logger.warning("Failed to get risk-free rate: %s", e)
            return None

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

            # 派生字段的依赖关系映射
            _FIELD_DEPENDENCIES = {
                "free_cash_flow": ["operating_cash_flow", "capital_expenditure"],
                "gross_profit": ["revenue", "cost_of_revenue"],
                "ebitda": ["operating_income", "depreciation_and_amortization"],
                "working_capital": ["current_assets", "current_liabilities"],
                "enterprise_value": ["market_cap", "total_debt", "total_liabilities", "cash_and_equivalents"],
            }

            # 自动扩展 line_items 以包含派生字段所需的源字段
            expanded_items = list(line_items)
            for field in line_items:
                if field in _FIELD_DEPENDENCIES:
                    for dep in _FIELD_DEPENDENCIES[field]:
                        if dep not in expanded_items:
                            expanded_items.append(dep)

            for item_name in expanded_items:
                cn_col = self._LINE_ITEM_MAP.get(item_name)
                if cn_col and cn_col in data:
                    item_data[item_name] = _safe_float(data[cn_col])

            # === Derived calculations for common line items ===

            # Derive free_cash_flow if direct mapping didn't yield a value
            if "free_cash_flow" in line_items and item_data.get("free_cash_flow") is None:
                ocf = item_data.get("operating_cash_flow")
                capex_val = item_data.get("capital_expenditure")
                if ocf is not None and capex_val is not None:
                    item_data["free_cash_flow"] = ocf - abs(capex_val)

            # Derive gross_profit
            if "gross_profit" in line_items and item_data.get("gross_profit") is None:
                rev = item_data.get("revenue")
                cogs = item_data.get("cost_of_revenue")
                if rev is not None and cogs is not None:
                    item_data["gross_profit"] = rev - cogs

            # Derive ebitda (approximate)
            if "ebitda" in line_items and item_data.get("ebitda") is None:
                op_income = item_data.get("operating_income")
                da = item_data.get("depreciation_and_amortization")
                if op_income is not None:
                    if da is not None:
                        item_data["ebitda"] = op_income + abs(da)
                    else:
                        # Without D&A data, approximate with operating income
                        item_data["ebitda"] = op_income

            # Derive working_capital = current_assets - current_liabilities
            if "working_capital" in line_items and item_data.get("working_capital") is None:
                ca = item_data.get("current_assets")
                cl = item_data.get("current_liabilities")
                if ca is not None and cl is not None:
                    item_data["working_capital"] = ca - cl

            # Derive enterprise_value = market_cap + total_debt - cash_and_equivalents
            if "enterprise_value" in line_items and item_data.get("enterprise_value") is None:
                # market_cap needs to be fetched separately
                mc = item_data.get("market_cap")
                td = item_data.get("total_debt") or item_data.get("total_liabilities") or 0
                cash = item_data.get("cash_and_equivalents") or 0
                if mc is not None and mc > 0:
                    item_data["enterprise_value"] = mc + td - cash

            try:
                results.append(LineItem(**item_data))
            except Exception as e:
                logger.warning("Skipping line item row for %s: %s", ticker, e)
                continue

        return results
