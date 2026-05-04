"""
GoalAnchor — 单元测试

覆盖：动态阈值、偏离度向量、四级纠偏、PID控制器、相似度计算
"""
import pytest

from src.execution.goal_anchor import AnchorResult, GoalAnchor


class TestGoalAnchorThreshold:
    """动态阈值"""

    def test_default_base_threshold(self):
        anchor = GoalAnchor()
        assert anchor.base_threshold is None

    def test_custom_base_threshold(self):
        anchor = GoalAnchor(base_threshold=0.6)
        assert anchor.base_threshold == 0.6

    def test_dynamic_threshold_at_progress_zero(self):
        anchor = GoalAnchor(base_threshold=0.5)
        # progress=0 → threshold = base
        assert anchor.get_dynamic_threshold(0.0) == pytest.approx(0.5)

    def test_dynamic_threshold_at_progress_half(self):
        anchor = GoalAnchor(base_threshold=0.5)
        # progress=0.5 → 0.5 + 0.4 * 0.25 = 0.6
        assert anchor.get_dynamic_threshold(0.5) == pytest.approx(0.6)

    def test_dynamic_threshold_at_progress_one(self):
        anchor = GoalAnchor(base_threshold=0.5)
        # progress=1.0 → 0.5 + 0.4 = 0.9
        assert anchor.get_dynamic_threshold(1.0) == pytest.approx(0.9)

    def test_dynamic_threshold_none_base_defaults_to_half(self):
        anchor = GoalAnchor()
        # base=None → 默认 0.5
        assert anchor.get_dynamic_threshold(0.0) == pytest.approx(0.5)


class TestGoalAnchorCheck:
    """偏离度检查"""

    def setup_method(self):
        self.anchor = GoalAnchor(base_threshold=0.5)

    def test_identical_goal_and_current(self):
        result = self.anchor.check("完成用户登录功能", "完成用户登录功能", progress=0.0)
        assert result.similarity == pytest.approx(1.0, abs=0.1)
        assert result.is_on_track is True
        assert result.action == "continue"

    def test_completely_different(self):
        result = self.anchor.check("写一个排序算法", "今天天气真好", progress=0.0)
        assert result.similarity < 0.5
        assert result.is_on_track is False

    def test_slight_deviation(self):
        result = self.anchor.check("实现用户注册模块", "实现用户登录模块", progress=0.0)
        # 相似度高但不同 → correct 或 ask_user
        assert result.action in ("continue", "correct")

    def test_returns_anchor_result_type(self):
        result = self.anchor.check("目标", "当前", progress=0.0)
        assert isinstance(result, AnchorResult)

    def test_deviation_vector_has_three_dimensions(self):
        result = self.anchor.check("abc", "xyz", progress=0.0)
        assert "cosine" in result.deviation_vector
        assert "edit" in result.deviation_vector
        assert "semantic" in result.deviation_vector

    def test_progress_affects_threshold(self):
        """进度越高，阈值越严，更容易触发纠偏"""
        result_early = self.anchor.check("写代码", "吃饭", progress=0.1)
        result_late = self.anchor.check("写代码", "吃饭", progress=0.9)
        # 后期阈值更高
        assert result_late.dynamic_threshold > result_early.dynamic_threshold

    def test_action_levels(self):
        """四级纠偏动作都在合理范围内"""
        result = self.anchor.check("目标", "当前", progress=0.0)
        assert result.action in ("continue", "correct", "ask_user", "stop")


class TestGoalAnchorPID:
    """PID 控制器"""

    def test_pid_output_bounded(self):
        anchor = GoalAnchor()
        output = anchor.pid_compute(0.5)
        assert 0.0 <= output <= 1.0

    def test_pid_zero_deviation(self):
        anchor = GoalAnchor()
        output = anchor.pid_compute(0.0)
        assert output == pytest.approx(0.0, abs=0.01)

    def test_pid_integral_windup_clamped(self):
        """积分项不应无限累积"""
        anchor = GoalAnchor()
        for _ in range(100):
            anchor.pid_compute(1.0)
        # 积分项被 clamp 到 [-10, 10]
        assert abs(anchor._integral_error) <= 10.0

    def test_custom_pid_params(self):
        anchor = GoalAnchor()
        anchor._kp = 1.0
        anchor._ki = 0.2
        anchor._kd = 0.1
        output = anchor.pid_compute(0.5)
        assert 0.0 <= output <= 1.0


class TestGoalAnchorSimilarityMethods:
    """相似度计算方法"""

    def setup_method(self):
        self.anchor = GoalAnchor()

    def test_cosine_identical(self):
        sim = self.anchor._cosine_similarity("hello world", "hello world")
        assert sim == pytest.approx(1.0)

    def test_cosine_completely_different(self):
        sim = self.anchor._cosine_similarity("abc", "xyz")
        assert sim == pytest.approx(0.0)

    def test_levenshtein_identical(self):
        dist = self.anchor._levenshtein_normalized("abc", "abc")
        assert dist == pytest.approx(0.0)

    def test_levenshtein_completely_different(self):
        dist = self.anchor._levenshtein_normalized("abc", "xyz")
        assert dist == pytest.approx(1.0)

    def test_levenshtein_empty_both(self):
        dist = self.anchor._levenshtein_normalized("", "")
        assert dist == pytest.approx(0.0)

    def test_levenshtein_one_empty(self):
        dist = self.anchor._levenshtein_normalized("abc", "")
        assert dist == pytest.approx(1.0)

    def test_jaccard_identical(self):
        sim = self.anchor._jaccard_similarity("a b c", "a b c")
        assert sim == pytest.approx(1.0)

    def test_jaccard_no_overlap(self):
        sim = self.anchor._jaccard_similarity("a b", "x y")
        assert sim == pytest.approx(0.0)

    def test_jaccard_empty_both(self):
        sim = self.anchor._jaccard_similarity("", "")
        assert sim == pytest.approx(1.0)

    def test_tokenize_chinese_bigram(self):
        tokens = self.anchor._tokenize("用户登录")
        # 中文 bigram: ['用户', '户登', '登录']
        assert len(tokens) > 0
        assert all(len(t) == 2 for t in tokens)

    def test_tokenize_english_space(self):
        tokens = self.anchor._tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_extract_keywords(self):
        keywords = self.anchor._extract_keywords("用户登录注册登录")
        assert len(keywords) <= 5
        assert "登录" in keywords


class TestGoalAnchorHistory:
    """纠偏效果记录"""

    def test_record_correction(self):
        anchor = GoalAnchor()
        anchor.record_correction(True)
        anchor.record_correction(False)
        assert len(anchor._history) == 2
        assert anchor._history[0]["was_effective"] is True
        assert anchor._history[1]["was_effective"] is False
