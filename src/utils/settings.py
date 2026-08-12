"""
Settings
Typed configuration assembled from config/*.yaml.

Defaults live here, in code, and YAML overrides them. That ordering matters:
the system must start and behave sensibly with no config files present, and a
config file must never be able to silently drop a setting the code depends on.

Validation is strict about the things that are dangerous to get wrong -
authorization tiers, weights that must sum to one, probabilities outside [0,1] -
and forgiving about everything else. A misconfigured guardrail should fail at
startup with a clear message, not at 3am mid-incident.
"""

import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.state import ActionType, AuthorizationLevel
from src.utils.config_loader import get_config_value, load_config

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    """Raised when configuration is present but invalid."""


@dataclass
class AgentSettings:
    window_size_minutes: int = 10
    analysis_interval_seconds: int = 30
    auto_approve_low_risk: bool = True
    min_severity_to_act: float = 0.3
    outcome_evaluation_seconds: int = 300
    holdout_fraction: float = 0.10


@dataclass
class ThresholdSettings:
    """Pattern detection thresholds and the bars an action has to clear."""

    issuer_degradation: float = 0.15
    method_fatigue: float = 0.20
    latency_spike: float = 1.5
    retry_storm: float = 0.40
    error_cluster: int = 10

    # Minimum confidence before a detected pattern is reported at all
    min_pattern_confidence: float = 0.0
    # Minimum decision score before an action is worth executing
    min_action_score: float = 0.0


@dataclass
class DecisionWeights:
    success_rate: float = 0.40
    latency: float = 0.25
    cost: float = 0.20
    risk: float = 0.15

    def as_dict(self) -> Dict[str, float]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def validate(self):
        total = sum(self.as_dict().values())
        if abs(total - 1.0) > 1e-6:
            raise ConfigError(
                f"decision_weights must sum to 1.0, got {total:.4f}. "
                f"Weights: {self.as_dict()}"
            )
        for name, value in self.as_dict().items():
            if value < 0:
                raise ConfigError(f"decision_weights.{name} must not be negative")


@dataclass
class LearningSettings:
    weight_adjustment_rate: float = 0.1
    min_samples_for_update: int = 5


@dataclass
class RollbackSettings:
    success_rate_drop: float = 0.05
    latency_increase: float = 0.50

    def as_dict(self) -> Dict[str, float]:
        return {
            'success_rate_drop': self.success_rate_drop,
            'latency_increase': self.latency_increase,
        }


@dataclass
class SimulationSettings:
    base_success_rate: float = 0.95
    transactions_per_batch: int = 25


@dataclass
class PublishSettings:
    """
    Where the control plane is published for other systems to read.

    This is the integration surface: the agent writes revisions here and a real
    checkout service reads them. Empty means do not publish, which is the right
    default for a demo and the wrong one for a deployment.
    """

    path: str = ""
    refresh_seconds: float = 30.0


@dataclass
class AdvisorSettings:
    """
    The slow lane of the two-lane brain.

    Disabled-by-default would be the wrong default: an advisor that cannot
    reach a model already returns None and the agent runs without commentary.
    So `enabled` exists to turn the lane *off* deliberately - in a test, or
    where sending incident detail to a provider is not acceptable - rather
    than to turn it on.
    """

    enabled: bool = True
    model: str = "gemini-2.5-flash"
    temperature: float = 0.2
    max_chars: int = 600


@dataclass
class Settings:
    agent: AgentSettings = field(default_factory=AgentSettings)
    thresholds: ThresholdSettings = field(default_factory=ThresholdSettings)
    decision_weights: DecisionWeights = field(default_factory=DecisionWeights)
    learning: LearningSettings = field(default_factory=LearningSettings)
    rollback: RollbackSettings = field(default_factory=RollbackSettings)
    simulation: SimulationSettings = field(default_factory=SimulationSettings)
    advisor: AdvisorSettings = field(default_factory=AdvisorSettings)
    publish: PublishSettings = field(default_factory=PublishSettings)

    # Safety limits are described by SafetyLimits itself; kept as a plain dict
    # here so this module does not import the safety package.
    safety_limits: Dict[str, Any] = field(default_factory=dict)

    # Optional override of the action -> authorization tier map
    authorization: Optional[Dict[ActionType, AuthorizationLevel]] = None

    log_level: str = "INFO"

    @classmethod
    def load(cls, config_dir: Optional[Path] = None) -> 'Settings':
        """
        Build settings from config/*.yaml, falling back to defaults.

        A missing config directory is not an error: the defaults are the
        documented behaviour, and the system has to run without config.
        """
        settings = cls()

        agent_config = _try_load('agent_config', config_dir)
        safety_config = _try_load('safety_rules', config_dir)
        simulation_config = _try_load('simulation_config', config_dir)

        settings._apply_agent_config(agent_config)
        settings._apply_safety_config(safety_config)
        settings._apply_simulation_config(simulation_config)

        settings.validate()
        return settings

    def validate(self):
        self.decision_weights.validate()

        _require_range('agent.min_severity_to_act', self.agent.min_severity_to_act, 0.0, 1.0)
        _require_range('agent.holdout_fraction', self.agent.holdout_fraction, 0.0, 0.49)
        _require_range(
            'thresholds.min_pattern_confidence', self.thresholds.min_pattern_confidence, 0.0, 1.0
        )
        _require_range('thresholds.min_action_score', self.thresholds.min_action_score, 0.0, 1.0)
        _require_range(
            'simulation.base_success_rate', self.simulation.base_success_rate, 0.0, 1.0
        )

        if self.agent.window_size_minutes <= 0:
            raise ConfigError("agent.window_size_minutes must be positive")

    # ── Section loaders ──────────────────────────────────────────────────────

    def _apply_agent_config(self, config: Dict[str, Any]):
        if not config:
            return

        _assign(self.agent, {
            'window_size_minutes': get_config_value(config, 'agent.window_size_minutes'),
            'analysis_interval_seconds': get_config_value(config, 'agent.analysis_interval_seconds'),
            'auto_approve_low_risk': get_config_value(config, 'agent.auto_approve_low_risk'),
            'min_severity_to_act': get_config_value(config, 'agent.min_severity_to_act'),
            'outcome_evaluation_seconds': get_config_value(config, 'agent.outcome_evaluation_seconds'),
            'holdout_fraction': get_config_value(config, 'agent.holdout_fraction'),
        })

        _assign(self.thresholds, {
            'issuer_degradation': get_config_value(config, 'thresholds.issuer_degradation_threshold'),
            'retry_storm': get_config_value(config, 'thresholds.retry_storm_threshold'),
            'method_fatigue': get_config_value(config, 'thresholds.method_fatigue_threshold'),
            'latency_spike': get_config_value(config, 'thresholds.latency_spike_threshold'),
            'error_cluster': get_config_value(config, 'thresholds.error_cluster_threshold'),
            'min_pattern_confidence': get_config_value(config, 'thresholds.pattern_confidence'),
            'min_action_score': get_config_value(config, 'thresholds.action_score_minimum'),
        })

        _assign(self.learning, {
            'weight_adjustment_rate': get_config_value(config, 'learning.weight_adjustment_rate'),
            'min_samples_for_update': get_config_value(config, 'learning.min_samples_for_update'),
        })

        _assign(self.advisor, {
            'enabled': get_config_value(config, 'advisor.enabled'),
            'model': get_config_value(config, 'advisor.model'),
            'temperature': get_config_value(config, 'advisor.temperature'),
            'max_chars': get_config_value(config, 'advisor.max_chars'),
        })

        _assign(self.publish, {
            'path': get_config_value(config, 'control_plane.publish_path'),
            'refresh_seconds': get_config_value(config, 'control_plane.refresh_seconds'),
        })

        weights = config.get('decision_weights')
        if weights:
            _assign(self.decision_weights, weights)

        level = get_config_value(config, 'logging.level')
        if level:
            self.log_level = str(level).upper()

    def _apply_safety_config(self, config: Dict[str, Any]):
        if not config:
            return

        limits = config.get('limits') or {}
        human = config.get('human_approval') or {}

        self.safety_limits = {
            key: value
            for key, value in {
                'max_traffic_impact_percent': limits.get('max_traffic_impact_percent'),
                'max_actions_per_hour': limits.get('max_actions_per_hour'),
                'max_rollbacks_per_hour': limits.get('max_rollbacks_per_hour'),
                'max_concurrent_interventions': limits.get('max_concurrent_interventions'),
                'manual_approve_impact_threshold': human.get('traffic_threshold_percent'),
            }.items()
            if value is not None
        }

        triggers = config.get('rollback_triggers') or {}
        if triggers.get('success_rate_drop') is not None:
            self.rollback.success_rate_drop = float(triggers['success_rate_drop'])
        if triggers.get('latency_increase_percent') is not None:
            # Config is a percentage; the executor works in fractions.
            self.rollback.latency_increase = float(triggers['latency_increase_percent']) / 100.0

        authorization = config.get('authorization')
        if authorization:
            self.authorization = _parse_authorization(authorization)

    def _apply_simulation_config(self, config: Dict[str, Any]):
        if not config:
            return

        _assign(self.simulation, {
            'base_success_rate': get_config_value(config, 'simulation.base_success_rate'),
            'transactions_per_batch': get_config_value(config, 'simulation.transactions_per_batch'),
        })


# ── Helpers ──────────────────────────────────────────────────────────────────


def _try_load(name: str, config_dir: Optional[Path]) -> Dict[str, Any]:
    """Load a config file, treating absence as 'use defaults'."""
    try:
        return load_config(name, config_dir)
    except FileNotFoundError:
        logger.debug("No %s.yaml found; using defaults", name)
        return {}
    except Exception as exc:  # malformed YAML is worth shouting about
        raise ConfigError(f"Could not parse {name}.yaml: {exc}") from exc


def _assign(target: Any, values: Dict[str, Any]):
    """Set attributes from a mapping, ignoring keys whose value is None."""
    valid = {f.name for f in fields(target)}
    for key, value in values.items():
        if value is None:
            continue
        if key not in valid:
            logger.warning("Ignoring unknown setting %r for %s", key, type(target).__name__)
            continue
        setattr(target, key, value)


def _require_range(name: str, value: float, low: float, high: float):
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")


def _parse_authorization(section: Dict[str, List[str]]) -> Dict[ActionType, AuthorizationLevel]:
    """
    Turn the YAML authorization section into a tier map.

    Strict on purpose. This section decides what the agent may do to live
    payments without asking anyone, so a typo must fail loudly at startup
    rather than quietly promoting an action to automatic.
    """
    tier_names = {
        'automatic': AuthorizationLevel.AUTOMATIC,
        'semi_automatic': AuthorizationLevel.SEMI_AUTOMATIC,
        'manual': AuthorizationLevel.MANUAL,
    }

    known_actions = {action.value: action for action in ActionType}
    mapping: Dict[ActionType, AuthorizationLevel] = {}
    unknown: List[str] = []

    for tier_name, action_names in section.items():
        level = tier_names.get(tier_name)
        if level is None:
            raise ConfigError(
                f"Unknown authorization tier {tier_name!r}. "
                f"Expected one of: {', '.join(sorted(tier_names))}"
            )
        for action_name in action_names or []:
            action = known_actions.get(action_name)
            if action is None:
                # Named but not implemented: record it rather than guessing.
                unknown.append(action_name)
                continue
            if action in mapping:
                raise ConfigError(
                    f"Action {action_name!r} is listed under more than one "
                    f"authorization tier"
                )
            mapping[action] = level

    if unknown:
        logger.warning(
            "safety_rules.yaml lists actions the agent does not implement: %s",
            ', '.join(sorted(unknown))
        )

    missing = [action.value for action in ActionType if action not in mapping]
    if missing:
        raise ConfigError(
            f"safety_rules.yaml authorization section does not classify: "
            f"{', '.join(sorted(missing))}. Every action must be assigned a "
            f"tier, so that adding a capability cannot leave it unclassified."
        )

    return mapping
