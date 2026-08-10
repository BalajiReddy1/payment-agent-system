"""
Decision scoring.

The failure this file guards against: scoring a zero-impact action as perfect
on every objective, which made "send an alert" strictly dominate every real
intervention and left the agent unable to act at all.
"""

from datetime import datetime

from src.agent.decision_maker import PaymentDecisionMaker
from src.models.state import ActionType, AgentState, DecisionContext, Pattern

from conftest import make_action


def make_pattern(severity=1.0, confidence=0.9, pattern_type='issuer_degradation'):
    return Pattern(
        pattern_id='p1',
        pattern_type=pattern_type,
        description='Issuer HDFC_BANK degraded',
        severity=severity,
        confidence=confidence,
        affected_dimension='issuer',
        affected_value='HDFC_BANK',
        metrics={
            'current_success_rate': 0.12,
            'baseline_success_rate': 0.95,
            'degradation': 0.83,
            'volume': 40,
            'avg_latency': 600.0,
        },
        detected_at=datetime.now(),
    )


def make_context(pattern=None, state=None):
    return DecisionContext(
        pattern=pattern or make_pattern(),
        hypotheses=[],
        available_actions=[],
        current_state=state or AgentState(),
        historical_outcomes={},
        constraints={},
    )


def test_zero_impact_does_not_score_perfectly():
    dm = PaymentDecisionMaker()
    assert dm._score_success_impact(0.0, 1.0) == dm.NEUTRAL_SCORE
    assert dm._score_latency_impact(0.0, 200.0) == dm.NEUTRAL_SCORE
    assert dm._score_cost_impact(0.0) == dm.NEUTRAL_SCORE


def test_scorers_are_monotonic():
    dm = PaymentDecisionMaker()

    # More success improvement is always better
    assert dm._score_success_impact(0.20, 1.0) > dm._score_success_impact(0.05, 1.0)
    assert dm._score_success_impact(0.05, 1.0) > dm._score_success_impact(0.0, 1.0)
    assert dm._score_success_impact(0.0, 1.0) > dm._score_success_impact(-0.05, 1.0)

    # Latency reductions beat no change, which beats increases
    assert dm._score_latency_impact(-200.0, 200.0) > dm._score_latency_impact(0.0, 200.0)
    assert dm._score_latency_impact(0.0, 200.0) > dm._score_latency_impact(200.0, 200.0)

    # Saving money must score above changing nothing
    assert dm._score_cost_impact(-0.02) > dm._score_cost_impact(0.0)
    assert dm._score_cost_impact(0.0) > dm._score_cost_impact(0.05)


def test_severe_pattern_prefers_intervention_over_standing_still():
    dm = PaymentDecisionMaker()
    context = make_context(make_pattern(severity=1.0, confidence=0.9))

    ranked = dm.rank_actions(context)
    scores = {action.action_type: score for action, score, _ in ranked}

    assert ActionType.CIRCUIT_BREAKER in scores
    assert scores[ActionType.CIRCUIT_BREAKER] > scores[ActionType.NO_ACTION]
    assert ranked[0][0].action_type is not ActionType.NO_ACTION


def test_weak_pattern_prefers_standing_still():
    """Low severity and low confidence should not trigger an intervention."""
    dm = PaymentDecisionMaker()
    context = make_context(make_pattern(severity=0.31, confidence=0.25))

    ranked = dm.rank_actions(context)
    assert ranked[0][0].action_type == ActionType.NO_ACTION


def test_alerting_is_not_a_competing_candidate():
    """
    Alerts are emitted alongside a mitigation, never instead of one, so they
    must not appear in the ranking where they would out-score real fixes.
    """
    dm = PaymentDecisionMaker()
    ranked = dm.rank_actions(make_context())
    assert ActionType.ALERT_OPS not in {action.action_type for action, _, _ in ranked}


def test_zero_impact_detection():
    dm = PaymentDecisionMaker()
    inert = make_action(estimated_impact={
        'success_rate_delta': 0.0,
        'latency_delta_ms': 0.0,
        'cost_delta_per_txn': 0.0,
        'affected_traffic_pct': 0.0,
    })
    assert dm._is_zero_impact(inert)
    assert not dm._is_zero_impact(make_action())


def test_ranking_is_sorted_and_carries_reasoning():
    dm = PaymentDecisionMaker()
    ranked = dm.rank_actions(make_context())

    scores = [score for _, score, _ in ranked]
    assert scores == sorted(scores, reverse=True)
    for action, _, _ in ranked:
        assert 'Pattern Detected' in action.reasoning
        assert 'Alternatives Considered' in action.reasoning
