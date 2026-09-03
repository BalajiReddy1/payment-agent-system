"""
Configuration.

config/*.yaml used to be read by nothing at all - a commit could "lower the
detection thresholds" while changing no behaviour whatsoever. These tests hold
the wiring in place: the files are loaded, they reach the components that use
them, and a dangerous mistake in them stops startup rather than passing through.
"""

import os
import textwrap

import pytest

from src.factory import build_agent, build_settings, build_system
from src.models.state import ActionType, AuthorizationLevel
from src.utils.settings import ConfigError, Settings


@pytest.fixture
def config_dir(tmp_path=None):
    """A throwaway config directory (created per call)."""
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def write(directory, name, body):
    (directory / f"{name}.yaml").write_text(textwrap.dedent(body))


def test_defaults_apply_with_no_config_files(config_dir):
    settings = Settings.load(config_dir)

    assert settings.agent.window_size_minutes == 10
    assert settings.thresholds.issuer_degradation == 0.15
    assert settings.authorization is None


def test_repo_config_loads_and_validates():
    """The committed config must actually be loadable."""
    settings = build_settings()

    assert settings.thresholds.issuer_degradation == 0.08
    assert settings.thresholds.retry_storm == 0.15
    assert settings.thresholds.min_pattern_confidence == 0.4
    assert settings.thresholds.min_action_score == 0.3


def test_thresholds_reach_the_reasoner():
    """The regression: YAML said 0.08 while the reasoner used a hardcoded 0.15."""
    agent = build_agent()

    assert agent.reasoner.thresholds['issuer_degradation'] == 0.08
    assert agent.reasoner.thresholds['retry_storm'] == 0.15
    assert agent.reasoner.min_confidence == 0.4


def test_decision_weights_reach_the_decision_maker():
    agent = build_agent()
    assert agent.decision_maker.weights['success_rate'] == 0.40
    assert agent.decision_maker.weights['risk'] == 0.15


def test_safety_limits_reach_the_executor():
    agent = build_agent()
    limits = agent.executor.guardrails.limits

    assert limits.max_actions_per_hour == 10
    assert limits.max_rollbacks_per_hour == 3
    assert limits.max_concurrent_interventions == 5


def test_rollback_percent_is_converted_to_a_fraction(config_dir):
    write(config_dir, 'safety_rules', """
        rollback_triggers:
          success_rate_drop: 0.07
          latency_increase_percent: 40
    """)
    settings = Settings.load(config_dir)

    assert settings.rollback.success_rate_drop == 0.07
    assert settings.rollback.latency_increase == 0.40


def test_weights_that_do_not_sum_to_one_are_rejected(config_dir):
    write(config_dir, 'agent_config', """
        decision_weights:
          success_rate: 0.9
          latency: 0.9
          cost: 0.9
          risk: 0.9
    """)
    with pytest.raises(ConfigError):
        Settings.load(config_dir)


def test_out_of_range_probability_is_rejected(config_dir):
    write(config_dir, 'agent_config', """
        thresholds:
          pattern_confidence: 1.7
    """)
    with pytest.raises(ConfigError):
        Settings.load(config_dir)


def test_authorization_section_becomes_the_tier_map(config_dir):
    write(config_dir, 'safety_rules', """
        authorization:
          automatic:
            - adjust_retry
            - alert_ops
            - no_action
          semi_automatic:
            - circuit_breaker
            - route_change
          manual:
            - method_suppress
    """)
    settings = Settings.load(config_dir)

    assert settings.authorization[ActionType.METHOD_SUPPRESS] == AuthorizationLevel.MANUAL
    assert settings.authorization[ActionType.ADJUST_RETRY] == AuthorizationLevel.AUTOMATIC


def test_unclassified_action_stops_startup(config_dir):
    """
    A capability nobody classified must not default into being executable
    without approval, so an incomplete map is a startup failure.
    """
    write(config_dir, 'safety_rules', """
        authorization:
          automatic:
            - adjust_retry
    """)
    with pytest.raises(ConfigError) as exc:
        Settings.load(config_dir)

    assert 'method_suppress' in str(exc.value)


def test_action_in_two_tiers_is_rejected(config_dir):
    write(config_dir, 'safety_rules', """
        authorization:
          automatic:
            - adjust_retry
            - alert_ops
            - no_action
            - method_suppress
          semi_automatic:
            - circuit_breaker
            - route_change
          manual:
            - method_suppress
    """)
    with pytest.raises(ConfigError):
        Settings.load(config_dir)


def test_unknown_tier_name_is_rejected(config_dir):
    write(config_dir, 'safety_rules', """
        authorization:
          whenever_it_feels_like_it:
            - method_suppress
    """)
    with pytest.raises(ConfigError):
        Settings.load(config_dir)


def test_malformed_yaml_is_reported_clearly(config_dir):
    (config_dir / 'agent_config.yaml').write_text("agent: [unclosed\n")
    with pytest.raises(ConfigError):
        Settings.load(config_dir)


def test_build_system_wires_simulator_to_the_agent():
    agent, simulator, _settings = build_system()

    agent.state.control_plane.trip_breaker(
        'HDFC_BANK', author='test', reason='wiring check'
    )
    assert 'HDFC_BANK' in simulator._cp('circuit_breakers', frozenset())


def test_simulator_accepts_agent_state_control_plane_or_revision():
    """
    All three shapes have to resolve to the same policy. Accepting several
    shapes whose attribute names differ is how a control plane ends up
    silently ignored.
    """
    from src.control.plane import ControlPlane
    from src.models.state import AgentState
    from src.simulation.payment_simulator import PaymentSimulator

    state = AgentState()
    state.control_plane.trip_breaker('HDFC_BANK', author='test', reason='check')

    for source in (state, state.control_plane, state.control_plane.current):
        simulator = PaymentSimulator(control_plane=source)
        assert simulator._cp('circuit_breakers', frozenset()) == frozenset({'HDFC_BANK'}), (
            f"policy not resolved from {type(source).__name__}"
        )


def test_overrides_win_over_config():
    agent = build_agent(window_size_minutes=1)
    assert agent.observer.window_size.total_seconds() == 60


def test_env_file_fills_gaps_without_overriding_the_real_environment(tmp_path, monkeypatch):
    """
    A key exported in the shell, injected by a container runtime, or handed
    over by a secret manager is authoritative. The file only fills gaps.
    """
    from src.utils.env import load_env_file

    env = tmp_path / '.env'
    env.write_text(
        '# a comment\n'
        '\n'
        'export FLOWSTATE_FROM_FILE="written"\n'
        "FLOWSTATE_QUOTED='also written'\n"
        'FLOWSTATE_ALREADY_SET=ignored\n'
        'not-a-pair\n',
        encoding='utf-8',
    )
    monkeypatch.setenv('FLOWSTATE_ALREADY_SET', 'from the shell')
    monkeypatch.delenv('FLOWSTATE_FROM_FILE', raising=False)
    monkeypatch.delenv('FLOWSTATE_QUOTED', raising=False)

    applied = load_env_file(env)

    assert os.environ['FLOWSTATE_FROM_FILE'] == 'written'
    assert os.environ['FLOWSTATE_QUOTED'] == 'also written'
    assert os.environ['FLOWSTATE_ALREADY_SET'] == 'from the shell'
    assert 'FLOWSTATE_ALREADY_SET' not in applied


def test_a_missing_env_file_is_not_an_error(tmp_path):
    from src.utils.env import load_env_file

    assert load_env_file(tmp_path / 'nothing-here') == []
