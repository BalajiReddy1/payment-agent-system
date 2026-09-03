"""
The slow lane.

The advisor was built with a hand-written fake and never connected to
anything. These tests cover the seam that connects it: the prompt it sends,
the response handling, and the resolution rules that decide whether an advisor
exists at all. None of them make a network call - the client is injected.

The property that matters most is the last one: every failure mode of the
optional lane has to leave the deterministic lane untouched.
"""

import sys
import types
from contextlib import contextmanager

from src.agent.advisors import (
    SYSTEM_PROMPT,
    build_advisor,
    format_incident_brief,
    _default_client_factory,
)
from src.factory import build_agent, build_settings, build_simulator, _advisor_for


# ── A stand-in for the provider SDK ──────────────────────────────────────────

class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, owner):
        self._owner = owner

    def generate_content(self, model, contents, **kwargs):
        self._owner.calls.append({'model': model, 'contents': contents, **kwargs})
        if self._owner.raises:
            raise self._owner.raises
        return FakeResponse(self._owner.reply)


class FakeClient:
    """Mimics the shape build_advisor uses: client.models.generate_content."""

    def __init__(self, reply='Issuer HDFC is failing 40% of authorisations.', raises=None):
        self.reply = reply
        self.raises = raises
        self.calls = []
        self.models = FakeModels(self)


@contextmanager
def no_api_key():
    """Run a block with both credential variables absent, then restore."""
    import os

    saved = {k: os.environ.pop(k, None) for k in ('GEMINI_API_KEY', 'GOOGLE_API_KEY')}
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


@contextmanager
def sdk_missing():
    """
    Make `from google import genai` fail, whether or not it is installed.

    This is the likelier production failure than an absent key - the key is
    configured, the package is not - and it has to be testable on a machine
    where the package *is* present.
    """
    saved = {
        name: module for name, module in sys.modules.items()
        if name == 'google' or name.startswith('google.')
    }
    for name in saved:
        del sys.modules[name]
    sys.modules['google'] = types.ModuleType('google')  # a package with no genai
    try:
        yield
    finally:
        del sys.modules['google']
        sys.modules.update(saved)


def context(**overrides):
    base = {
        'incident_id': 'inc-7',
        'pattern_type': 'issuer_degradation',
        'target': 'HDFC_BANK',
        'severity': 0.82,
        'confidence': 0.91,
        'evidence': ['success rate 0.94 -> 0.51', 'p95 latency 240ms -> 900ms'],
        'hypotheses': [
            {'root_cause': 'issuer_outage', 'probability': 0.62},
            {'root_cause': 'network_degradation', 'probability': 0.21},
        ],
        'similar_incidents': ['inc-2 (HDFC_BANK, resolved by circuit_breaker)'],
        'what_worked_before': {
            'circuit_breaker': {'expected_lift': 0.31, 'samples': 4},
        },
    }
    base.update(overrides)
    return base


# ── The prompt ───────────────────────────────────────────────────────────────

def test_brief_carries_the_evidence_the_advisor_is_asked_to_weigh():
    brief = format_incident_brief(context())

    assert 'inc-7' in brief
    assert 'issuer_degradation' in brief
    assert 'HDFC_BANK' in brief
    assert 'success rate 0.94 -> 0.51' in brief


def test_brief_reports_hypotheses_strongest_first():
    brief = format_incident_brief(context())

    assert brief.index('issuer_outage') < brief.index('network_degradation')


def test_brief_states_measured_outcomes_as_measurements():
    """
    "+31.0% across 4 measured incidents" is a claim a reader can check.
    "circuit_breaker worked" is not.
    """
    brief = format_incident_brief(context())

    assert '+31.0%' in brief
    assert '4 measured incidents' in brief


def test_brief_says_so_when_nothing_comparable_has_been_measured():
    """
    Silence would read as "no prior action helped". The agent's actual state
    is that it has not measured one yet, which is a different thing.
    """
    brief = format_incident_brief(context(what_worked_before={}))

    assert 'No comparable incident has a measured outcome yet' in brief


def test_brief_survives_a_sparse_context():
    """Early incidents have no history and no hypotheses."""
    brief = format_incident_brief({'incident_id': 'inc-1'})

    assert 'inc-1' in brief
    assert '(none recorded)' in brief


def test_prompt_forbids_the_advisor_from_proposing_actions():
    """
    The advisor has no tools; if it also recommends unranked actions, an
    operator reads a suggestion that never passed the guardrails.
    """
    assert 'not recommend actions the agent has not proposed' in SYSTEM_PROMPT.lower()


# ── The call ─────────────────────────────────────────────────────────────────

def test_advisor_sends_the_brief_and_returns_the_assessment():
    client = FakeClient(reply='HDFC is rejecting 4 in 10 authorisations.')
    advisor = build_advisor(client_factory=lambda: client)

    assessment = advisor(context())

    assert assessment == 'HDFC is rejecting 4 in 10 authorisations.'
    assert len(client.calls) == 1
    assert 'HDFC_BANK' in client.calls[0]['contents']


def test_advisor_is_not_given_tools():
    """
    A second, unranked path to change payment routing is the one thing this
    component must never acquire. Asserted on the wire, not in a comment.
    """
    client = FakeClient()
    build_advisor(client_factory=lambda: client)(context())

    config = client.calls[0].get('config')
    assert getattr(config, 'tools', None) in (None, [])


def test_assessment_is_truncated_to_fit_an_incident_card():
    client = FakeClient(reply='word ' * 500)
    advisor = build_advisor(client_factory=lambda: client, max_chars=120)

    assert len(advisor(context())) <= 120


def test_whitespace_is_normalised():
    client = FakeClient(reply='  Issuer down.\n\n  Latency up.  ')

    assert build_advisor(client_factory=lambda: client)(context()) == \
        'Issuer down. Latency up.'


def test_an_empty_response_is_an_empty_assessment_not_a_crash():
    client = FakeClient(reply=None)

    assert build_advisor(client_factory=lambda: client)(context()) == ''


# ── Resolution: when does an advisor exist at all ────────────────────────────

def test_no_api_key_means_no_advisor():
    with no_api_key():
        assert _default_client_factory() is None
        assert build_advisor() is None


def test_a_key_without_the_sdk_still_yields_no_advisor():
    """
    The likelier production failure: the key is configured, the package is
    not. It has to degrade the same way an absent key does.
    """
    import os

    with no_api_key(), sdk_missing():
        os.environ['GEMINI_API_KEY'] = 'test-key'
        assert _default_client_factory() is None
        assert build_advisor() is None


def test_an_injected_client_does_not_need_a_key():
    with no_api_key():
        assert build_advisor(client_factory=lambda: FakeClient()) is not None


# ── The factory seam ─────────────────────────────────────────────────────────

def test_config_can_switch_the_lane_off():
    settings = build_settings()
    settings.advisor.enabled = False

    assert _advisor_for(settings) is None


def test_settings_expose_the_advisor_section():
    settings = build_settings()

    assert settings.advisor.model
    assert 0.0 <= settings.advisor.temperature <= 2.0
    assert settings.advisor.max_chars > 0


def test_factory_never_raises_when_no_model_is_reachable():
    """
    build_agent() is called by the console, the API and every test. An
    unreachable optional model must not be able to stop any of them starting.
    """
    with no_api_key():
        agent = build_agent(window_size_minutes=5)

    assert agent.advisor is None


def test_a_wired_advisor_writes_the_assessment_onto_the_incident():
    """End to end through the seam, with the provider replaced."""
    from datetime import datetime

    client = FakeClient(reply='SBI authorisations are failing; watch the retry rate.')
    agent = build_agent(
        window_size_minutes=5,
        advisor=build_advisor(client_factory=lambda: client),
    )
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(4):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    incidents = agent.incident_tracker.all()
    assert incidents, 'the degradation should have opened an incident'

    advised = [i for i in incidents if i.advice]
    assert advised, 'the wired advisor should have written an assessment'
    assert all(i.advice == 'SBI authorisations are failing; watch the retry rate.'
               for i in advised)

    # One call per incident, not one per cycle: four cycles ran, and the
    # degradation is re-detected in each of them.
    assert len(client.calls) == len(advised)
    assert len(client.calls) < 4


def test_a_provider_outage_degrades_the_narrative_and_not_the_mitigation():
    """
    The deterministic lane has already decided. This is the property the
    whole two-lane split exists to guarantee.
    """
    from datetime import datetime

    client = FakeClient(raises=RuntimeError('503 from provider'))
    agent = build_agent(
        window_size_minutes=5,
        advisor=build_advisor(client_factory=lambda: client),
    )
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(5):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        assert 'error' not in agent.run_cycle()

    assert agent.state.actions_executed > 0
    assert not agent.state.control_plane.current.is_empty()


def test_the_snapshot_names_the_lane_that_wrote_the_assessment():
    """
    An operator reading an incident is entitled to know whether a model or the
    detector said it. The desk renders that attribution, so the read model has
    to carry it rather than leaving the UI to guess.
    """
    from src import views

    client = FakeClient(reply='Authorisations on this issuer are failing.')
    advised = build_agent(
        window_size_minutes=5,
        advisor=build_advisor(model='gemini-2.5-flash', client_factory=lambda: client),
    )
    assert views.snapshot(advised)['agent']['advisor'] is True
    assert views.snapshot(advised)['agent']['advisor_model'] == 'gemini-2.5-flash'

    with no_api_key():
        bare = build_agent(window_size_minutes=5)
    assert views.snapshot(bare)['agent']['advisor'] is False
    assert views.snapshot(bare)['agent']['advisor_model'] is None


class _Unavailable(Exception):
    """Shaped like the SDK's error: availability is signalled by `code`."""

    def __init__(self, code):
        super().__init__(f"{code} UNAVAILABLE")
        self.code = code


class FlakyClient:
    """Fails the first N models with a transient status, then answers."""

    def __init__(self, unavailable, reply='It recovered.'):
        self.unavailable = set(unavailable)
        self.reply = reply
        self.asked = []

    class _Models:
        def __init__(self, outer):
            self.outer = outer

        def generate_content(self, model, contents, **kwargs):
            self.outer.asked.append(model)
            if model in self.outer.unavailable:
                raise _Unavailable(503)
            return type('R', (), {'text': self.outer.reply})()

    @property
    def models(self):
        return self._Models(self)


def test_an_overloaded_model_falls_through_to_the_next():
    """
    A flagship model under load returns 503. That should cost the assessment
    its wording, not its existence.
    """
    client = FlakyClient(unavailable={'gemini-3.6-flash'})
    advise = build_advisor(
        model='gemini-3.6-flash',
        fallbacks=['gemini-3.5-flash'],
        client_factory=lambda: client,
    )

    assert advise({'incident_id': 'inc-1'}) == 'It recovered.'
    assert client.asked == ['gemini-3.6-flash', 'gemini-3.5-flash']


def test_the_model_that_answered_is_the_one_reported():
    """The desk attributes the assessment, so it must name the right model."""
    client = FlakyClient(unavailable={'gemini-3.6-flash'})
    advise = build_advisor(
        model='gemini-3.6-flash',
        fallbacks=['gemini-3.5-flash'],
        client_factory=lambda: client,
    )

    assert advise.model == 'gemini-3.6-flash', 'the primary before any call'
    advise({'incident_id': 'inc-1'})
    assert advise.model == 'gemini-3.5-flash', 'whichever actually answered'


def test_a_bad_key_is_raised_at_once_rather_than_retried_across_models():
    """
    An error that will fail identically everywhere must not be turned into a
    slow one by trying three more models.
    """
    asked = []

    class Rejecting:
        class _Models:
            def generate_content(self, model, **kwargs):
                asked.append(model)
                raise _Unavailable(400)

        models = _Models()

    advise = build_advisor(
        model='gemini-3.6-flash',
        fallbacks=['gemini-3.5-flash', 'gemini-flash-latest'],
        client_factory=Rejecting,
    )

    try:
        advise({'incident_id': 'inc-1'})
    except _Unavailable as exc:
        assert exc.code == 400
    else:
        raise AssertionError('a 400 should not have been swallowed')

    assert asked == ['gemini-3.6-flash'], 'only the first model should be asked'


def test_a_long_assessment_is_trimmed_to_a_whole_sentence():
    """
    A severed word looks like a bug in the desk rather than a length limit.
    """
    client = FakeClient(reply=(
        'ICICI Bank is degrading badly. The evidence cannot yet separate an outage '
        'from throttling. Watch the raw decline codes to tell them apart.'
    ))
    advise = build_advisor(client_factory=lambda: client, max_chars=100)

    assessment = advise({'incident_id': 'inc-1'})
    assert assessment == 'ICICI Bank is degrading badly. The evidence cannot yet separate an outage from throttling.'
    assert len(assessment) <= 100


def test_a_single_endless_sentence_falls_back_to_a_whole_word():
    client = FakeClient(reply='word ' * 200)
    advise = build_advisor(client_factory=lambda: client, max_chars=52)

    assessment = advise({'incident_id': 'inc-1'})
    assert assessment.endswith('...')
    assert 'wor...' not in assessment, 'must not cut inside a word'
    assert len(assessment) <= 52


def test_an_unreachable_model_is_recorded_on_the_incident_not_just_logged():
    """
    An operator looking at an incident with no assessment should be told the
    model could not be reached, not left to assume the lane had nothing to say.
    """
    from datetime import datetime

    class Exhausted:
        class _Models:
            def generate_content(self, **kwargs):
                raise _Unavailable(429)

        models = _Models()

    agent = build_agent(
        window_size_minutes=5,
        advisor=build_advisor(fallbacks=[], client_factory=Exhausted),
    )
    simulator = build_simulator(control_plane=agent.state)
    simulator.inject_issuer_degradation('SBI', severity=0.9, duration_seconds=3600)

    for _ in range(3):
        agent.process_batch(simulator.generate_stream(count=300, start_time=datetime.now()))
        agent.run_cycle()

    incidents = agent.incident_tracker.all()
    assert incidents, 'the degradation should have opened an incident'
    assert all(i.advice is None for i in incidents)
    assert any(i.advice_unavailable == 'Quota exhausted for the configured models.' for i in incidents)
