"""
Tests for dss.data_layer.stock_filter — filtering logic.
"""
import pytest
from dss.data_layer.stock_filter import StockFilter, FilterConfig


class TestHotStockFiltering:
    """热榜列表过滤"""

    def test_exclude_688_300(self):
        sf = StockFilter(FilterConfig(
            exclude_prefixes=['688', '300'],
            exclude_st=False,
        ))
        stocks = [
            {'ts_code': '600036.SH', 'name': '招商银行'},
            {'ts_code': '688001.SH', 'name': '华兴源创'},
            {'ts_code': '300001.SZ', 'name': '特锐德'},
            {'ts_code': '000001.SZ', 'name': '平安银行'},
        ]
        result = sf.filter_hot_stocks(stocks)
        codes = {s['ts_code'] for s in result}
        assert codes == {'600036.SH', '000001.SZ'}

    def test_exclude_st_by_set(self):
        sf = StockFilter(FilterConfig(exclude_st=True))
        stocks = [
            {'ts_code': '600036.SH', 'name': '招商银行'},
            {'ts_code': '000001.SZ', 'name': 'ST平安'},
        ]
        # ST set has '000001.SZ'
        result = sf.filter_hot_stocks(stocks, st_set={'000001.SZ'})
        codes = {s['ts_code'] for s in result}
        assert codes == {'600036.SH'}

    def test_exclude_st_by_name(self):
        sf = StockFilter(FilterConfig(exclude_st=True))
        stocks = [
            {'ts_code': '600036.SH', 'name': '招商银行'},
            {'ts_code': '000001.SZ', 'name': '*ST银行'},
        ]
        result = sf.filter_hot_stocks(stocks)
        codes = {s['ts_code'] for s in result}
        assert codes == {'600036.SH'}

    def test_dedup(self):
        sf = StockFilter(FilterConfig(exclude_prefixes=[], exclude_st=False))
        stocks = [
            {'ts_code': '600036.SH', 'name': '招商银行'},
            {'ts_code': '600036.SH', 'name': '招商银行'},
        ]
        result = sf.filter_hot_stocks(stocks)
        assert len(result) == 1

    def test_only_sh_sz(self):
        sf = StockFilter(FilterConfig(exclude_prefixes=[], exclude_st=False))
        stocks = [
            {'ts_code': '600036.SH', 'name': '招商银行'},
            {'ts_code': '830001.BJ', 'name': '北交所股'},
        ]
        result = sf.filter_hot_stocks(stocks)
        codes = {s['ts_code'] for s in result}
        assert codes == {'600036.SH'}
