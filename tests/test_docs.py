"""
Documentation that can be checked.

Most prose cannot be tested, but a surprising amount of what goes stale in a
README is mechanically verifiable: a command that no longer exists, a file path
that moved, an install step that fails. This suite covers exactly that class.

It exists because the docs had drifted badly enough to be actively misleading.
QUICKSTART told a new user to verify their install with `import numpy, scipy`
- neither of which this project has ever depended on, so the very first step
failed. ARCHITECTURE described a system with no control plane, no holdouts, no
journal and no statistics, and quoted a detection precision of 85-95% that was
never measured. PERFORMANCE published a throughput figure roughly a hundredfold
below the real one, produced by a benchmark that timed a reconstructed
pseudo-cycle rather than the loop.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ['README.md', 'QUICKSTART.md', 'ARCHITECTURE.md', 'PERFORMANCE.md']


def text(name):
    return (ROOT / name).read_text()


def all_docs():
    return {name: text(name) for name in DOCS}


# ── Dependencies the project does not have ───────────────────────────────────

def test_no_document_tells_a_reader_to_import_numpy_or_scipy():
    """
    The regression. QUICKSTART's install-verification step was
    `python -c "import numpy, scipy"`, which fails - the agent core has no
    third-party dependencies at all and the statistics are implemented against
    the standard library.
    """
    for name, body in all_docs().items():
        for line in body.splitlines():
            if 'import numpy' in line or 'import scipy' in line:
                raise AssertionError(f"{name} tells the reader to import a "
                                     f"dependency this project lacks: {line.strip()}")


def test_the_scientific_stack_stays_out_of_requirements():
    """
    The statistics are stdlib by design, and several documents say so. If
    NumPy or SciPy ever gets added, those statements become false in a way
    nothing else here would catch.
    """
    declared = (ROOT / 'requirements.txt').read_text().lower()

    for package in ('numpy', 'scipy', 'torch'):
        assert package not in declared, (
            f"{package} is now a dependency; the docs claim the core has none"
        )


# ── Commands the docs tell a reader to run ───────────────────────────────────

def test_referenced_entry_points_exist():
    for path in (
        'web/server.py', 'main.py', 'api/main.py', 'dashboard/app.py',
        'src/utils/benchmark.py', 'requirements.txt', 'docker-compose.yml',
    ):
        assert (ROOT / path).is_file(), f"docs reference {path}, which is missing"


def test_documented_main_modes_are_real():
    modes = set(re.findall(r'--mode (\w+)', ' '.join(all_docs().values())))
    declared = (ROOT / 'main.py').read_text()

    assert modes, 'the docs should show at least one run mode'
    for mode in modes:
        assert f"'{mode}'" in declared, (
            f"docs show `--mode {mode}`, which main.py does not accept"
        )


def test_documented_config_files_exist():
    for name in ('agent_config.yaml', 'safety_rules.yaml', 'simulation_config.yaml'):
        assert (ROOT / 'config' / name).is_file()


def test_the_console_command_matches_what_docker_runs():
    """
    The image shipped Streamlit while every document described the console -
    so the one artefact a reviewer would actually run served a different UI
    from the one being documented.
    """
    compose = text('docker-compose.yml')
    dockerfile = text('Dockerfile')

    assert 'web/server.py' in compose
    assert 'web/server.py' in dockerfile


# ── Source paths named in prose ──────────────────────────────────────────────

def test_every_source_path_mentioned_in_the_docs_exists():
    pattern = re.compile(r'`(src/[\w/]+\.py|web/[\w/]+\.\w+|tests/[\w/]+\.py)`')

    missing = []
    for name, body in all_docs().items():
        for path in set(pattern.findall(body)):
            if not (ROOT / path).exists():
                missing.append(f"{name}: {path}")

    assert not missing, f"documented paths that do not exist: {missing}"


def test_documented_symbols_exist_where_the_docs_say():
    """Named functions and classes drift when code is refactored."""
    expectations = {
        'src/analysis/statistics.py': ['compare_proportions', 'CusumDetector'],
        'src/analysis/experiment.py': ['has_sufficient_data'],
        'src/control/plane.py': ['class ControlPlane'],
        'src/control/publish.py': ['class PolicyClient', 'class PolicyPublisher'],
        'src/traffic/gateway.py': ['class PaymentGatewaySource', 'def signals'],
        'src/agent/advisors.py': ['def build_advisor'],
        'src/models/state.py': ['ACTION_AUTHORIZATION'],
        'src/views.py': ['def snapshot'],
    }

    for path, symbols in expectations.items():
        body = (ROOT / path).read_text()
        for symbol in symbols:
            assert symbol in body, f"{path} no longer defines {symbol}"


# ── Measured claims ──────────────────────────────────────────────────────────

def test_the_benchmark_the_docs_cite_actually_runs():
    """
    PERFORMANCE.md tells the reader to run this and quotes its output. A
    benchmark that no longer imports makes every number in that document
    unverifiable.
    """
    from src.utils.benchmark import run_benchmark

    metrics = run_benchmark(cycles=3, batch=50)

    assert metrics['cycle_ms']
    assert metrics['transactions'] == 150
    assert metrics['ingest_throughput'] > 0


def test_the_benchmark_reports_the_phases_the_docs_break_down():
    """
    The phase table in PERFORMANCE.md comes from run_cycle's own timings. If
    a phase stops being reported the table becomes fiction, which is what it
    was before the cycle measured itself.
    """
    from src.utils.benchmark import PHASES, run_benchmark

    metrics = run_benchmark(cycles=3, batch=50)

    for phase in PHASES:
        assert metrics['phase_ms'].get(phase), f"{phase} is documented but not measured"


def test_phase_timings_account_for_the_cycle():
    """
    The parts have to add up to the whole, or the breakdown is apportioned
    rather than measured. Timed inside the cycle, they do.
    """
    import statistics

    from src.utils.benchmark import run_benchmark

    metrics = run_benchmark(cycles=5, batch=100)
    accounted = sum(
        statistics.mean(v) for v in metrics['phase_ms'].values() if v
    )
    cycle = statistics.mean(metrics['cycle_ms'])

    assert 0.80 <= accounted / cycle <= 1.0, (
        f"phases account for {accounted / cycle:.0%} of the cycle"
    )


def test_no_document_quotes_unmeasured_accuracy_figures():
    """
    ARCHITECTURE quoted "Pattern detection precision: ~85-95%" and an MTTD of
    30 seconds against real payment traffic there is no way to measure, since
    there is no real payment traffic. Invented numbers are worse than absent
    ones: a reader cannot tell them apart from the measured ones beside them.
    """
    banned = [
        r'precision[:\s]+~?\s*8[05]-9[05]%',
        r'recall[:\s]+~?\s*\d+-\d+%',
        r'MTTD[:\s]+~?\s*\d+\s*second',
    ]

    for name, body in all_docs().items():
        for pattern in banned:
            match = re.search(pattern, body, re.IGNORECASE)
            assert not match, f"{name} quotes an unmeasured figure: {match.group(0)}"
