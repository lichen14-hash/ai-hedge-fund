import os
import time
from dotenv import load_dotenv

load_dotenv()
tushare_token = os.getenv("TUSHARE_TOKEN")

import tushare as ts
pro = ts.pro_api(tushare_token)

# 测试各个 Tushare API 的权限
print("=== 测试 Tushare API 权限 ===")

# 测试1: daily (通常免费)
print("\n1. daily API (价格数据):")
try:
    df = pro.daily(ts_code="002602.SZ", start_date="20250101", end_date="20250401")
    print(f"OK: {len(df)} rows")
except Exception as e:
    print(f"FAIL: {str(e)[:100]}")

time.sleep(1)

# 测试2: fina_indicator (需要权限)
print("\n2. fina_indicator API (财务指标):")
try:
    df = pro.fina_indicator(ts_code="002602.SZ", end_date="20250401", limit=10)
    print(f"OK: {len(df)} rows")
except Exception as e:
    print(f"FAIL: {str(e)[:100]}")

time.sleep(1)

# 测试3: income (需要权限)
print("\n3. income API (利润表):")
try:
    df = pro.income(ts_code="002602.SZ", end_date="20250401", limit=10)
    print(f"OK: {len(df)} rows")
except Exception as e:
    print(f"FAIL: {str(e)[:100]}")

time.sleep(1)

# 测试4: balancesheet (需要权限)
print("\n4. balancesheet API (资产负债表):")
try:
    df = pro.balancesheet(ts_code="002602.SZ", end_date="20250401", limit=10)
    print(f"OK: {len(df)} rows")
except Exception as e:
    print(f"FAIL: {str(e)[:100]}")

time.sleep(1)

# 测试5: cashflow (需要权限)
print("\n5. cashflow API (现金流量表):")
try:
    df = pro.cashflow(ts_code="002602.SZ", end_date="20250401", limit=10)
    print(f"OK: {len(df)} rows")
except Exception as e:
    print(f"FAIL: {str(e)[:100]}")

time.sleep(1)

# 测试6: stk_holdertrade (需要权限)
print("\n6. stk_holdertrade API (内部人士交易):")
try:
    df = pro.stk_holdertrade(ts_code="002602.SZ", start_date="20250101", end_date="20250401")
    print(f"OK: {len(df)} rows")
except Exception as e:
    print(f"FAIL: {str(e)[:100]}")

print("\n=== 总结 ===")
print("如果所有 fina_indicator / income / balancesheet / cashflow 都失败，")
print("说明当前 Tushare 账户权限不足。")
