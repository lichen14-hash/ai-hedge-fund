import os
import sys
import time

# 确保加载环境变量
from dotenv import load_dotenv
load_dotenv()

tushare_token = os.getenv("TUSHARE_TOKEN")
print(f"TUSHARE_TOKEN: {tushare_token[:20]}..." if tushare_token else "TUSHARE_TOKEN not found")

# 测试 Tushare
print("\n=== 测试 Tushare 002602 ===")
try:
    import tushare as ts
    pro = ts.pro_api(tushare_token)
    
    # 测试1: 股票基本信息
    print("\n测试 stock_basic:")
    df = pro.stock_basic(ts_code="002602.SZ")
    print(df)
    
    time.sleep(1)
    
    # 测试2: 日线数据
    print("\n测试 daily:")
    df = pro.daily(ts_code="002602.SZ", start_date="20250101", end_date="20250401")
    print(f"daily: {len(df)} rows")
    if len(df) > 0:
        print(df.head(2))
    
    time.sleep(1)
    
    # 测试3: 财务指标
    print("\n测试 fina_mainbz:")
    df = pro.fina_mainbz(ts_code="002602.SZ")
    print(f"fina_mainbz: {len(df)} rows")
    if len(df) > 0:
        print(df.head(2))
    
except Exception as e:
    import traceback
    print(f"错误: {type(e).__name__}: {e}")
    traceback.print_exc()
