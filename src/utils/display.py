from colorama import Fore, Style
from tabulate import tabulate
from .analysts import ANALYST_ORDER
import os
import json


def sort_agent_signals(signals):
    """Sort agent signals in a consistent order."""
    # Create order mapping from ANALYST_ORDER
    analyst_order = {display: idx for idx, (display, _) in enumerate(ANALYST_ORDER)}
    analyst_order["Risk Management"] = len(ANALYST_ORDER)  # Add Risk Management at the end

    return sorted(signals, key=lambda x: analyst_order.get(x[0], 999))


def print_trading_output(result: dict) -> None:
    """
    Print formatted trading results with colored tables for multiple tickers.

    Args:
        result (dict): Dictionary containing decisions and analyst signals for multiple tickers
    """
    decisions = result.get("decisions")
    if not decisions:
        print(f"{Fore.RED}No trading decisions available{Style.RESET_ALL}")
        return

    # Print decisions for each ticker
    for ticker, decision in decisions.items():
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Analysis for {Fore.CYAN}{ticker}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 50}{Style.RESET_ALL}")

        # Prepare analyst signals table for this ticker
        table_data = []
        for agent, signals in result.get("analyst_signals", {}).items():
            if ticker not in signals:
                continue
                
            # Skip Risk Management agent in the signals section
            if agent == "risk_management_agent":
                continue

            signal = signals[ticker]
            agent_name = agent.replace("_agent", "").replace("_", " ").title()
            signal_type = signal.get("signal", "").upper()
            confidence = signal.get("confidence", 0)

            signal_color = {
                "BULLISH": Fore.GREEN,
                "BEARISH": Fore.RED,
                "NEUTRAL": Fore.YELLOW,
            }.get(signal_type, Fore.WHITE)
            
            # Get reasoning if available
            reasoning_str = ""
            if "reasoning" in signal and signal["reasoning"]:
                reasoning = signal["reasoning"]
                
                # Handle different types of reasoning (string, dict, etc.)
                if isinstance(reasoning, str):
                    reasoning_str = reasoning
                elif isinstance(reasoning, dict):
                    # Convert dict to string representation
                    reasoning_str = json.dumps(reasoning, indent=2)
                else:
                    # Convert any other type to string
                    reasoning_str = str(reasoning)
                
                # Wrap long reasoning text to make it more readable
                wrapped_reasoning = ""
                current_line = ""
                # Use a fixed width of 60 characters to match the table column width
                max_line_length = 60
                for word in reasoning_str.split():
                    if len(current_line) + len(word) + 1 > max_line_length:
                        wrapped_reasoning += current_line + "\n"
                        current_line = word
                    else:
                        if current_line:
                            current_line += " " + word
                        else:
                            current_line = word
                if current_line:
                    wrapped_reasoning += current_line
                
                reasoning_str = wrapped_reasoning

            table_data.append(
                [
                    f"{Fore.CYAN}{agent_name}{Style.RESET_ALL}",
                    f"{signal_color}{signal_type}{Style.RESET_ALL}",
                    f"{Fore.WHITE}{confidence}%{Style.RESET_ALL}",
                    f"{Fore.WHITE}{reasoning_str}{Style.RESET_ALL}",
                ]
            )

        # Sort the signals according to the predefined order
        table_data = sort_agent_signals(table_data)

        print(f"\n{Fore.WHITE}{Style.BRIGHT}AGENT ANALYSIS:{Style.RESET_ALL} [{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(
            tabulate(
                table_data,
                headers=[f"{Fore.WHITE}Agent", "Signal", "Confidence", "Reasoning"],
                tablefmt="grid",
                colalign=("left", "center", "right", "left"),
            )
        )

        # Print Trading Decision Table
        action = decision.get("action", "").upper()
        action_color = {
            "BUY": Fore.GREEN,
            "SELL": Fore.RED,
            "HOLD": Fore.YELLOW,
            "COVER": Fore.GREEN,
            "SHORT": Fore.RED,
        }.get(action, Fore.WHITE)

        # Get reasoning and format it
        reasoning = decision.get("reasoning", "")
        # Wrap long reasoning text to make it more readable
        wrapped_reasoning = ""
        if reasoning:
            current_line = ""
            # Use a fixed width of 60 characters to match the table column width
            max_line_length = 60
            for word in reasoning.split():
                if len(current_line) + len(word) + 1 > max_line_length:
                    wrapped_reasoning += current_line + "\n"
                    current_line = word
                else:
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
            if current_line:
                wrapped_reasoning += current_line

        decision_data = [
            ["Action", f"{action_color}{action}{Style.RESET_ALL}"],
            ["Quantity", f"{action_color}{decision.get('quantity')}{Style.RESET_ALL}"],
            [
                "Confidence",
                f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}",
            ],
            ["Reasoning", f"{Fore.WHITE}{wrapped_reasoning}{Style.RESET_ALL}"],
        ]
        
        # 追加价格推荐字段
        current_price = decision.get('current_price', 0)
        target_price = decision.get('target_price', 0)
        stop_loss_price = decision.get('stop_loss', 0)
        
        if current_price > 0:
            decision_data.append(
                ["Current Price", f"{Fore.WHITE}${current_price:,.2f}{Style.RESET_ALL}"]
            )
        if target_price > 0:
            pct = ((target_price - current_price) / current_price * 100) if current_price > 0 else 0
            pct_color = Fore.GREEN if pct >= 0 else Fore.RED
            decision_data.append(
                ["Target Price", f"{Fore.GREEN}${target_price:,.2f}{Style.RESET_ALL} ({pct_color}{pct:+.1f}%{Style.RESET_ALL})"]
            )
        if stop_loss_price > 0:
            pct = ((stop_loss_price - current_price) / current_price * 100) if current_price > 0 else 0
            decision_data.append(
                ["Stop Loss", f"{Fore.RED}${stop_loss_price:,.2f}{Style.RESET_ALL} ({Fore.RED}{pct:+.1f}%{Style.RESET_ALL})"]
            )
        
        short_term = decision.get('short_term', '')
        medium_term = decision.get('medium_term', '')
        long_term = decision.get('long_term', '')
        
        if short_term:
            decision_data.append(
                ["Short Term (1W)", f"{Fore.CYAN}{short_term}{Style.RESET_ALL}"]
            )
        if medium_term:
            decision_data.append(
                ["Medium Term (1M)", f"{Fore.CYAN}{medium_term}{Style.RESET_ALL}"]
            )
        if long_term:
            decision_data.append(
                ["Long Term (3-6M)", f"{Fore.CYAN}{long_term}{Style.RESET_ALL}"]
            )
        
        print(f"\n{Fore.WHITE}{Style.BRIGHT}TRADING DECISION:{Style.RESET_ALL} [{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(tabulate(decision_data, tablefmt="grid", colalign=("left", "left")))

    # Print Portfolio Summary
    print(f"\n{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY:{Style.RESET_ALL}")
    portfolio_data = []
    
    # Extract portfolio manager reasoning (common for all tickers)
    portfolio_manager_reasoning = None
    for ticker, decision in decisions.items():
        if decision.get("reasoning"):
            portfolio_manager_reasoning = decision.get("reasoning")
            break
            
    analyst_signals = result.get("analyst_signals", {})
    for ticker, decision in decisions.items():
        action = decision.get("action", "").upper()
        action_color = {
            "BUY": Fore.GREEN,
            "SELL": Fore.RED,
            "HOLD": Fore.YELLOW,
            "COVER": Fore.GREEN,
            "SHORT": Fore.RED,
        }.get(action, Fore.WHITE)

        # Calculate analyst signal counts
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        if analyst_signals:
            for agent, signals in analyst_signals.items():
                if ticker in signals:
                    signal = signals[ticker].get("signal", "").upper()
                    if signal == "BULLISH":
                        bullish_count += 1
                    elif signal == "BEARISH":
                        bearish_count += 1
                    elif signal == "NEUTRAL":
                        neutral_count += 1

        portfolio_data.append(
            [
                f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
                f"{action_color}{action}{Style.RESET_ALL}",
                f"{action_color}{decision.get('quantity')}{Style.RESET_ALL}",
                f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}",
                f"{Fore.GREEN}{bullish_count}{Style.RESET_ALL}",
                f"{Fore.RED}{bearish_count}{Style.RESET_ALL}",
                f"{Fore.YELLOW}{neutral_count}{Style.RESET_ALL}",
            ]
        )

    headers = [
        f"{Fore.WHITE}Ticker",
        f"{Fore.WHITE}Action",
        f"{Fore.WHITE}Quantity",
        f"{Fore.WHITE}Confidence",
        f"{Fore.WHITE}Bullish",
        f"{Fore.WHITE}Bearish",
        f"{Fore.WHITE}Neutral",
    ]
    
    # Print the portfolio summary table
    print(
        tabulate(
            portfolio_data,
            headers=headers,
            tablefmt="grid",
            colalign=("left", "center", "right", "right", "center", "center", "center"),
        )
    )
    
    # Print Portfolio Manager's reasoning if available
    if portfolio_manager_reasoning:
        # Handle different types of reasoning (string, dict, etc.)
        reasoning_str = ""
        if isinstance(portfolio_manager_reasoning, str):
            reasoning_str = portfolio_manager_reasoning
        elif isinstance(portfolio_manager_reasoning, dict):
            # Convert dict to string representation
            reasoning_str = json.dumps(portfolio_manager_reasoning, indent=2)
        else:
            # Convert any other type to string
            reasoning_str = str(portfolio_manager_reasoning)
            
        # Wrap long reasoning text to make it more readable
        wrapped_reasoning = ""
        current_line = ""
        # Use a fixed width of 60 characters to match the table column width
        max_line_length = 60
        for word in reasoning_str.split():
            if len(current_line) + len(word) + 1 > max_line_length:
                wrapped_reasoning += current_line + "\n"
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
        if current_line:
            wrapped_reasoning += current_line
            
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Portfolio Strategy:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{wrapped_reasoning}{Style.RESET_ALL}")


def print_backtest_results(table_rows: list) -> None:
    """Print the backtest results in a nicely formatted table"""
    # Clear the screen
    os.system("cls" if os.name == "nt" else "clear")

    # Split rows into ticker rows and summary rows
    ticker_rows = []
    summary_rows = []

    for row in table_rows:
        if isinstance(row[1], str) and "PORTFOLIO SUMMARY" in row[1]:
            summary_rows.append(row)
        else:
            ticker_rows.append(row)

    # Display latest portfolio summary
    if summary_rows:
        # Pick the most recent summary by date (YYYY-MM-DD)
        latest_summary = max(summary_rows, key=lambda r: r[0])
        print(f"\n{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY:{Style.RESET_ALL}")

        # Adjusted indexes after adding Long/Short Shares
        position_str = latest_summary[7].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")
        cash_str     = latest_summary[8].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")
        total_str    = latest_summary[9].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")

        print(f"Cash Balance: {Fore.CYAN}${float(cash_str):,.2f}{Style.RESET_ALL}")
        print(f"Total Position Value: {Fore.YELLOW}${float(position_str):,.2f}{Style.RESET_ALL}")
        print(f"Total Value: {Fore.WHITE}${float(total_str):,.2f}{Style.RESET_ALL}")
        print(f"Portfolio Return: {latest_summary[10]}")
        if len(latest_summary) > 14 and latest_summary[14]:
            print(f"Benchmark Return: {latest_summary[14]}")

        # Display performance metrics if available
        if latest_summary[11]:  # Sharpe ratio
            print(f"Sharpe Ratio: {latest_summary[11]}")
        if latest_summary[12]:  # Sortino ratio
            print(f"Sortino Ratio: {latest_summary[12]}")
        if latest_summary[13]:  # Max drawdown
            print(f"Max Drawdown: {latest_summary[13]}")

    # Add vertical spacing
    print("\n" * 2)

    # Print the table with just ticker rows
    print(
        tabulate(
            ticker_rows,
            headers=[
                "Date",
                "Ticker",
                "Action",
                "Quantity",
                "Price",
                "Long Shares",
                "Short Shares",
                "Position Value",
            ],
            tablefmt="grid",
            colalign=(
                "left",    # Date
                "left",    # Ticker
                "center",  # Action
                "right",   # Quantity
                "right",   # Price
                "right",   # Long Shares
                "right",   # Short Shares
                "right",   # Position Value
            ),
        )
    )

    # Add vertical spacing
    print("\n" * 4)


def format_backtest_row(
    date: str,
    ticker: str,
    action: str,
    quantity: float,
    price: float,
    long_shares: float = 0,
    short_shares: float = 0,
    position_value: float = 0,
    is_summary: bool = False,
    total_value: float = None,
    return_pct: float = None,
    cash_balance: float = None,
    total_position_value: float = None,
    sharpe_ratio: float = None,
    sortino_ratio: float = None,
    max_drawdown: float = None,
    benchmark_return_pct: float | None = None,
) -> list[any]:
    """Format a row for the backtest results table"""
    # Color the action
    action_color = {
        "BUY": Fore.GREEN,
        "COVER": Fore.GREEN,
        "SELL": Fore.RED,
        "SHORT": Fore.RED,
        "HOLD": Fore.WHITE,
    }.get(action.upper(), Fore.WHITE)

    if is_summary:
        return_color = Fore.GREEN if return_pct >= 0 else Fore.RED
        benchmark_str = ""
        if benchmark_return_pct is not None:
            bench_color = Fore.GREEN if benchmark_return_pct >= 0 else Fore.RED
            benchmark_str = f"{bench_color}{benchmark_return_pct:+.2f}%{Style.RESET_ALL}"
        return [
            date,
            f"{Fore.WHITE}{Style.BRIGHT}PORTFOLIO SUMMARY{Style.RESET_ALL}",
            "",  # Action
            "",  # Quantity
            "",  # Price
            "",  # Long Shares
            "",  # Short Shares
            f"{Fore.YELLOW}${total_position_value:,.2f}{Style.RESET_ALL}",  # Total Position Value
            f"{Fore.CYAN}${cash_balance:,.2f}{Style.RESET_ALL}",  # Cash Balance
            f"{Fore.WHITE}${total_value:,.2f}{Style.RESET_ALL}",  # Total Value
            f"{return_color}{return_pct:+.2f}%{Style.RESET_ALL}",  # Return
            f"{Fore.YELLOW}{sharpe_ratio:.2f}{Style.RESET_ALL}" if sharpe_ratio is not None else "",  # Sharpe Ratio
            f"{Fore.YELLOW}{sortino_ratio:.2f}{Style.RESET_ALL}" if sortino_ratio is not None else "",  # Sortino Ratio
            f"{Fore.RED}{max_drawdown:.2f}%{Style.RESET_ALL}" if max_drawdown is not None else "",  # Max Drawdown (signed)
            benchmark_str,  # Benchmark (S&P 500)
        ]
    else:
        return [
            date,
            f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
            f"{action_color}{action.upper()}{Style.RESET_ALL}",
            f"{action_color}{quantity:,.0f}{Style.RESET_ALL}",
            f"{Fore.WHITE}{price:,.2f}{Style.RESET_ALL}",
            f"{Fore.GREEN}{long_shares:,.0f}{Style.RESET_ALL}",   # Long Shares
            f"{Fore.RED}{short_shares:,.0f}{Style.RESET_ALL}",    # Short Shares
            f"{Fore.YELLOW}{position_value:,.2f}{Style.RESET_ALL}",
        ]


# Translation dictionaries for Chinese reports
AGENT_NAME_TRANSLATIONS = {
    "Warren Buffett": "沃伦·巴菲特",
    "Charlie Munger": "查理·芒格",
    "Ben Graham": "本杰明·格雷厄姆",
    "Peter Lynch": "彼得·林奇",
    "Phil Fisher": "菲利普·费雪",
    "Cathie Wood": "凯瑟琳·伍德",
    "Stanley Druckenmiller": "斯坦利·德鲁肯米勒",
    "Bill Ackman": "比尔·阿克曼",
    "Michael Burry": "迈克尔·伯里",
    "Mohnish Pabrai": "莫尼什·帕布莱",
    "Nassim Taleb": "纳西姆·塔勒布",
    "Rakesh Jhunjhunwala": "拉凯什·金君瓦拉",
    "Aswath Damodaran": "阿斯沃斯·达摩达兰",
    "Technical Analysis": "技术面分析",
    "Fundamental Analysis": "基本面分析",
    "Sentiment Analysis": "情绪分析",
    "Valuation Analysis": "估值分析",
    "Growth Analysis": "成长性分析",
    "News Sentiment": "新闻情绪",
    "Risk Management": "风险管理",
}

SIGNAL_TRANSLATIONS = {
    "BULLISH": "看多",
    "BEARISH": "看空",
    "NEUTRAL": "中性",
}

ACTION_TRANSLATIONS = {
    "BUY": "买入",
    "SELL": "卖出",
    "HOLD": "持有",
    "SHORT": "做空",
    "COVER": "平仓",
}


def translate_reasonings_to_chinese(reasonings: dict[str, str], model_name: str = None, model_provider: str = None) -> dict[str, str]:
    """
    Use LLM to batch translate all analyst reasonings to Chinese.
    
    Args:
        reasonings: dict of {agent_name: reasoning_text}
        model_name: LLM model name
        model_provider: LLM provider name
    
    Returns:
        dict of {agent_name: translated_reasoning}
    """
    if not reasonings or not model_name:
        return reasonings
    
    try:
        from src.llm.models import get_model
        
        llm = get_model(model_name, model_provider)
        
        # Build a single prompt to translate all reasonings at once (efficient)
        prompt_parts = []
        agent_keys = []
        for i, (agent, reasoning) in enumerate(reasonings.items()):
            if reasoning and reasoning.strip():
                agent_keys.append(agent)
                prompt_parts.append(f"[{i+1}] {reasoning}")
        
        if not prompt_parts:
            return reasonings
        
        combined_text = "\n\n".join(prompt_parts)
        
        from langchain_core.messages import HumanMessage
        
        prompt = HumanMessage(content=f"""请将以下投资分析文本翻译成中文。保持编号格式不变，每段翻译之间用空行分隔。只输出翻译结果，不要添加任何解释。

{combined_text}""")
        
        result = llm.invoke([prompt])
        translated_text = result.content
        
        # Parse translated results back by numbering
        translated = dict(reasonings)  # copy original
        import re
        # Split by [number] pattern
        parts = re.split(r'\[(\d+)\]\s*', translated_text)
        # parts will be like: ['', '1', 'translated1', '2', 'translated2', ...]
        for j in range(1, len(parts) - 1, 2):
            idx = int(parts[j]) - 1
            text = parts[j + 1].strip()
            # 确保翻译结果是单行且不含管道符
            text = text.replace("\n", " ").replace("|", " ")
            if 0 <= idx < len(agent_keys):
                translated[agent_keys[idx]] = text
        
        return translated
    except Exception as e:
        print(f"Warning: Failed to translate reasonings: {e}")
        return reasonings  # Return original on failure


def format_dict_reasoning(agent_name: str, reasoning_dict: dict) -> str:
    """
    将 dict 类型的 reasoning 格式化为单行紧凑描述文本。
    
    Args:
        agent_name: 分析师名称
        reasoning_dict: reasoning 字典
    
    Returns:
        单行中文描述文本
    """
    if not isinstance(reasoning_dict, dict):
        return str(reasoning_dict)
    
    parts = []
    
    # Technical Analyst - 数据结构: {trend_following: {signal, confidence, metrics}, mean_reversion: {...}, ...}
    if "technical" in agent_name.lower():
        tech_keys = ["trend_following", "mean_reversion", "momentum", "volatility", "statistical_arbitrage"]
        key_cn_map = {
            "trend_following": "趋势跟踪",
            "mean_reversion": "均值回归",
            "momentum": "动量",
            "volatility": "波动性",
            "statistical_arbitrage": "统计套利"
        }
        for key in tech_keys:
            value = reasoning_dict.get(key, {})
            if isinstance(value, dict):
                signal = value.get("signal", "")
                metrics = value.get("metrics", {})
                metric_str = ""
                if metrics:
                    if key == "trend_following" and "adx" in metrics:
                        metric_str = f"(ADX={metrics['adx']:.2f})"
                    elif key == "mean_reversion" and "rsi_14" in metrics:
                        metric_str = f"(RSI14={metrics['rsi_14']:.1f})"
                    elif key == "momentum" and "momentum_1m" in metrics:
                        metric_str = f"(1月动量={metrics['momentum_1m']:.2f})"
                    elif key == "volatility" and "historical_volatility" in metrics:
                        metric_str = f"(历史波动率={metrics['historical_volatility']:.2f})"
                
                signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(str(signal).lower(), signal)
                parts.append(f"{key_cn_map.get(key, key)}: {signal_cn}{metric_str}")
    
    # Fundamentals Analyst - 数据结构: {profitability_signal: {signal, details}, growth_signal: {...}, ...}
    elif "fundamental" in agent_name.lower():
        fund_keys = {
            "profitability_signal": "盈利能力",
            "growth_signal": "增长",
            "financial_health_signal": "财务健康",
            "price_ratios_signal": "价格比率"
        }
        for key, key_cn in fund_keys.items():
            value = reasoning_dict.get(key, {})
            if isinstance(value, dict):
                signal = value.get("signal", "")
                details = value.get("details", "")
                signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(str(signal).lower(), signal)
                detail_str = f"({details})" if details else ""
                parts.append(f"{key_cn}: {signal_cn}{detail_str}")
    
    # Growth Analyst
    elif "growth" in agent_name.lower() or agent_name == "Growth Analysis":
        final = reasoning_dict.get("final_analysis", {})
        signal = final.get("signal", "")
        score = final.get("score", 0)
        signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(signal.lower(), signal)
        
        # 提取关键指标
        metrics = []
        if "operating_margin" in reasoning_dict:
            metrics.append(f"运营利润率:{reasoning_dict['operating_margin']:.1f}%")
        if "debt_to_equity" in reasoning_dict:
            metrics.append(f"负债权益比:{reasoning_dict['debt_to_equity']:.2f}")
        if "revenue_growth" in reasoning_dict:
            metrics.append(f"收入增长:{reasoning_dict['revenue_growth']:.1f}%")
        
        metric_str = f"({' | '.join(metrics)})" if metrics else ""
        parts.append(f"成长性: {signal_cn}(得分:{score:.1f}){metric_str}")
    
    # Sentiment Analyst - 数据结构: {insider_trading: {signal, confidence, metrics: {total_trades, bullish_trades, bearish_trades}}, news_sentiment: {...}, combined_analysis: {...}}
    elif "sentiment" in agent_name.lower() and "news" not in agent_name.lower():
        insider = reasoning_dict.get("insider_trading", {})
        news = reasoning_dict.get("news_sentiment", {})
        
        insider_signal = insider.get("signal", "")
        insider_signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(str(insider_signal).lower(), insider_signal)
        insider_metrics = insider.get("metrics", {})
        buy_count = insider_metrics.get("bullish_trades", 0)
        sell_count = insider_metrics.get("bearish_trades", 0)
        
        news_signal = news.get("signal", "")
        news_signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(str(news_signal).lower(), news_signal)
        news_metrics = news.get("metrics", {})
        article_count = news_metrics.get("total_articles", 0)
        
        parts.append(f"内部交易: {insider_signal_cn}({buy_count}买入/{sell_count}卖出)")
        parts.append(f"新闻情绪: {news_signal_cn}({article_count}篇文章)")
    
    # Valuation Analyst
    elif "valuation" in agent_name.lower() or agent_name == "Valuation Analysis":
        if "error" in reasoning_dict:
            parts.append(f"错误: {reasoning_dict['error']}")
        else:
            signal = reasoning_dict.get("signal", "")
            signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(signal.lower(), signal)
            
            # 提取估值指标
            metrics = []
            if "dcf_valuation" in reasoning_dict:
                dcf = reasoning_dict["dcf_valuation"]
                if isinstance(dcf, dict) and "intrinsic_value" in dcf:
                    metrics.append(f"DCF估值:${dcf['intrinsic_value']:.2f}")
            if "pe_ratio" in reasoning_dict:
                metrics.append(f"PE:{reasoning_dict['pe_ratio']:.2f}")
            if "pb_ratio" in reasoning_dict:
                metrics.append(f"PB:{reasoning_dict['pb_ratio']:.2f}")
            
            metric_str = f"({' | '.join(metrics)})" if metrics else ""
            parts.append(f"估值: {signal_cn}{metric_str}")
    
    # News Sentiment - 数据结构: {news_sentiment: {signal, confidence, metrics: {total_articles, bullish_articles, bearish_articles, neutral_articles}}}
    elif "news" in agent_name.lower():
        news_data = reasoning_dict.get("news_sentiment", reasoning_dict)
        signal = news_data.get("signal", "")
        signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(str(signal).lower(), signal)
        
        news_metrics = news_data.get("metrics", {})
        bullish = news_metrics.get("bullish_articles", 0)
        bearish = news_metrics.get("bearish_articles", 0)
        neutral = news_metrics.get("neutral_articles", 0)
        total = news_metrics.get("total_articles", 0)
        
        parts.append(f"新闻情绪: {signal_cn}(共{total}篇: {bullish}篇看涨/{bearish}篇看跌/{neutral}篇中性)")
    
    # 默认处理：提取关键字段
    if not parts:
        # 尝试提取 signal 和关键指标
        signal = reasoning_dict.get("signal", "")
        if signal:
            signal_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(signal.lower(), signal)
            parts.append(f"信号: {signal_cn}")
        
        # 添加其他关键数值
        for key, value in reasoning_dict.items():
            if key not in ["signal", "details"] and isinstance(value, (int, float)):
                parts.append(f"{key}: {value:.2f}")
    
    result = "; ".join(parts)
    # 确保没有换行符和管道符
    result = result.replace("\n", " ").replace("|", " ")
    return result if result else str(reasoning_dict)


def generate_markdown_report(
    result: dict,
    ticker_list: list,
    model_name: str = "",
    initial_cash: float = 300000,
    model_name_for_translate: str = None,
    model_provider_for_translate: str = None
) -> str:
    """
    Generate a structured Chinese Markdown report from analysis results.

    Args:
        result: Dictionary containing decisions and analyst_signals
        ticker_list: List of ticker symbols
        model_name: Name of the model used for analysis
        initial_cash: Initial cash position
        model_name_for_translate: LLM model name for translating reasonings
        model_provider_for_translate: LLM provider name for translating reasonings

    Returns:
        Complete Markdown report as a string
    """
    from datetime import datetime

    decisions = result.get("decisions", {})
    analyst_signals = result.get("analyst_signals", {})

    if not decisions:
        return "# 错误\n\n未找到交易决策数据。"

    # Collect all reasonings for translation
    all_reasonings = {}
    
    # Collect portfolio manager reasonings from decisions
    for ticker in ticker_list:
        if ticker in decisions:
            decision = decisions[ticker]
            reasoning = decision.get("reasoning", "")
            if isinstance(reasoning, dict):
                reasoning = json.dumps(reasoning, ensure_ascii=False, indent=2)
            elif not isinstance(reasoning, str):
                reasoning = str(reasoning)
            if reasoning and reasoning.strip():
                all_reasonings[f"__portfolio_{ticker}"] = reasoning
            
            # 收集时间策略文本用于翻译
            short_term = decision.get('short_term', '')
            medium_term = decision.get('medium_term', '')
            long_term = decision.get('long_term', '')
            if short_term:
                all_reasonings[f"__short_term_{ticker}"] = short_term
            if medium_term:
                all_reasonings[f"__medium_term_{ticker}"] = medium_term
            if long_term:
                all_reasonings[f"__long_term_{ticker}"] = long_term
    
    # Collect analyst reasonings
    for agent, signals in analyst_signals.items():
        for ticker in ticker_list:
            if ticker in signals:
                signal = signals[ticker]
                if "reasoning" in signal and signal["reasoning"]:
                    r = signal["reasoning"]
                    if isinstance(r, str):
                        reasoning_str = r
                    elif isinstance(r, dict):
                        # 使用单行格式化的中文描述替代多行JSON
                        agent_display_name = agent.replace("_agent", "").replace("_", " ").title()
                        reasoning_str = format_dict_reasoning(agent_display_name, r)
                    else:
                        reasoning_str = str(r)
                    if reasoning_str.strip():
                        all_reasonings[f"{agent}_{ticker}"] = reasoning_str
    
    # Translate all reasonings in one batch
    translated_reasonings = translate_reasonings_to_chinese(
        all_reasonings,
        model_name_for_translate,
        model_provider_for_translate
    )

    report_lines = []

    for ticker in ticker_list:
        if ticker not in decisions:
            continue

        decision = decisions[ticker]
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Report header
        report_lines.append(f"# {ticker} 股票分析报告")
        report_lines.append("")
        report_lines.append(f"**分析时间**: {current_time}")
        report_lines.append(f"**模型**: {model_name}")
        report_lines.append(f"**分析师**: 全部 19 位")
        report_lines.append(f"**初始本金**: ${initial_cash:,.0f}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Section 1: Final trading decision
        action = decision.get("action", "").upper()
        action_cn = ACTION_TRANSLATIONS.get(action, action)
        quantity = decision.get("quantity", 0)
        confidence = decision.get("confidence", 0)

        # Get translated reasoning for portfolio manager
        portfolio_key = f"__portfolio_{ticker}"
        reasoning = translated_reasonings.get(portfolio_key, decision.get("reasoning", ""))
        if isinstance(reasoning, dict):
            reasoning = json.dumps(reasoning, ensure_ascii=False, indent=2)
        elif not isinstance(reasoning, str):
            reasoning = str(reasoning)

        report_lines.append("## 一、最终交易决策")
        report_lines.append("")
        report_lines.append("| 项目 | 内容 |")
        report_lines.append("|------|------|")
        report_lines.append(f"| 股票代码 | {ticker} |")
        report_lines.append(f"| 操作建议 | {action_cn} |")
        report_lines.append(f"| 建议数量 | {quantity} 股 |")
        report_lines.append(f"| 综合置信度 | {confidence:.1f}% |")
        report_lines.append(f"| 决策理由 | {reasoning} |")
        
        # 追加价格推荐行
        current_price = decision.get('current_price', 0)
        target_price = decision.get('target_price', 0)
        stop_loss_price = decision.get('stop_loss', 0)
        
        if current_price > 0:
            report_lines.append(f"| 当前价格 | ${current_price:,.2f} |")
        if target_price > 0 and current_price > 0:
            pct = (target_price - current_price) / current_price * 100
            report_lines.append(f"| 目标价格 | ${target_price:,.2f} ({pct:+.1f}%) |")
        if stop_loss_price > 0 and current_price > 0:
            pct = (stop_loss_price - current_price) / current_price * 100
            report_lines.append(f"| 止损价格 | ${stop_loss_price:,.2f} ({pct:+.1f}%) |")
        
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")
        
        # 分时间段操作建议章节
        short_term = decision.get('short_term', '')
        medium_term = decision.get('medium_term', '')
        long_term = decision.get('long_term', '')
        
        if short_term or medium_term or long_term:
            report_lines.append("### 分时间段操作建议")
            report_lines.append("")
            report_lines.append("| 时间范围 | 操作建议 |")
            report_lines.append("|---------|---------|")
            if short_term:
                translated_short = translated_reasonings.get(f"__short_term_{ticker}", short_term)
                report_lines.append(f"| 短期 (1周) | {translated_short} |")
            if medium_term:
                translated_medium = translated_reasonings.get(f"__medium_term_{ticker}", medium_term)
                report_lines.append(f"| 中期 (1月) | {translated_medium} |")
            if long_term:
                translated_long = translated_reasonings.get(f"__long_term_{ticker}", long_term)
                report_lines.append(f"| 长期 (3-6月) | {translated_long} |")
            report_lines.append("")

        # Section 2: Signal distribution
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        if analyst_signals:
            for agent, signals in analyst_signals.items():
                if ticker in signals:
                    signal = signals[ticker].get("signal", "").upper()
                    if signal == "BULLISH":
                        bullish_count += 1
                    elif signal == "BEARISH":
                        bearish_count += 1
                    elif signal == "NEUTRAL":
                        neutral_count += 1

        report_lines.append("## 二、分析师信号分布")
        report_lines.append("")
        report_lines.append("| 看多 (Bullish) | 看空 (Bearish) | 中性 (Neutral) |")
        report_lines.append("|:-:|:-:|:-:|")
        report_lines.append(f"| {bullish_count} 位 | {bearish_count} 位 | {neutral_count} 位 |")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Section 3: Detailed analyst analysis
        report_lines.append("## 三、各分析师详细分析")
        report_lines.append("")
        report_lines.append("| 分析师 | 信号 | 置信度 | 分析理由 |")
        report_lines.append("|--------|------|--------|----------|")

        # Collect agent data for sorting
        agent_data = []
        for agent, signals in analyst_signals.items():
            if ticker not in signals:
                continue

            # Skip Risk Management agent in the signals section
            if agent == "risk_management_agent":
                continue

            signal = signals[ticker]
            agent_name = agent.replace("_agent", "").replace("_", " ").title()
            signal_type = signal.get("signal", "").upper()
            confidence_val = signal.get("confidence", 0)

            # Get translated reasoning
            reasoning_key = f"{agent}_{ticker}"
            reasoning_str = translated_reasonings.get(reasoning_key, "")
            if not reasoning_str:
                # Fallback to original reasoning if translation not available
                if "reasoning" in signal and signal["reasoning"]:
                    r = signal["reasoning"]
                    if isinstance(r, str):
                        reasoning_str = r
                    elif isinstance(r, dict):
                        # 使用单行格式化的中文描述替代多行JSON
                        reasoning_str = format_dict_reasoning(agent_name, r)
                    else:
                        reasoning_str = str(r)

            agent_data.append([
                agent_name,
                signal_type,
                confidence_val,
                reasoning_str
            ])

        # Sort using the existing sort_agent_signals logic
        def get_agent_sort_key(item):
            analyst_order = {display: idx for idx, (display, _) in enumerate(ANALYST_ORDER)}
            analyst_order["Risk Management"] = len(ANALYST_ORDER)
            return analyst_order.get(item[0], 999)

        agent_data.sort(key=get_agent_sort_key)

        # Add rows to report
        for agent_name, signal_type, confidence_val, reasoning_str in agent_data:
            # Use English agent name (no translation)
            signal_cn = SIGNAL_TRANSLATIONS.get(signal_type, signal_type)
            # 确保 reasoning 是单行且不含管道符
            if isinstance(reasoning_str, str):
                reasoning_str = reasoning_str.replace("\n", " ").replace("|", " ")
            report_lines.append(f"| {agent_name} | {signal_cn} | {confidence_val}% | {reasoning_str} |")

        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Section 4: Portfolio strategy
        report_lines.append("## 四、投资组合策略")
        report_lines.append("")

        # Extract portfolio manager reasoning
        portfolio_reasoning = ""
        if reasoning:
            portfolio_reasoning = reasoning

        if portfolio_reasoning:
            report_lines.append(portfolio_reasoning)
        else:
            report_lines.append("（无额外策略说明）")

        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Footer
        report_lines.append("*报告由 AI 对冲基金分析系统自动生成，仅供参考，不构成投资建议。*")

    return "\n".join(report_lines)
