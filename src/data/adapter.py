"""
Unified data source adapter layer.
Routes data requests to appropriate providers based on market type,
with automatic failover between providers.
"""
import logging
import os
from typing import Optional
from src.data.models import (
    Price, FinancialMetrics, CompanyNews, InsiderTrade, LineItem,
    MarketType, detect_market
)
from src.data.providers.akshare_provider import AKShareProvider
from src.data.providers.yfinance_provider import YFinanceProvider
from src.data.providers.financial_datasets_provider import FinancialDatasetsProvider
from src.data.providers.tushare_provider import TushareProvider

logger = logging.getLogger(__name__)


class DataSourceAdapter:
    """Unified adapter that routes requests to appropriate data providers."""
    
    def __init__(self):
        # Lazy initialization - create providers on first use
        self._akshare = None
        self._yfinance = None
        self._financial_datasets = None
        self._tushare = None
        
        # Provider priority by market
        self._provider_priority = {
            MarketType.US: ['financial_datasets', 'yfinance'],
            MarketType.CN_SH: ['akshare', 'tushare'],
            MarketType.CN_SZ: ['akshare', 'tushare'],
            MarketType.HK: ['akshare', 'yfinance'],
        }
    
    @property
    def akshare(self):
        if self._akshare is None:
            self._akshare = AKShareProvider()
        return self._akshare
    
    @property
    def yfinance(self):
        if self._yfinance is None:
            self._yfinance = YFinanceProvider()
        return self._yfinance
    
    @property
    def financial_datasets(self):
        if self._financial_datasets is None:
            self._financial_datasets = FinancialDatasetsProvider()
        return self._financial_datasets
    
    @property
    def tushare(self):
        if self._tushare is None:
            token = os.getenv('TUSHARE_TOKEN')
            if token:
                self._tushare = TushareProvider(token)
            else:
                logger.warning("TUSHARE_TOKEN not set, TushareProvider will not be available")
        return self._tushare
    
    def _get_provider(self, name: str):
        """Get provider instance by name."""
        providers = {
            'akshare': self.akshare,
            'yfinance': self.yfinance,
            'financial_datasets': self.financial_datasets,
            'tushare': self.tushare,
        }
        return providers.get(name)
    
    def _try_providers(self, ticker: str, method_name: str, *args, **kwargs):
        """Try providers in priority order, return first successful result."""
        market = detect_market(ticker)
        provider_names = self._provider_priority.get(market, ['financial_datasets'])
        
        for provider_name in provider_names:
            provider = self._get_provider(provider_name)
            if provider is None:
                continue
            method = getattr(provider, method_name, None)
            if method is None:
                continue
            try:
                result = method(ticker, *args, **kwargs)
                if result is not None and (not isinstance(result, list) or len(result) > 0):
                    logger.info(f"[{provider_name}] {method_name}({ticker}) succeeded")
                    return result
            except Exception as e:
                logger.warning(f"[{provider_name}] {method_name}({ticker}) failed: {e}")
                continue
        
        logger.warning(f"All providers failed for {method_name}({ticker})")
        # Return appropriate empty value
        if method_name == 'get_market_cap':
            return None
        return []
    
    def get_prices(self, ticker: str, start_date: str, end_date: str, **kwargs) -> list[Price]:
        """Fetch OHLCV price data.
        
        Args:
            ticker: Stock ticker (e.g., '600519.SH', 'AAPL', '0700.HK')
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            **kwargs: Additional arguments (e.g., interval for AKShare)
        
        Returns:
            List of Price objects.
        """
        return self._try_providers(ticker, 'get_prices', start_date, end_date, **kwargs)
    
    def get_financial_metrics(self, ticker: str, end_date: str, period: str = "ttm", limit: int = 10) -> list[FinancialMetrics]:
        """Fetch financial metrics.
        
        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'
            period: 'ttm' | 'annual' | 'quarterly'
            limit: Max number of records
        
        Returns:
            List of FinancialMetrics objects.
        """
        return self._try_providers(ticker, 'get_financial_metrics', end_date, period=period, limit=limit)
    
    def get_company_news(self, ticker: str, end_date: str, start_date: str = None, limit: int = 50) -> list[CompanyNews]:
        """Fetch company news.
        
        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'
            start_date: Start date 'YYYY-MM-DD' (optional)
            limit: Max number of news items
        
        Returns:
            List of CompanyNews objects.
        """
        market = detect_market(ticker)
        
        # Try providers in priority order with correct parameter mapping
        provider_names = self._provider_priority.get(market, ['financial_datasets'])
        
        for provider_name in provider_names:
            provider = self._get_provider(provider_name)
            if provider is None:
                continue
            
            try:
                # Different providers have different parameter orders
                if provider_name == 'akshare':
                    # AKShare: get_company_news(ticker, start_date, end_date, limit)
                    result = provider.get_company_news(ticker, start_date or '', end_date, limit)
                elif provider_name == 'financial_datasets':
                    # FinancialDatasets: get_company_news(ticker, start_date, end_date, limit)
                    result = provider.get_company_news(ticker, start_date or '', end_date, limit)
                else:
                    # YFinance and others: get_company_news(ticker, end_date, start_date, limit)
                    result = provider.get_company_news(ticker, end_date, start_date, limit)
                
                if result is not None and len(result) > 0:
                    logger.info(f"[{provider_name}] get_company_news({ticker}) succeeded")
                    return result
            except Exception as e:
                logger.warning(f"[{provider_name}] get_company_news({ticker}) failed: {e}")
                continue
        
        logger.warning(f"All providers failed for get_company_news({ticker})")
        return []
    
    def get_insider_trades(self, ticker: str, end_date: str, start_date: str = None, limit: int = 50) -> list[InsiderTrade]:
        """Fetch insider trades.
        
        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'
            start_date: Start date 'YYYY-MM-DD' (optional)
            limit: Max number of records
        
        Returns:
            List of InsiderTrade objects.
        """
        market = detect_market(ticker)
        
        # Try providers in priority order with correct parameter mapping
        provider_names = self._provider_priority.get(market, ['financial_datasets'])
        
        for provider_name in provider_names:
            provider = self._get_provider(provider_name)
            if provider is None:
                continue
            
            try:
                # Different providers have different parameter orders
                if provider_name == 'akshare':
                    # AKShare: get_insider_trades(ticker, start_date, end_date, limit)
                    result = provider.get_insider_trades(ticker, start_date or '', end_date, limit)
                elif provider_name == 'financial_datasets':
                    # FinancialDatasets: get_insider_trades(ticker, start_date, end_date, limit)
                    result = provider.get_insider_trades(ticker, start_date or '', end_date, limit)
                else:
                    # YFinance and others: get_insider_trades(ticker, end_date, start_date, limit)
                    result = provider.get_insider_trades(ticker, end_date, start_date, limit)
                
                if result is not None and len(result) > 0:
                    logger.info(f"[{provider_name}] get_insider_trades({ticker}) succeeded")
                    return result
            except Exception as e:
                logger.warning(f"[{provider_name}] get_insider_trades({ticker}) failed: {e}")
                continue
        
        logger.warning(f"All providers failed for get_insider_trades({ticker})")
        return []
    
    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Fetch total market capitalization.
        
        Args:
            ticker: Stock ticker
            end_date: End date 'YYYY-MM-DD'
        
        Returns:
            Market cap as float, or None if unavailable.
        """
        return self._try_providers(ticker, 'get_market_cap', end_date)
    
    def get_valuation_params(self, ticker: str) -> dict:
        """Get dynamic valuation parameters (beta, risk-free rate).
        
        Args:
            ticker: Stock ticker
        
        Returns:
            Dict with 'beta', 'risk_free_rate', 'market_risk_premium'.
        """
        market = detect_market(ticker)
        provider_names = self._provider_priority.get(market, ['financial_datasets'])
        
        for provider_name in provider_names:
            provider = self._get_provider(provider_name)
            if provider is None:
                continue
            method = getattr(provider, 'get_valuation_params', None)
            if method is None:
                continue
            try:
                result = method(ticker)
                if result is not None and isinstance(result, dict):
                    logger.info(f"[{provider_name}] get_valuation_params({ticker}) succeeded")
                    return result
            except Exception as e:
                logger.warning(f"[{provider_name}] get_valuation_params({ticker}) failed: {e}")
                continue
        
        logger.warning(f"All providers failed for get_valuation_params({ticker})")
        return {
            "beta": 1.0,
            "risk_free_rate": 0.045,
            "market_risk_premium": 0.06,
        }
    
    def search_line_items(self, ticker: str, line_items: list[str], end_date: str, period: str = "annual", limit: int = 10) -> list[LineItem]:
        """Search for specific financial line items.
        
        Args:
            ticker: Stock ticker
            line_items: List of line item names to search for
            end_date: End date 'YYYY-MM-DD'
            period: 'annual' | 'quarterly'
            limit: Max number of records
        
        Returns:
            List of LineItem objects.
        """
        return self._try_providers(ticker, 'search_line_items', line_items, end_date, period=period, limit=limit)
