"""R14 chronology/source safety and six-ancestor candidate placement."""
import copy,json,tempfile,unittest
from datetime import date
from pathlib import Path
from lineage_r14 import load_r14,recommend_lineage,event_calendar,base_name,export_r14_json
from plan_r13 import load_pack

class R14Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r13=load_pack();cls.r14=load_r14(r13=cls.r13)

    def test_four_events_mapping(self):
        self.assertEqual(len(self.r14['events']),4)
        self.assertEqual({x['event_id'] for x in self.r14['events']},{x['id'] for x in self.r13['events']})
    def test_first_kr_event_date(self):
        d=event_calendar('jp-2025-07-cm','2026-10-15',self.r13,self.r14)
        self.assertEqual(d['kr_period'],'2026-11-13 ~ 2026-11-19')
        self.assertEqual(d['days_left'],29)
        self.assertEqual(d['milestones'][1]['start'],'2026-10-09')
    def test_forecasts_do_not_invent_date(self):
        for eid in ('jp-2025-08-loh','jp-2025-09-cm','jp-2025-10-cm'):
            d=event_calendar(eid,'2026-10-15',self.r13,self.r14)
            self.assertIsNone(d['kr_period']);self.assertTrue(d['kr_month_estimate'])
            self.assertTrue(all(m['start'] is None for m in d['milestones']))
    def test_prep_prev_year(self):
        d=event_calendar('jp-2025-09-cm','2026-10-15',self.r13,self.r14)
        self.assertEqual(d['approx_prep_month'],'2026-12')
    def test_no_duplicate_in_six(self):
        for event in self.r13['events']:
            for style in ('도주','선행','선입','추입'):
                with self.subTest(event=event['id'],style=style):
                    r=recommend_lineage(event['id'],style,'골드 쉽',r13=self.r13,r14=self.r14)
                    names=[base_name(x['name']) for b in r['branches'] for x in [b['parent']]+b['grandparents'] if x]
                    self.assertEqual(len(names),len(set(names)))
                    self.assertNotIn('골드 쉽',names)
    def test_two_parents_four_grands(self):
        x=recommend_lineage('jp-2025-09-cm','선입','골드 쉽',r13=self.r13,r14=self.r14)
        self.assertEqual(len(x['branches']),2)
        self.assertTrue(all(len(b['grandparents'])==2 for b in x['branches']))
        self.assertTrue(all(b['parent'] for b in x['branches']))
    def test_prioritize_source_specific_parent(self):
        r=recommend_lineage('jp-2025-09-cm','선입','골드 쉽',r13=self.r13,r14=self.r14)
        self.assertEqual(r['branches'][0]['parent']['name'],'신의상 라인 크래프트')
    def test_no_same_character_different_outfit(self):
        self.assertEqual(base_name('신년 키타산 블랙'),'키타산 블랙')
        r=recommend_lineage('jp-2025-09-cm','도주','라인 크래프트',r13=self.r13,r14=self.r14)
        self.assertNotIn('라인 크래프트',[base_name(b['parent']['name']) for b in r['branches'] if b['parent']])
    def test_owned_restriction_keeps_empty(self):
        r=recommend_lineage('jp-2025-07-cm','도주','골드 쉽',['세이운 스카이'],self.r13,self.r14)
        self.assertEqual(r['branches'][0]['parent']['name'],'세이운 스카이')
        self.assertIsNone(r['branches'][1]['parent'])
        self.assertTrue(all(not y for b in r['branches'] for y in b['grandparents']))
    def test_factor_types_are_not_skill_probs(self):
        r=recommend_lineage('jp-2025-08-loh','선입',r13=self.r13,r14=self.r14)
        self.assertEqual(set(r['factor_targets']),{'red','green','white','blue'})
        self.assertNotIn('probability',r)
    def test_every_candidate_has_source(self):
        r=recommend_lineage('jp-2025-10-cm','추입',r13=self.r13,r14=self.r14)
        self.assertTrue(r['sources'])
        for b in r['branches']:
            for c in [b['parent']]+b['grandparents']:
                if c:self.assertTrue(c['source_ids'])
    def test_export_and_no_overwrite(self):
        r=recommend_lineage('jp-2025-09-cm','추입',r13=self.r13,r14=self.r14)
        cal=event_calendar('jp-2025-09-cm','2026-10-15',self.r13,self.r14)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'result.json';export_r14_json(p,r,cal)
            self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['schema'],'r14-plan.v1')
            with self.assertRaises(FileExistsError):export_r14_json(p,r,cal)
    def test_reject_wrong_status(self):
        c=copy.deepcopy(self.r14);c['events'][1]['kr_end']='2026-12-19'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises(ValueError):load_r14(p,self.r13)
    def test_reject_unknown_source(self):
        c=copy.deepcopy(self.r14);c['events'][0]['sources']=['fake']
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_text(json.dumps(c,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises(ValueError):load_r14(p,self.r13)
    def test_unknown_event(self):
        with self.assertRaises(ValueError):event_calendar('unlisted',r13=self.r13,r14=self.r14)
        with self.assertRaises(ValueError):recommend_lineage('unlisted','선입',r13=self.r13,r14=self.r14)

if __name__=='__main__':unittest.main()
