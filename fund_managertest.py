import akshare as ak

print(ak.fund_etf_category_sina(symbol="LOF基金"))
print(ak.fund_etf_category_sina(symbol="封闭式基金"))
print(ak.fund_etf_category_sina(symbol="ETF基金"))

fund_open_fund_rank_em_df = ak.fund_open_fund_rank_em(symbol="全部")
print(fund_open_fund_rank_em_df)

fund_etf_hist_sina_df = ak.fund_etf_hist_sina(symbol="sh510500")
print(fund_etf_hist_sina_df)

