# A股回测规则

## 板块识别（涨跌停幅度）

根据股票代码前缀判断所属板块和每日涨跌停幅度：

| 代码前缀 | 板块 | 每日涨跌停幅度 |
|---------|------|--------------|
| 60xxxx | 上交所主板 | ±10% |
| 000xxx, 001xxx, 002xxx, 003xxx | 深交所主板 | ±10% |
| 688xxx | 科创板（STAR） | ±20% |
| 300xxx, 301xxx | 创业板（ChiNext） | ±20% |
| 8xxxxx | 北交所（BSE） | ±30% |

新股/次新股上市首日及前5个交易日无涨跌停限制（策略中可忽略此例外）。

## 交易规则

- **T+1制度**：当日买入的股票，次日才能卖出。当日卖出的股票，资金当日可用。
- **执行时机**：信号产生于当日收盘后，下一交易日开盘价执行（next-bar open）。
- **无做空**：A股不支持普通散户直接做空个股，策略仅考虑多头（持有或空仓）。
- **交易成本**：暂不计入手续费和印花税（忽略）。

## 图表可视化要求

回测策略生成的Plotly图表必须包含以下标记：

### 涨停/跌停标记
- **触及涨停（close ≥ prev_close × (1 + limit)）**：在K线上方绘制红色向上三角标记 `▲`，标注「涨停」
- **触及跌停（close ≤ prev_close × (1 - limit)）**：在K线下方绘制绿色向下三角标记 `▼`，标注「跌停」
- 标记使用 `go.Scatter(mode='markers+text')` 叠加在主图上

### 买卖信号标记
- **买入信号**：绿色向上三角 `△`（空心），标注「买」，位于K线下方
- **卖出信号**：红色向下三角 `▽`（空心），标注「卖」，位于K线上方

### 示例代码片段（板块识别）
```python
def get_limit_pct(code: str) -> float:
    """返回该股票的单日涨跌停幅度（小数形式）。"""
    if code.startswith('688'):
        return 0.20  # 科创板
    elif code.startswith('300') or code.startswith('301'):
        return 0.20  # 创业板
    elif code.startswith('8'):
        return 0.30  # 北交所
    else:
        return 0.10  # 主板（60xxxx / 000xxx / 002xxx 等）
```

### 示例代码片段（涨跌停标记）
```python
import plotly.graph_objects as go

limit = get_limit_pct(stock_code)
df['limit_up']   = df['close'] >= df['close'].shift(1) * (1 + limit - 0.001)
df['limit_down'] = df['close'] <= df['close'].shift(1) * (1 - limit + 0.001)

# 涨停标记（红色▲）
fig.add_trace(go.Scatter(
    x=df.loc[df['limit_up'], 'ts'],
    y=df.loc[df['limit_up'], 'high'] * 1.01,
    mode='markers+text',
    marker=dict(symbol='triangle-up', color='red', size=10),
    text='涨停', textposition='top center',
    name='涨停', showlegend=False,
))

# 跌停标记（绿色▼）
fig.add_trace(go.Scatter(
    x=df.loc[df['limit_down'], 'ts'],
    y=df.loc[df['limit_down'], 'low'] * 0.99,
    mode='markers+text',
    marker=dict(symbol='triangle-down', color='green', size=10),
    text='跌停', textposition='bottom center',
    name='跌停', showlegend=False,
))
```

## 回测统计输出

每次回测必须用 `print()` 输出以下统计指标（print输出会被系统捕获并返回给用户）：

```
===== 回测结果 =====
股票代码: {code}
回测区间: {start} ~ {end}
板块: {board}（涨跌停幅度: ±{pct}%）

总收益率:     {total_return:.2f}%
年化收益率:   {annual_return:.2f}%
最大回撤:     {max_drawdown:.2f}%
夏普比率:     {sharpe:.2f}
胜率:         {win_rate:.1f}%
交易次数:     {trade_count} 次（买入 {buy_count} 次，卖出 {sell_count} 次）
==================
```

- **总收益率** = (期末净值 - 1) × 100%
- **年化收益率** = (期末净值)^(252/交易日数) - 1
- **最大回撤** = max((峰值净值 - 谷值净值) / 峰值净值)
- **夏普比率** = 年化超额收益 / 年化波动率（无风险利率取2.5%年化）
- **胜率** = 盈利交易次数 / 总交易次数（以完整一买一卖为一次交易）
