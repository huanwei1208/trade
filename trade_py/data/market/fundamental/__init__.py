"""Fundamental data package.

Primary provider: Tushare (fina_indicator)
"""
from trade_py.data.market.fundamental.tushare import FundamentalFetcher, compute_fundamental_features

__all__ = ["FundamentalFetcher", "compute_fundamental_features"]
