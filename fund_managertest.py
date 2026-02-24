import akshare as ak

fund_open_fund_rank_em_df = ak.fund_open_fund_rank_em(symbol="全部")
print(fund_open_fund_rank_em_df)

fund_etf_hist_sina_df = ak.fund_etf_hist_sina(symbol="sh510500")
print(fund_etf_hist_sina_df)


fund_rating_all_df = ak.fund_rating_all()
print(fund_rating_all_df)

fund_name_em_df = ak.fund_name_em()
print(fund_name_em_df)
