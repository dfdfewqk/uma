import tempfile, json, unittest
from pathlib import Path
from course_advisor_r12 import *

class CourseSkillTests(unittest.TestCase):
 def c(self,**kw):
  a=dict(COURSES['도쿄 잔디 2400m']);a.update(kw)
  return Course(venue=a['venue'],meters=a['meters'],surface=a['surface'],direction=a['direction'],end=a['end'],
                style=a.get('style','선행'),season=a.get('season','미정'),weather=a.get('weather','미정'),ground=a.get('ground','미정'),
                event=a.get('event','챔피언스 미팅'))
 def test_distance(self):
  self.assertEqual(distance_type(2400),'중거리');self.assertEqual(distance_type(2500),'장거리')
 def test_green_course(self):
  r=green_rules(self.c(season='봄',weather='맑음',ground='양호'))
  self.assertTrue(r['반시계(좌) 방향○']);self.assertFalse(r['시계(우) 방향○'])
  self.assertTrue(r['근간거리○']);self.assertFalse(r['비근간거리○'])
  self.assertTrue(r['도쿄 경기장○']);self.assertFalse(r['한신 경기장○'])
  self.assertTrue(r['봄 우마무스메○']);self.assertTrue(r['양호한 경기장○']);self.assertFalse(r['진창길○'])
 def test_green_unknown(self):
  r=green_rules(self.c());self.assertIsNone(r['봄 우마무스메○']);self.assertIsNone(r['양호한 경기장○'])
 def test_invalid_ground_rule(self):
  r=green_rules(self.c(ground='포화'));self.assertTrue(r['진창길○']);self.assertFalse(r['양호한 경기장○'])
 def test_course_activation_not_false_percent(self):
  a=advise(self.c(),[Candidate('왕수')])[0]
  self.assertEqual(a.verdict,'우선 검토');self.assertNotIn('%',a.activation)
 def test_worst_case_mismatch(self):
  a=advise(self.c(style='도주'),[Candidate('왕수')])[0]
  self.assertEqual(a.verdict,'각질·거리 불일치')
 def test_phase_mismatch(self):
  a=advise(self.c(end='직선'),[Candidate('왕수')])[0]
  self.assertEqual(a.verdict,'코스 비효율')
 def test_phase_unknown(self):
  a=advise(self.c(end='미검증'),[Candidate('왕수')])[0]
  self.assertEqual(a.verdict,'구간 검증 필요')
 def test_other_skill(self):
  a=advise(self.c(),[Candidate('미등록 스킬',140)])[0]
  self.assertEqual(a.verdict,'판단 보류');self.assertIn('미산출',a.efficiency)
 def test_skill_sample(self):
  a=advise(self.c(),[Candidate('왕수',160,'구매가능',20,15,11)])[0]
  self.assertAlmostEqual(a.observed_rate,0.75)
  self.assertAlmostEqual(a.effective_rate,0.55)
  self.assertLess(a.wilson_range[0],.55);self.assertGreater(a.wilson_range[1],.55)
  self.assertIn('100 Pt',a.efficiency)
 def test_empty_sample(self):
  with self.assertRaises(ValueError):Candidate('왕수',100,'미확인',0,0,0).validate()
 def test_corrupt_sample(self):
  with self.assertRaises(ValueError):Candidate('왕수',100,'미확인',10,9,11).validate()
 def test_incomplete_sample(self):
  with self.assertRaises(ValueError):Candidate('왕수',100,'미확인',10,None,7).validate()
 def test_invalid_money(self):
  with self.assertRaises(ValueError):Candidate('왕수',0).validate()
 def test_sorted_green_first(self):
  names=[a.name for a in advise(self.c(),[Candidate('왕수'),Candidate('시계(우) 방향○'),Candidate('근간거리○')])]
  self.assertEqual(names[0],'근간거리○');self.assertEqual(names[-1],'시계(우) 방향○')
 def test_parse_candidates(self):
  x=parse_candidate_lines('왕수 | 160 | 구매가능 | 20 | 14 | 12\n중거리 직선○ | 110 | 보유')
  self.assertEqual((len(x),x[0].races,x[1].status),(2,20,'보유'))
 def test_no_duplicate(self):
  with self.assertRaises(ValueError):parse_candidate_lines('왕수\n왕수')
 def test_no_fake_sample(self):
  a=advise(self.c(),default_candidates(self.c()))
  self.assertTrue(all(x.effective_rate is None for x in a))
 def test_save(self):
  c=self.c();skill=[Candidate('왕수')];ranked=advise(c,skill)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r12.json';save_report(p,c,skill,ranked)
   x=json.loads(p.read_text('utf8'));self.assertEqual(x['schema'],'r12_course_skill_1')
   self.assertIsNone(x['estimated_winrate']);self.assertFalse(x['user_observation_independently_verified'])
 def test_validation(self):
  with self.assertRaises(ValueError):self.c(meters=0).validate()
  with self.assertRaises(ValueError):self.c(season='임의').validate()
 def test_season_name(self):
  r=green_rules(self.c(season='가을',weather='흐림'))
  self.assertTrue(r['가을 우마무스메○']);self.assertTrue(r['흐린 날○'])
 def test_weather_other(self):
  r=green_rules(self.c(weather='비'));self.assertFalse(r['맑은 날○'])
 def test_user_cost_only(self):
  a=advise(self.c(),[Candidate('왕수',220)])[0]
  self.assertIn('실전 효율 미산출',a.efficiency)
 def test_unknown_skill_not_recommended(self):
  a=advise(self.c(),[Candidate('가짜스킬')])[0]
  self.assertEqual(a.order,4)

if __name__=='__main__': unittest.main()
