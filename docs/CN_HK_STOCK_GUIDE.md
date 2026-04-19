# A 股 / 港股分析使用指南

## 概述

本项目支持 A 股（上海/深圳）和港股的分析能力，基于 AKShare + Tushare + yfinance 多数据源架构。通过统一的 Ticker 格式和智能数据源降级机制，为投资者提供全面的股票分析服务。

## 快速开始

### 环境配置

在 `.env` 文件中配置以下环境变量：

1. **LLM 密钥（必选其一）**：推荐使用 `ZHIPUAI_API_KEY`（智谱AI，国内访问友好）
   - 获取地址：https://open.bigmodel.cn/
   - 推荐模型：`glm-4-plus`（JSON 输出质量最佳）

2. **数据源配置（可选但推荐）**：
   - `TUSHARE_TOKEN` — Tushare Pro 备用数据源，获取地址：https://tushare.pro/
   - AKShare 和 yfinance 无需配置，开箱即用

### Ticker 格式约定

| 市场 | 格式 | 示例 | 说明 |
|------|------|------|------|
| A 股上证 | `代码.SH` | `600519.SH` | 贵州茅台 |
| A 股深证 | `代码.SZ` | `000858.SZ` | 五粮液 |
| 港股 | `代码.HK` | `0700.HK` | 腾讯控股 |
| 美股 | `代码` | `AAPL` | 苹果（对比参考） |

**重要**：必须使用后缀（.SH/.SZ/.HK）标识市场，否则系统会默认按美股处理。

## 基本用法

### 分析单支 A 股
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus
```

### 分析单支港股
```bash
poetry run python src/main.py --tickers 0700.HK --model glm-4-plus
```

### 分析多支股票（混合市场）
```bash
poetry run python src/main.py --tickers 600519.SH,0700.HK,AAPL --model glm-4-plus
```

### 使用全部 19 个分析师
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus --analysts-all
```

### 指定特定分析师
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus --analysts warren_buffett,peter_lynch,technical_analyst
```

### 使用分钟级数据（盘中分析）
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus --interval 15min
```

### 显示详细推理过程
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus --analysts-all --show-reasoning
```

## CLI 完整参数参考

| 参数 | 说明 | 示例 |
|------|------|------|
| `--tickers` | 股票代码（必填，逗号分隔） | `600519.SH,0700.HK` |
| `--model` | LLM 模型名称 | `glm-4-plus` |
| `--analysts` | 指定分析师（逗号分隔） | `warren_buffett,peter_lynch` |
| `--analysts-all` | 使用全部 19 个分析师 | — |
| `--start-date` | 分析起始日期 | `2025-01-01` |
| `--end-date` | 分析结束日期 | `2025-06-01` |
| `--interval` | 数据粒度 | `daily`/`1min`/`5min`/`15min`/`30min`/`60min` |
| `--initial-cash` | 初始资金（默认 300000） | `500000` |
| `--show-reasoning` | 显示分析师推理过程 | — |
| `--ollama` | 使用本地 Ollama 模型 | — |

## 可用分析师一览

### 投资大师 Agent（13 位）

| ID | 名称 | 投资风格 |
|----|------|---------|
| `warren_buffett` | Warren Buffett | 价值投资，寻求护城河和强基本面 |
| `charlie_munger` | Charlie Munger | 理性价值投资，关注优质企业 |
| `ben_graham` | Ben Graham | 价值投资之父，强调安全边际 |
| `peter_lynch` | Peter Lynch | 十倍股猎手，关注 PEG 和增长 |
| `phil_fisher` | Phil Fisher | 闲聊投资法，关注管理和创新 |
| `cathie_wood` | Cathie Wood | 颠覆性创新投资 |
| `michael_burry` | Michael Burry | 逆向投资，深度基本面分析 |
| `bill_ackman` | Bill Ackman | 激进投资，反向布局 |
| `stanley_druckenmiller` | Stanley Druckenmiller | 宏观投资，关注经济趋势 |
| `aswath_damodaran` | Aswath Damodaran | 估值大师，精确内在价值 |
| `mohnish_pabrai` | Mohnish Pabrai | Dhandho 价值投资 |
| `rakesh_jhunjhunwala` | Rakesh Jhunjhunwala | 新兴市场增长投资 |
| `nassim_taleb` | Nassim Taleb | 黑天鹅风险、反脆弱策略 |

### 专业分析 Agent（6 位）

| ID | 名称 | 分析维度 |
|----|------|---------|
| `technical_analyst` | 技术面分析师 | 图表模式、技术指标 |
| `fundamentals_analyst` | 基本面分析师 | 财务报表深度分析 |
| `growth_analyst` | 增长分析师 | 增长趋势和估值 |
| `valuation_analyst` | 估值分析师 | 多种估值模型 |
| `sentiment_analyst` | 情绪分析师 | 市场情绪和投资者行为 |
| `news_sentiment_analyst` | 新闻情绪分析师 | 新闻情感分析 |

## 可用 GLM 模型

| 模型 | ID | 特点 |
|------|-----|------|
| GLM-4 Plus | `glm-4-plus` | **推荐** — JSON 输出质量最佳，分析深度好 |
| GLM-4 Air | `glm-4-air` | 平衡型，速度快 |
| GLM-4 Flash | `glm-4-flash` | 最快，适合快速测试，JSON 偶有解析问题 |

## 数据源架构

### 数据源优先级

| 市场 | 第一优先级 | 备用数据源 | 说明 |
|------|----------|----------|------|
| A 股（.SH/.SZ） | AKShare（免费） | Tushare Pro | AKShare 失败自动降级到 Tushare |
| 港股（.HK） | AKShare（免费） | yfinance（免费） | AKShare 失败自动降级到 yfinance |
| 美股 | Financial Datasets | yfinance（免费） | 需配置 API 密钥 |

### 各数据源支持的数据类型

| 数据类型 | AKShare (A股) | Tushare (A股备用) | AKShare (港股) | yfinance (港股备用) |
|---------|:---:|:---:|:---:|:---:|
| 日线行情 | ✅ | ✅ | ✅ | ✅ |
| 分钟行情 | ✅ | ✅ | ✅ | ❌ |
| 财务指标 | ✅ | ✅（需积分） | ❌ | ✅ |
| 公司新闻 | ✅ | ❌ | ❌ | ❌ |
| 股东变动 | ✅ | ✅ | ❌ | ❌ |
| 总市值 | ✅ | ✅ | ✅ | ✅ |
| 财务报表 | ✅ | ✅（需积分） | ❌ | ✅ |

### 分钟级数据说明

| 市场 | 支持粒度 | 数据延迟 | 说明 |
|------|---------|---------|------|
| A 股 | 1/5/15/30/60 分钟 | 盘中近实时（3-5秒） | 默认获取最近 5 个交易日 |
| 港股 | 1/5/15/30/60 分钟 | 延迟 15-20 分钟 | 非实时数据 |

## 常用分析场景

### 场景 1：快速技术面分析
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-flash --analysts technical_analyst --interval 15min
```

### 场景 2：深度价值评估
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus --analysts warren_buffett,ben_graham,peter_lynch,valuation_analyst --show-reasoning
```

### 场景 3：全面分析报告
```bash
poetry run python src/main.py --tickers 600519.SH --model glm-4-plus --analysts-all --start-date 2025-01-01 --end-date 2025-06-01 --show-reasoning
```

### 场景 4：多市场对比
```bash
poetry run python src/main.py --tickers 600519.SH,0700.HK,AAPL --model glm-4-plus --analysts-all
```

### 场景 5：港股快速分析
```bash
poetry run python src/main.py --tickers 0700.HK --model glm-4-plus --analysts technical_analyst,fundamentals_analyst,sentiment_analyst
```

## 常见 A 股/港股 Ticker 参考

### 热门 A 股

| Ticker | 名称 | 行业 |
|--------|------|------|
| `600519.SH` | 贵州茅台 | 白酒 |
| `000858.SZ` | 五粮液 | 白酒 |
| `601318.SH` | 中国平安 | 保险 |
| `600036.SH` | 招商银行 | 银行 |
| `000333.SZ` | 美的集团 | 家电 |
| `002594.SZ` | 比亚迪 | 新能源汽车 |
| `600900.SH` | 长江电力 | 电力 |
| `601899.SH` | 紫金矿业 | 矿业 |

### 热门港股

| Ticker | 名称 | 行业 |
|--------|------|------|
| `0700.HK` | 腾讯控股 | 互联网 |
| `9988.HK` | 阿里巴巴 | 电商 |
| `9888.HK` | 百度集团 | AI/互联网 |
| `1810.HK` | 小米集团 | 消费电子 |
| `2318.HK` | 中国平安 | 保险 |
| `0005.HK` | 汇丰控股 | 银行 |
| `3690.HK` | 美团 | 生活服务 |
| `9618.HK` | 京东集团 | 电商 |

## 注意事项与限制

1. **Ticker 格式必须正确** — 缺少 `.SH`/`.SZ`/`.HK` 后缀会导致系统按美股处理
2. **AKShare 网络依赖** — AKShare 底层依赖东方财富等网站，偶尔会遇到连接问题，此时会自动降级到备用数据源
3. **Tushare 积分限制** — 免费账户可使用日线数据，财务报表数据需要 2000+ 积分
4. **港股数据延迟** — 港股分钟级数据有 15-20 分钟延迟
5. **A 股交易时段** — 分钟级数据仅在交易时段（9:30-15:00）有效
6. **GLM 模型推荐** — 推荐使用 `glm-4-plus`，其 JSON 输出质量远优于 `glm-4-flash`
7. **数据覆盖差异** — A 股数据最丰富（新闻、股东变动等），港股数据相对有限

## 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 数据获取失败 | AKShare 网络不稳定 | 等待重试，系统会自动降级到备用数据源 |
| 财务指标为空 | Tushare 积分不足 | 升级 Tushare 积分或依赖 AKShare |
| JSON 解析错误 | 模型输出格式问题 | 换用 `glm-4-plus` 模型 |
| Ticker 无法识别 | 格式不正确 | 确保使用正确的后缀（.SH/.SZ/.HK） |
| 分析结果数据不足 | 该股票数据覆盖有限 | 尝试更主流的标的，或调整时间范围 |
