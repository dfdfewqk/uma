"""Coverage for historical event strategy provenance and R13 recommendation safety."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from plan_r13 import load_pack,recommend,available_cards,export_plan,STYLES,TYPES

class R13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=load_pack()

    def test_four_jp_events(self):
        self.assertEqual(len(self.data['events']),4)
        self.assertEqual({e['year_month'] for e in self.data['events']},{'2025-07','2025-08','2025-09','2025-10'})
    def test_events_mixed(self):
        self.assertEqual([e['kind'] for e in self.data['events']].count('리그 오브 히어로즈'),1)
    def test_16_strategies(self):
        self.assertEqual(len(self.data['profiles']),16)
        self.assertEqual({p['style'] for p in self.data['profiles']},set(STYLES))
    def test_no_kr_conflation(self):
        self.assertEqual(self.data['region'],'JP');self.assertFalse(self.data['applied_to_KR'])
    def test_patch_timing(self):self.assertEqual(self.data['patch_after'],'2025-06-30')
    def test_core_green_conditions(self):
        self.assertEqual([(e['meters'],e['direction']) for e in self.data['events']],[(2200,'우회전'),(2600,'우회전'),(2000,'우회전'),(1200,'좌회전')])
    def test_every_combo_has_results_and_unique_ids(self):
        for e in self.data['events']:
            for style in STYLES:
                with self.subTest(e=e['id'],style=style):
                    r=recommend(e['id'],style,data=self.data)
                    self.assertEqual(len(r.selections),6)
                    self.assertEqual(len({c['id'] for c in r.selections}),6)
    def test_deck_has_friend_and_types(self):
        r=recommend('jp-2025-07-cm','선행',data=self.data)
        self.assertEqual({c['type'] for c in r.selections},set(TYPES))
    def test_changing_style_alters_primary(self):
        a=recommend('jp-2025-09-cm','선입',data=self.data)
        b=recommend('jp-2025-09-cm','도주',data=self.data)
        self.assertIn('admirer-sp',{c['id'] for c in a.selections})
        self.assertNotIn('admirer-sp',{c['id'] for c in b.selections})
    def test_factor_cards_separate(self):
        a=recommend('jp-2025-08-loh','도주','인자작',data=self.data)
        self.assertTrue(a.selections)
        self.assertTrue(all(c['purpose']=='인자작' for c in a.selections))
    def test_owned_filter_requires_owned_cards(self):
        r=recommend('jp-2025-09-cm','선입',owned={'admirer-sp'},data=self.data)
        self.assertEqual(len(r.selections),1)
        self.assertEqual(r.selections[0]['id'],'admirer-sp')
        self.assertTrue(r.missing_types)
    def test_no_owned_does_not_claim_ownership(self):
        r=recommend('jp-2025-07-cm','선행',data=self.data)
        self.assertTrue(any('미확인' in x for x in r.caveats))
    def test_missing_friend_warning(self):
        r=recommend('jp-2025-07-cm','선행',owned={'almond-sp'},data=self.data)
        self.assertIn('친구',r.missing_types)
        self.assertTrue(any('터커' in x for x in r.caveats))
    def test_loh_weather_is_unknown(self):
        e=self.data['events'][1]
        self.assertEqual(e['weather'],'미정')
        self.assertEqual(e['ground'],'미정')
    def test_flat_courses_mark_hills(self):
        r=recommend('jp-2025-10-cm','추입',data=self.data)
        self.assertTrue(any('오르막' in t for t in r.caveats))
    def test_one_course_specific_inheritance(self):
        r=recommend('jp-2025-09-cm','선입',data=self.data)
        self.assertTrue(any(x['unique_skill']=='ずっとずっと輝いて' for x in r.ancestors))
    def test_only_manual_reference_stats(self):
        a=recommend('jp-2025-09-cm','선입',data=self.data)
        b=recommend('jp-2025-09-cm','도주',data=self.data)
        self.assertEqual(a.stats_reference['스태미나'],1200)
        self.assertEqual(b.stats_reference,{})
    def test_no_fake_probability(self):
        r=recommend('jp-2025-07-cm','선행',data=self.data)
        self.assertNotIn('win_rate',r.serializable())
        self.assertNotIn('activation_probability',r.serializable())
    def test_source_urls_in_result(self):
        r=recommend('jp-2025-09-cm','선입',data=self.data)
        self.assertTrue(all(u.startswith('https://') for u in r.provenance.values()))
    def test_export_and_collision_safe(self):
        r=recommend('jp-2025-09-cm','선입',data=self.data)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'plan.json'
            export_plan(p,r)
            self.assertEqual(json.loads(p.read_text(encoding='utf8'))['style'],'선입')
            with self.assertRaises(FileExistsError):export_plan(p,r)
    def test_bad_target_rejected(self):
        with self.assertRaises(ValueError):recommend('nope','선행',data=self.data)
        with self.assertRaises(ValueError):recommend('jp-2025-07-cm','none',data=self.data)
        with self.assertRaises(ValueError):recommend('jp-2025-07-cm','선행','auto',data=self.data)
    def test_reject_invalid_reference(self):
        d=copy.deepcopy(self.data)
        d['cards'][0]['source_ids']=['invented']
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.json';p.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises(ValueError):load_pack(p)
    def test_reject_kr_pack(self):
        d=copy.deepcopy(self.data);d['applied_to_KR']=True
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.json';p.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
            with self.assertRaises(ValueError):load_pack(p)

if __name__=='__main__':unittest.main()
