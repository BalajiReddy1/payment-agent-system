"""
Composition root.

One place where configuration is turned into wired-up objects. Components take
their settings as constructor arguments and never read YAML themselves, so they
stay testable in isolation and there is a single answer to "where does this
threshold come from".
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from src.agent.core import PaymentAgent
from src.models.state import ACTION_AUTHORIZATION
from src.safety.guardrails import SafetyGuardrails, SafetyLimits
from src.simulation.payment_simulator import PaymentSimulator
from src.utils.settings import Settings

logger = logging.getLogger(__name__)


def build_settings(config_dir: Optional[Path] = None) -> Settings:
    """Load and validate settings."""
    return Settings.load(config_dir)


def build_agent(
    settings: Optional[Settings] = None,
    journal=None,
    **overrides
) -> PaymentAgent:
    """
    Construct a PaymentAgent from settings.

    Args:
        settings: Loaded settings; defaults are used when omitted.
        journal: Optional durable journal; omitted means record nothing.
        **overrides: Direct PaymentAgent keyword overrides, applied last, for
            tests and demos that want to differ from config on one axis.
    """
    settings = settings or build_settings()

    logging.getLogger().setLevel(settings.log_level)

    guardrails = SafetyGuardrails(SafetyLimits(**settings.safety_limits))

    agent_kwargs = {
        'window_size_minutes': settings.agent.window_size_minutes,
        'analysis_interval_seconds': settings.agent.analysis_interval_seconds,
        'auto_approve_low_risk': settings.agent.auto_approve_low_risk,
        'min_severity_to_act': settings.agent.min_severity_to_act,
        'outcome_evaluation_seconds': settings.agent.outcome_evaluation_seconds,
        'holdout_fraction': settings.agent.holdout_fraction,
        'journal': journal,
    }
    agent_kwargs.update(overrides)

    agent = PaymentAgent(**agent_kwargs)

    # Detection thresholds
    agent.reasoner.thresholds.update({
        'issuer_degradation': settings.thresholds.issuer_degradation,
        'method_fatigue': settings.thresholds.method_fatigue,
        'latency_spike': settings.thresholds.latency_spike,
        'retry_storm': settings.thresholds.retry_storm,
        'error_cluster': settings.thresholds.error_cluster,
    })
    agent.reasoner.min_confidence = settings.thresholds.min_pattern_confidence

    # Decision policy
    agent.decision_maker.weights = settings.decision_weights.as_dict()
    agent.min_action_score = settings.thresholds.min_action_score

    # Safety and rollback
    agent.executor.guardrails = guardrails
    agent.executor.rollback_thresholds.update(settings.rollback.as_dict())

    # Learning
    agent.learner.learning_rate = settings.learning.weight_adjustment_rate
    agent.learner.min_samples_for_update = settings.learning.min_samples_for_update

    # Authorization tiers, when config chooses to define them
    if settings.authorization:
        ACTION_AUTHORIZATION.clear()
        ACTION_AUTHORIZATION.update(settings.authorization)
        logger.info("Authorization tiers loaded from safety_rules.yaml")

    return agent


def build_simulator(
    settings: Optional[Settings] = None,
    control_plane=None
) -> PaymentSimulator:
    """Construct a simulator bound to a control plane."""
    settings = settings or build_settings()
    return PaymentSimulator(
        base_success_rate=settings.simulation.base_success_rate,
        control_plane=control_plane,
    )


def build_system(
    settings: Optional[Settings] = None,
    journal=None,
    **overrides
) -> Tuple[PaymentAgent, PaymentSimulator, Settings]:
    """
    Build an agent and a simulator already wired to each other.

    The simulator reads the agent's control plane, which is what makes the
    agent's interventions actually affect the traffic it observes.
    """
    settings = settings or build_settings()
    agent = build_agent(settings, journal=journal, **overrides)
    simulator = build_simulator(settings, control_plane=agent.state)
    return agent, simulator, settings
