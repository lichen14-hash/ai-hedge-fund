"""YFinance data provider for US and HK stock markets.

Uses yfinance as a backup data source for US and HK stocks.
A-shares (CN_SH/CN_SZ) are NOT supported by yfinance.
"""

import warnings
from datetime import datetime

import yfinance as yf

from src.data.models import (
    FinancialMetrics,
    LineItem,
    MarketType,
    Price,
    detect_market,
    normalize_ticker,
)

# Suppress yfinance warnings (e.g., UserWarning about formatting)
warnings.filterwarnings("ignore", category=UserWarning, module="yfinance")


class YFinanceProvider:
    """Data provider backed by yfinance, supporting US and HK markets."""

    # Mapping from yfinance .info keys to FinancialMetrics fields
    _INFO_METRICS_MAP = {
        "marketCap": "market_cap",
        "enterpriseValue": "enterprise_value",
        "trailingPE": "price_to_earnings_ratio",
        "priceToBook": "price_to_book_ratio",
        "priceToSalesTrailing12Months": "price_to_sales_ratio",
        "enterpriseToEbitda": "enterprise_value_to_ebitda_ratio",
        "enterpriseToRevenue": "enterprise_value_to_revenue_ratio",
        "pegRatio": "peg_ratio",
        "grossMargins": "gross_margin",
        "operatingMargins": "operating_margin",
        "profitMargins": "net_margin",
        "returnOnEquity": "return_on_equity",
        "returnOnAssets": "return_on_assets",
        "debtToEquity": "debt_to_equity",
        "currentRatio": "current_ratio",
        "quickRatio": "quick_ratio",
        "payoutRatio": "payout_ratio",
        "earningsGrowth": "earnings_growth",
        "revenueGrowth": "revenue_growth",
        "trailingEps": "earnings_per_share",
        "bookValue": "book_value_per_share",
    }

    # Mapping from yfinance financial statement column names to LineItem-friendly names
    _LINE_ITEM_MAP = {
        "Total Revenue": "total_revenue",
        "Cost Of Revenue": "cost_of_revenue",
        "Gross Profit": "gross_profit",
        "Operating Revenue": "operating_revenue",
        "Operating Income": "operating_income",
        "Net Income": "net_income",
        "Net Income Common Stockholders": "net_income_common_stockholders",
        "EBITDA": "ebitda",
        "EBIT": "ebit",
        "Interest Expense": "interest_expense",
        "Depreciation And Amortization": "depreciation_and_amortization",
        "Research Development": "research_and_development",
        "Selling General Administrative": "selling_general_and_administrative",
        "Total Assets": "total_assets",
        "Total Liabilities Net Minority Interest": "total_liabilities",
        "Total Equity Gross Minority Interest": "total_equity",
        "Common Stock Equity": "common_stock_equity",
        "Cash And Cash Equivalents": "cash_and_cash_equivalents",
        "Cash Cash Equivalents And Short Term Investments": "cash_and_short_term_investments",
        "Inventory": "inventory",
        "Accounts Receivable": "accounts_receivable",
        "Current Assets": "current_assets",
        "Current Liabilities": "current_liabilities",
        "Long Term Debt": "long_term_debt",
        "Short Term Debt": "short_term_debt",
        "Operating Cash Flow": "operating_cash_flow",
        "Free Cash Flow": "free_cash_flow",
        "Capital Expenditure": "capital_expenditure",
        "Dividends Paid": "dividends_paid",
        "Share Issued": "shares_outstanding",
        "Net Debt": "net_debt",
        "Goodwill": "goodwill",
        "Intangible Assets": "intangible_assets",
        "Property Plant Equipment": "property_plant_and_equipment",
        "Retained Earnings": "retained_earnings",
    }

    def _convert_ticker(self, ticker: str) -> str | None:
        """Convert ticker to yfinance format. Returns None for unsupported markets."""
        market = detect_market(ticker)
        if market in (MarketType.CN_SH, MarketType.CN_SZ):
            return None
        return normalize_ticker(ticker, "yfinance")

    def get_prices(
        self, ticker: str, start_date: str, end_date: str
    ) -> list[Price]:
        """Fetch OHLCV price data from yfinance.

        Args:
            ticker: Stock ticker (e.g., 'AAPL', '0700.HK')
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)

        Returns:
            List of Price objects, or empty list on failure.
        """
        symbol = self._convert_ticker(ticker)
        if symbol is None:
            return []

        try:
            df = yf.download(
                symbol, start=start_date, end=end_date, progress=False
            )
            if df is None or df.empty:
                return []

            prices: list[Price] = []
            for date_idx, row in df.iterrows():
                try:
                    # Handle MultiIndex columns (yfinance >= 0.2.18)
                    if isinstance(row.iloc[0], (int, float)):
                        open_val = float(row.iloc[0])
                        high_val = float(row.iloc[1])
                        low_val = float(row.iloc[2])
                        close_val = float(row.iloc[3])
                        volume_val = int(row.iloc[4]) if len(row) > 4 else 0
                    else:
                        # MultiIndex: extract values from Series
                        open_val = float(row["Open"].iloc[0]) if hasattr(row["Open"], "iloc") else float(row["Open"])
                        high_val = float(row["High"].iloc[0]) if hasattr(row["High"], "iloc") else float(row["High"])
                        low_val = float(row["Low"].iloc[0]) if hasattr(row["Low"], "iloc") else float(row["Low"])
                        close_val = float(row["Close"].iloc[0]) if hasattr(row["Close"], "iloc") else float(row["Close"])
                        volume_val = int(row["Volume"].iloc[0]) if hasattr(row["Volume"], "iloc") else int(row["Volume"])
                except (IndexError, KeyError, TypeError):
                    # Fallback: try accessing by position
                    open_val = float(row.iloc[0])
                    high_val = float(row.iloc[1])
                    low_val = float(row.iloc[2])
                    close_val = float(row.iloc[3])
                    volume_val = int(row.iloc[4]) if len(row) > 4 else 0

                price = Price(
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=volume_val,
                    time=date_idx.strftime("%Y-%m-%d"),
                )
                prices.append(price)

            return prices

        except Exception as e:
            warnings.warn(f"YFinanceProvider.get_prices({ticker}) failed: {e}")
            return []

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        """Fetch financial metrics from yfinance.

        Args:
            ticker: Stock ticker
            end_date: End date string (YYYY-MM-DD)
            period: Period type ('ttm', 'annual', 'quarterly')
            limit: Maximum number of results

        Returns:
            List of FinancialMetrics objects, or empty list on failure.
        """
        symbol = self._convert_ticker(ticker)
        if symbol is None:
            return []

        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}

            # Build metrics dict with all fields defaulting to None
            metrics_data: dict = {
                "ticker": ticker,
                "report_period": end_date,
                "period": period,
                "currency": info.get("currency", "USD"),
                # Initialize all nullable fields to None
                "market_cap": None,
                "enterprise_value": None,
                "price_to_earnings_ratio": None,
                "price_to_book_ratio": None,
                "price_to_sales_ratio": None,
                "enterprise_value_to_ebitda_ratio": None,
                "enterprise_value_to_revenue_ratio": None,
                "free_cash_flow_yield": None,
                "peg_ratio": None,
                "gross_margin": None,
                "operating_margin": None,
                "net_margin": None,
                "return_on_equity": None,
                "return_on_assets": None,
                "return_on_invested_capital": None,
                "asset_turnover": None,
                "inventory_turnover": None,
                "receivables_turnover": None,
                "days_sales_outstanding": None,
                "operating_cycle": None,
                "working_capital_turnover": None,
                "current_ratio": None,
                "quick_ratio": None,
                "cash_ratio": None,
                "operating_cash_flow_ratio": None,
                "debt_to_equity": None,
                "debt_to_assets": None,
                "interest_coverage": None,
                "revenue_growth": None,
                "earnings_growth": None,
                "book_value_growth": None,
                "earnings_per_share_growth": None,
                "free_cash_flow_growth": None,
                "operating_income_growth": None,
                "ebitda_growth": None,
                "payout_ratio": None,
                "earnings_per_share": None,
                "book_value_per_share": None,
                "free_cash_flow_per_share": None,
            }

            for yf_key, field_name in self._INFO_METRICS_MAP.items():
                val = info.get(yf_key)
                metrics_data[field_name] = float(val) if val is not None else None

            # Compute derived metrics from financial statements
            try:
                income_stmt = stock.income_stmt
                balance_sheet = stock.balance_sheet
                cashflow = stock.cashflow

                if income_stmt is not None and not income_stmt.empty:
                    # Free cash flow per share
                    if (
                        cashflow is not None
                        and not cashflow.empty
                        and "Free Cash Flow" in cashflow.index
                    ):
                        fcf = cashflow.loc["Free Cash Flow"].iloc[0]
                        shares = info.get("sharesOutstanding")
                        if (
                            fcf is not None
                            and shares
                            and not (isinstance(fcf, float) and fcf != fcf)
                        ):
                            metrics_data["free_cash_flow_per_share"] = float(
                                fcf
                            ) / float(shares)
                            # Free cash flow yield
                            market_cap = info.get("marketCap")
                            if market_cap and float(market_cap) > 0:
                                metrics_data["free_cash_flow_yield"] = float(
                                    fcf
                                ) / float(market_cap)

                    # Operating cash flow ratio
                    if (
                        cashflow is not None
                        and not cashflow.empty
                        and "Operating Cash Flow" in cashflow.index
                        and balance_sheet is not None
                        and not balance_sheet.empty
                        and "Current Liabilities" in balance_sheet.index
                    ):
                        ocf = cashflow.loc["Operating Cash Flow"].iloc[0]
                        cl = balance_sheet.loc["Current Liabilities"].iloc[0]
                        if (
                            ocf is not None
                            and cl is not None
                            and float(cl) != 0
                        ):
                            metrics_data["operating_cash_flow_ratio"] = float(
                                ocf
                            ) / float(cl)

                    # Debt to assets
                    if (
                        balance_sheet is not None
                        and not balance_sheet.empty
                        and "Total Liabilities Net Minority Interest" in balance_sheet.index
                        and "Total Assets" in balance_sheet.index
                    ):
                        total_liab = balance_sheet.loc[
                            "Total Liabilities Net Minority Interest"
                        ].iloc[0]
                        total_assets = balance_sheet.loc["Total Assets"].iloc[0]
                        if (
                            total_assets is not None
                            and float(total_assets) != 0
                        ):
                            metrics_data["debt_to_assets"] = float(
                                total_liab
                            ) / float(total_assets)

                    # Interest coverage
                    if (
                        income_stmt is not None
                        and not income_stmt.empty
                        and "Operating Income" in income_stmt.index
                        and "Interest Expense" in income_stmt.index
                    ):
                        op_income = income_stmt.loc["Operating Income"].iloc[0]
                        int_expense = income_stmt.loc["Interest Expense"].iloc[0]
                        if (
                            op_income is not None
                            and int_expense is not None
                            and float(int_expense) != 0
                        ):
                            metrics_data["interest_coverage"] = float(
                                op_income
                            ) / abs(float(int_expense))

                    # Return on invested capital
                    if (
                        balance_sheet is not None
                        and not balance_sheet.empty
                        and "Common Stock Equity" in balance_sheet.index
                        and income_stmt is not None
                        and not income_stmt.empty
                        and "Operating Income" in income_stmt.index
                    ):
                        equity = balance_sheet.loc[
                            "Common Stock Equity"
                        ].iloc[0]
                        op_income = income_stmt.loc["Operating Income"].iloc[0]
                        if (
                            equity is not None
                            and float(equity) != 0
                            and op_income is not None
                        ):
                            metrics_data["return_on_invested_capital"] = float(
                                op_income
                            ) / float(equity)

            except Exception:
                pass  # Best-effort derived metrics

            metrics_obj = FinancialMetrics(**metrics_data)
            return [metrics_obj]

        except Exception as e:
            warnings.warn(
                f"YFinanceProvider.get_financial_metrics({ticker}) failed: {e}"
            )
            return []

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Fetch market capitalization from yfinance.

        Args:
            ticker: Stock ticker
            end_date: End date string (YYYY-MM-DD)

        Returns:
            Market cap as float, or None on failure.
        """
        symbol = self._convert_ticker(ticker)
        if symbol is None:
            return None

        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}
            market_cap = info.get("marketCap")
            return float(market_cap) if market_cap is not None else None
        except Exception as e:
            warnings.warn(
                f"YFinanceProvider.get_market_cap({ticker}) failed: {e}"
            )
            return None

    def search_line_items(
        self,
        ticker: str,
        line_items: list[str],
        end_date: str,
        period: str = "annual",
        limit: int = 10,
    ) -> list[LineItem]:
        """Search for specific line items from financial statements.

        Args:
            ticker: Stock ticker
            line_items: List of line item names to search for
            end_date: End date string (YYYY-MM-DD)
            period: 'annual' or 'quarterly'
            limit: Maximum number of results

        Returns:
            List of LineItem objects, or empty list on failure.
        """
        symbol = self._convert_ticker(ticker)
        if symbol is None:
            return []

        try:
            stock = yf.Ticker(symbol)

            # Select the appropriate period
            if period == "quarterly":
                income_stmt = stock.quarterly_income_stmt
                balance_sheet = stock.quarterly_balance_sheet
                cashflow = stock.quarterly_cashflow
            else:
                income_stmt = stock.income_stmt
                balance_sheet = stock.balance_sheet
                cashflow = stock.cashflow

            # Merge all statements into one lookup
            all_statements = {}
            for stmt in [income_stmt, balance_sheet, cashflow]:
                if stmt is not None and not stmt.empty:
                    for idx_name in stmt.index:
                        if idx_name not in all_statements:
                            all_statements[idx_name] = stmt.loc[idx_name]

            # Build reverse map: normalized field name -> yfinance name
            reverse_map = {v: k for k, v in self._LINE_ITEM_MAP.items()}

            results: list[LineItem] = []
            count = 0

            # Determine currency
            info = stock.info or {}
            currency = info.get("currency", "USD")

            # Iterate over date columns (each column = one report period)
            # Use the first statement that has columns to get dates
            ref_stmt = None
            for stmt in [income_stmt, balance_sheet, cashflow]:
                if stmt is not None and not stmt.empty:
                    ref_stmt = stmt
                    break

            if ref_stmt is None:
                return []

            for col in ref_stmt.columns:
                if count >= limit:
                    break

                report_period = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)

                item_data: dict = {
                    "ticker": ticker,
                    "report_period": report_period,
                    "period": period,
                    "currency": currency,
                }

                for requested_item in line_items:
                    # Try direct match first, then normalized match
                    yf_name = None
                    if requested_item in all_statements:
                        yf_name = requested_item
                    elif requested_item in reverse_map:
                        yf_name = reverse_map[requested_item]

                    if yf_name and yf_name in all_statements:
                        series = all_statements[yf_name]
                        # Get value for this column
                        try:
                            val = series[col] if col in series.index else None
                        except (KeyError, IndexError):
                            val = None
                        if val is not None and not (
                            isinstance(val, float) and val != val
                        ):  # NaN check
                            item_data[requested_item] = float(val)
                        else:
                            item_data[requested_item] = None
                    else:
                        item_data[requested_item] = None

                results.append(LineItem(**item_data))
                count += 1

            return results

        except Exception as e:
            warnings.warn(
                f"YFinanceProvider.search_line_items({ticker}) failed: {e}"
            )
            return []

    def get_company_news(
        self, ticker: str, end_date: str, start_date: str | None = None, limit: int = 10
    ) -> list:
        """Fetch company news. Not supported by yfinance.

        Returns:
            Empty list (yfinance does not support structured news data).
        """
        return []

    def get_insider_trades(
        self, ticker: str, end_date: str, start_date: str | None = None, limit: int = 10
    ) -> list:
        """Fetch insider trades. Not supported by yfinance.

        Returns:
            Empty list (yfinance does not support structured insider trade data).
        """
        return []
