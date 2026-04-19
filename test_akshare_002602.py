import akshare as ak
import time

# 测试1: 利润表
print('=== 测试利润表 ===')
try:
    df = ak.stock_financial_report_sina(stock='002602', symbol='利润表')
    print(f'利润表: {len(df)} rows')
    print(df.head(2))
except Exception as e:
    print(f'利润表失败: {type(e).__name__}: {e}')

time.sleep(2)

# 测试2: 资产负债表
print('\n=== 测试资产负债表 ===')
try:
    df = ak.stock_financial_report_sina(stock='002602', symbol='资产负债表')
    print(f'资产负债表: {len(df)} rows')
    print(df.head(2))
except Exception as e:
    print(f'资产负债表失败: {type(e).__name__}: {e}')

time.sleep(2)

# 测试3: 价格数据
print('\n=== 测试日线价格 ===')
try:
    df = ak.stock_zh_a_hist(symbol='002602', period='daily', start_date='20250101', end_date='20250401')
    print(f'价格数据: {len(df)} rows')
    print(df.head(2))
except Exception as e:
    print(f'价格失败: {type(e).__name__}: {e}')

time.sleep(2)

# 测试4: 个股信息（市值）
print('\n=== 测试个股信息 ===')
try:
    df = ak.stock_individual_info_em(symbol='002602')
    print(df)
except Exception as e:
    print(f'个股信息失败: {type(e).__name__}: {e}')

time.sleep(2)

# 测试5: 财务指标
print('\n=== 测试财务指标 ===')
try:
    df = ak.stock_financial_analysis_indicator(symbol='002602')
    print(f'财务指标: {len(df)} rows')
    print(df.head(2))
except Exception as e:
    print(f'财务指标失败: {type(e).__name__}: {e}')

time.sleep(2)

# 测试6: 对比 600519
print('\n=== 测试 600519 利润表（对比） ===')
try:
    df = ak.stock_financial_report_sina(stock='600519', symbol='利润表')
    print(f'600519 利润表: {len(df)} rows')
    print(df.head(2))
except Exception as e:
    print(f'600519 利润表失败: {type(e).__name__}: {e}')
