"""Regresje rozbieżności oraz granica surowe dane / zapis pomiaru."""
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
import random

import pytest

from app.services.fatigue_engine import FatigueEngine, CanonicalMeasurementInput

T = 1780000000


def observation(id, **changes):
    data = dict(id=id, title='', body='', start=T-100, end=T+100,
                voted_at=T-50, category='treasury', lifecycle_id=id,
                source_domain='snapshot')
    data.update(changes)
    return SimpleNamespace(**data)


def measure(target, history, ecosystem=None):
    return FatigueEngine().compute_per_event(
        'x', target, history, now=datetime.fromtimestamp(T, timezone.utc),
        ecosystem_proposals=ecosystem)


def test_remis_okien_dokladny_kontrprzyklad():
    target = observation('target')
    a = observation('a', lifecycle_id='lc', end=T-1)
    b = observation('b', lifecycle_id='lc')
    first = measure(target, [a, b])
    second = measure(target, [b, a])
    assert first.identity.measurement_id == second.identity.measurement_id
    assert asdict(first) == asdict(second)
    assert first.metrics.voted_concurrent == 0
    assert first.fatigue_score == 22.2


def test_czas_rozne_znaczenie_rozne_id():
    target = observation('target')
    a = observation('a', voted_at=0, cast_at=T-50, start=T-40*86400)
    b = observation('a', voted_at=T-50, cast_at=T-50, start=T-40*86400)
    first, second = measure(target, [a], []), measure(target, [b], [])
    assert first.fatigue_score != second.fatigue_score
    assert first.identity.measurement_id != second.identity.measurement_id


def test_tekst_granica_pol_rozne_id():
    a = observation('target', title='x\n'+'one '*710, body='two')
    b = observation('target', title='x', body='one '*710+'\ntwo')
    assert a.title+'\n'+a.body == b.title+'\n'+b.body
    first, second = measure(a, [], []), measure(b, [], [])
    assert first.fatigue_score != second.fatigue_score
    assert first.identity.measurement_id != second.identity.measurement_id


def test_odtworzenie_bez_zrodel_i_biezacego_yaml(monkeypatch):
    target = observation('target', body='word '*200)
    history = [observation('a', category='protocol')]
    result = measure(target, history, [])
    target.body = 'zmieniona treść'
    history[0].category = 'treasury'
    monkeypatch.setattr(FatigueEngine, '_load_config', lambda self: pytest.fail('odczyt YAML'))
    restored = FatigueEngine.replay(result.identity.manifest())
    assert asdict(restored) == asdict(result)
    broken = result.identity.manifest()
    broken['prepared_input']['target']['body'] = 'inna treść'
    with pytest.raises(ValueError, match='skrótem'):
        FatigueEngine.replay(broken)


@pytest.mark.parametrize('seed', range(10))
def test_granica_serializacji_i_permutacje(seed):
    rng = random.Random(seed)
    target = observation('target', category='')
    history = [observation(str(i % 3), lifecycle_id=str(i % 2),
                           voted_at=T-rng.randrange(1, 10),
                           category=rng.choice(['', 'treasury', 'protocol'])) for i in range(8)]
    history.append(observation('future', voted_at=T+1, category='future', lifecycle_id='0'))
    ecosystem = [observation('eco', end=T+rng.choice([-1, 1])) for _ in range(3)]
    original = measure(target, history, ecosystem)
    rng.shuffle(history)
    rng.shuffle(ecosystem)
    permuted = measure(target, history, ecosystem)
    assert asdict(original) == asdict(permuted)
    prepared = CanonicalMeasurementInput.from_dict(original.identity.prepared_input)
    for item in [target, *history, *ecosystem]:
        item.title = 'zmiana źródła'
        item.category = 'inna'
        item.unprojected_field = object()
    assert asdict(FatigueEngine.compute_prepared(prepared)) == asdict(original)
    assert all(p['id'] != 'future' for p in prepared.to_dict()['history'])


def test_kategoria_najwczesniejsza_znana_i_jawny_konflikt():
    history = [observation('a', lifecycle_id='lc', category='', voted_at=T-300),
               observation('b', lifecycle_id='lc', category='protocol', voted_at=T-200),
               observation('c', lifecycle_id='lc', category='treasury', voted_at=T-100)]
    result = measure(observation('target'), history, [])
    assert result.components.novelty == 1.0
    conflict = result.identity.input_conflicts[0]
    assert conflict['selected_stage_id'] == 'b'
    assert conflict['selected_category'] == 'protocol'
    without_conflict = measure(observation('target'), history[:2], [])
    assert result.identity.eligibility == without_conflict.identity.eligibility
