"""An evaluation command must fail closed on missing or incorrect evidence."""
from dataclasses import replace
import pytest
from scripts import evaluate as ev


def result(**changes):
    base = ev.VendorResult('V', 'N', 'eliminate', '7', 'not_compliant', True,
                           outcome='TP', clause_matched=True)
    return replace(base, **changes)


@pytest.mark.parametrize('expected,actual,want', [
    ('7', ['7 Manufacturer authorization'], True),
    ('7', ['27'], False), ('1', ['21', '1.1'], False),
    ('1.1(4)', ['1.1(4) Similar works'], True),
    ('1.1(4)', ['1.1(4)(a)'], False),
    ('28.1 vi)', ['28.1   VI) Liquidity'], True),
    ('', ['7'], None), ('—', ['7'], None),
    ('NIT clauses 5, 6, 8 and 20', ['20', '8', '6', '5'], True),
    ('NIT clauses 1, 5, 6 and 8', ['8', '6', '5'], False),
    ('NIT clauses 5, 6, 8 and 20', ['5', '6', '8', '120'], False),
    ('Clauses 1.1(4), 2.6(b)', ['1.1(4)', '2.6(b)'], True),
    ('NIT clause 6 and Process Compliance Statement requirement', ['6'], False),
])
def test_clause_check_uses_full_references(expected, actual, want):
    assert ev._clause_matches(expected, actual) is want


def test_named_requirement_needs_both_clause_and_matching_blocker():
    expected = "NIT clause 6 and Process Compliance Statement requirement"
    assert ev._evidence_matches(expected, ["6"], ["Submit Process Compliance Statement (Annexure-II)"])
    assert not ev._evidence_matches(expected, ["6"], ["Submit Demand Draft"])
    assert not ev._evidence_matches(expected, ["8"], ["Submit Process Compliance Statement (Annexure-II)"])


@pytest.mark.parametrize('rows,passed', [
    ([result()], True), ([], False),
    ([result(outcome='FP')], False), ([result(outcome='FN')], False),
    ([result(outcome='SKIP')], False),
    ([result(clause_matched=None)], False), ([result(clause_matched=False)], False),
    ([result(outcome='UNASSESSED')], False),
])
def test_production_gate_requires_every_result_and_reason(rows, passed):
    assert ev.summarise(rows)['passed'] is passed


def test_zero_precision_and_recall_produces_zero_f1():
    summary = ev.summarise([result(outcome='FP'), result(outcome='FN')])
    assert summary['f1'] == 0


def test_unknown_reason_is_reported_separately():
    summary = ev.summarise([result(), result(clause_matched=None)])
    assert summary['reason_unverified'] == 1
    assert summary['reason_accuracy'] == 0.5


def test_cli_returns_nonzero_for_bad_evaluation(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.argv', ['evaluate', '--json', str(tmp_path/'result.json')])
    monkeypatch.setattr(ev, 'load_ground_truth', lambda _: {})
    monkeypatch.setattr(ev, 'evaluate', lambda *_: [result(outcome='FP')])
    assert ev.main() == 1
    assert (tmp_path/'result.json').exists()


@pytest.mark.parametrize('contents', [
    'vendor_id,notification_id,intended_status,intended_failed_clause\nV,N,pass,\nV,N,pass,\n',
    'vendor_id,notification_id,intended_status,intended_failed_clause\nV,N,pas,\n',
])
def test_invalid_ground_truth_is_rejected(contents, tmp_path):
    path = tmp_path/'truth.csv'; path.write_text(contents)
    with pytest.raises(ValueError): ev.load_ground_truth(path)
