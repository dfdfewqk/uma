import unittest
from ranker_strategy_r56 import inspect_strategy, StrategyContext
from training_evidence_r55 import TrainingEvidenceView, TrainingOptionEvidence, TRAININGS


def evidence(n=5, all_numeric=False):
    opts=[]
    for i, name in enumerate(TRAININGS[:n]):
        opts.append(TrainingOptionEvidence(name,(5+i,5,0,0,0),
           failure_rate=0 if all_numeric else None,
           energy_cost=12 if all_numeric else None,
           skill_point_gain=10 if all_numeric else None))
    return TrainingEvidenceView(None,tuple(opts),n,n if all_numeric else 0,'test')


class StrategyTests(unittest.TestCase):
    def test_incomplete_does_not_select(self):
        x=inspect_strategy(evidence(3))
        self.assertIn('3/5',x.label)
        self.assertIsNone(x.observed_stat_leader)
        self.assertFalse(x.game_input_allowed)
        self.assertFalse(x.decision_ready)
        self.assertFalse(x.kr_strategy_verified)

    def test_all_five_stat_only_is_not_optimal(self):
        x=inspect_strategy(evidence())
        self.assertEqual(x.observed_stat_leader, TRAININGS[-1])
        self.assertFalse(x.comparable_options)
        self.assertIn('보류',x.label)
        self.assertFalse(x.ml_training_label)

    def test_numeric_pareto_is_cautious(self):
        x=inspect_strategy(evidence(all_numeric=True))
        self.assertEqual(x.comparable_options,(TRAININGS[-1],))
        self.assertFalse(x.decision_ready)
        self.assertFalse(x.game_input_allowed)

    def test_context_only_when_explicit(self):
        a=inspect_strategy(evidence(),StrategyContext(phase='초반'))
        b=inspect_strategy(evidence(),StrategyContext())
        self.assertTrue(any('인연 형성' in n for n in a.notes))
        self.assertFalse(any('인연 형성' in n for n in b.notes))

    def test_server_and_unknown_ticket_abstain(self):
        self.assertIn('불일치',inspect_strategy(evidence(),StrategyContext(server='JP')).label)
        self.assertIn('검증 실패',inspect_strategy(evidence(),StrategyContext(island_tickets=-1)).label)

    def test_explicit_ticket_does_not_invent_expiry(self):
        x=inspect_strategy(evidence(),StrategyContext(island_tickets=2))
        self.assertTrue(any('시점 미검증' in n for n in x.notes))
        self.assertFalse(x.decision_ready)

    def test_rejects_relabelled_verified_or_automatic_evidence(self):
        from dataclasses import replace
        self.assertIn('불일치',inspect_strategy(replace(evidence(),source='synthetic')).label)
        self.assertIn('불일치',inspect_strategy(replace(evidence(),game_input_allowed=True)).label)


if __name__ == '__main__': unittest.main()
