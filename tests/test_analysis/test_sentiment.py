"""
Tests for dss.analysis_engine.sentiment — rank score mapping.
"""
import pytest
from dss.analysis_engine.sentiment import SentimentAnalyzer


class TestRankScore:
    """热榜排名 → 得分映射"""

    def test_rank_1(self):
        score = SentimentAnalyzer._compute_rank_score(1)
        assert score == 100.0

    def test_rank_10(self):
        score = SentimentAnalyzer._compute_rank_score(10)
        assert score == 91.0

    def test_rank_50(self):
        score = SentimentAnalyzer._compute_rank_score(50)
        assert 70.0 <= score <= 90.0

    def test_rank_100(self):
        score = SentimentAnalyzer._compute_rank_score(100)
        assert 50.0 <= score <= 70.0

    def test_rank_200(self):
        score = SentimentAnalyzer._compute_rank_score(200)
        assert score >= 30.0, f"Floor should be 30, got {score}"

    def test_no_rank(self):
        score = SentimentAnalyzer._compute_rank_score(0)
        assert score == 50.0

    def test_negative_rank(self):
        score = SentimentAnalyzer._compute_rank_score(-1)
        assert score == 50.0


class TestSentimentAnalyze:
    """情绪面完整分析"""

    def test_positive_sentiment(self):
        analyzer = SentimentAnalyzer()
        score, details = analyzer.analyze(
            ts_code='600036.SH', name='招商银行',
            hot_rank=5, daily_change_pct=4.0,
        )
        assert 0 <= score <= 100
        assert details['change_sentiment'] == 'positive'
        assert 'hot_rank' in details

    def test_negative_sentiment(self):
        analyzer = SentimentAnalyzer()
        score, details = analyzer.analyze(
            ts_code='000001.SZ', name='平安银行',
            hot_rank=200, daily_change_pct=-6.0,
        )
        assert 0 <= score <= 100
        assert details['change_sentiment'] == 'negative'

    def test_not_in_hotlist(self):
        analyzer = SentimentAnalyzer()
        score, details = analyzer.analyze(
            ts_code='600000.SH', name='浦发银行',
            hot_rank=0, daily_change_pct=0.0,
        )
        assert details['data_available'] is False
        assert 40 <= score <= 60  # 全中性 = ~50
