import akshare as ak
import logging
import traceback

# 启用详细的日志输出
logging.basicConfig(level=logging.DEBUG)

# 测试1: 尝试调用 stock_financial_report_sina，捕获更多信息
print("=== 测试1: 直接调用 ak.stock_financial_report_sina ===")
try:
    df = ak.stock_financial_report_sina(stock='002602', symbol='利润表')
    print(f"成功: {len(df)} rows")
except Exception as e:
    print(f"错误: {type(e).__name__}: {e}")
    traceback.print_exc()

print("\n=== 测试2: 尝试调用 ak.stock_zh_a_hist ===")
try:
    df = ak.stock_zh_a_hist(symbol='002602', period='daily', start_date='20250101', end_date='20250401')
    print(f"成功: {len(df)} rows")
except Exception as e:
    print(f"错误: {type(e).__name__}: {e}")
    traceback.print_exc()

print("\n=== 测试3: 尝试调用 ak.stock_individual_info_em ===")
try:
    df = ak.stock_individual_info_em(symbol='002602')
    print(f"成功: {len(df)} rows")
except Exception as e:
    print(f"错误: {type(e).__name__}: {e}")
    traceback.print_exc()
