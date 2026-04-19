import akshare as ak
import time
import requests

print("=== 诊断 AKShare 连接 ===")

# 测试1: 直接 URL 连接测试
print("\n1. 测试 AKShare Sina 数据源连接:")
try:
    # AKShare stock_financial_report_sina 使用新浪财经数据源
    # 尝试连接新浪
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    # 这是 AKShare 调用的 URL
    url = "https://vip.stock.finance.sina.com.cn/q/go.php"
    params = {"symbol": "sz002602"}
    
    response = requests.get(url, params=params, headers=headers, timeout=10)
    print(f"状态码: {response.status_code}")
    print(f"响应长度: {len(response.text)} chars")
    print(f"前100字符: {response.text[:100]}")
except Exception as e:
    print(f"错误: {type(e).__name__}: {e}")

time.sleep(2)

# 测试2: 直接调用 AKShare，加长超时
print("\n2. 测试 AKShare stock_financial_report_sina（加长超时）:")
try:
    # 使用更长的超时时间
    import socket
    socket.setdefaulttimeout(30)
    df = ak.stock_financial_report_sina(stock="002602", symbol="利润表")
    print(f"成功: {len(df)} rows")
except Exception as e:
    print(f"错误: {type(e).__name__}: {str(e)[:150]}")

time.sleep(2)

# 测试3: 尝试 600519 的对比
print("\n3. 测试其他股票 600519 的利润表:")
try:
    df = ak.stock_financial_report_sina(stock="600519", symbol="利润表")
    print(f"成功: {len(df)} rows")
except Exception as e:
    print(f"错误: {type(e).__name__}: {str(e)[:150]}")

print("\n=== 分析 ===")
print("如果 002602 和 600519 都失败，说明是 AKShare 服务问题或网络问题。")
print("如果只有 002602 失败，可能是该股票数据源问题。")
