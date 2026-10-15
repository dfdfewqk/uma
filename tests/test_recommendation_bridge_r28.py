import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from dataclasses import replace
from unittest.mock import Mock
from PIL import Image

from uma_core import RunProfile,TurnState,STATS
from training_r5 import FIELDS
from live_training_r22 import TrainingCaptureSession
from recommendation_bridge_r28 import (create_handoff,save_handoff,load_handoff,cancel_handoff,
    HintGate,HandoffError,validate_handoff,TTL_SECONDS)
from button_detection_r21 import ButtonHit

NOW=datetime(2026,10,15,10,0,tzinfo=timezone.utc)


def ready():
    state=TurnState(turn_label='주니어급 9월 전반',energy=88,remaining_turns=45,island_tickets=0)
    profile=RunProfile(event='챔피언스 미팅',distance='중거리',style='선행')
    session=TrainingCaptureSession(state.turn_label,window_id=1001)
    # Different synthetic images per option (NOT real-game performance data).
    for i,label in enumerate(STATS):
        picture=Image.new('RGB',(900,600),(i*31+10,15,18))
        digest=session.register_capture(label,picture,window_id=1001)
        fields={f:'0' for f in FIELDS}
        fields['스피드 상승']=str(10+i*3)
        fields['스킬 Pt 상승']='18'
        fields['실패 확률']='0'
        fields['체력 변화']='-15'
        session.confirm(label,fields,digest)
    report=session.compare(profile,state)
    obj=create_handoff(session,report,profile,state,window_id=1001,window_size=(900,600),now=NOW)
    return session, report,profile,state,obj


class BridgeTests(unittest.TestCase):
    def test_export_success_and_no_fake_game_claim(self):
        *_,obj=ready()
        self.assertIn(obj['suggestion'],STATS)
        self.assertIn('heuristic',obj['advice_kind'].lower())
        self.assertEqual(len(obj['frame_hashes']),5)
        self.assertNotIn('click',obj)

    def test_save_load_expiry(self):
        *_,obj=ready()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'hint.json';save_handoff(obj,p,now=NOW)
            self.assertEqual(load_handoff(p,now=NOW+timedelta(seconds=45)),obj)
            with self.assertRaises(HandoffError):load_handoff(p,now=NOW+timedelta(seconds=121))
            cancel_handoff(p);self.assertIsNone(load_handoff(p))

    def test_no_source_image_and_mixed_frames(self):
        sess,rep,profile,state,_=ready()
        sess.capture_origin[STATS[0]]='file'
        with self.assertRaisesRegex(HandoffError,'직접 게임'):
            create_handoff(sess,rep,profile,state,window_id=1001,window_size=(900,600),now=NOW)

    def test_source_window_mismatch(self):
        sess,rep,profile,state,_=ready()
        with self.assertRaises(HandoffError):
            create_handoff(sess,rep,profile,state,window_id=800,window_size=(900,600),now=NOW)

    def test_resize_blocks_publish(self):
        sess,rep,profile,state,_=ready()
        with self.assertRaises(HandoffError):
            create_handoff(sess,rep,profile,state,window_id=1001,window_size=(860,600),now=NOW)

    def test_turn_change_blocks_publish(self):
        sess,rep,profile,state,_=ready()
        sess.turn_id='시니어급 5월'
        with self.assertRaises(HandoffError):
            create_handoff(sess,rep,profile,state,window_id=1001,window_size=(900,600),now=NOW)

    def test_missing_comparison_blocks_publish(self):
        sess,rep,profile,state,_=ready()
        del sess.options[STATS[-1]]
        rep=sess.compare(profile,state)
        with self.assertRaises(HandoffError):
            create_handoff(sess,rep,profile,state,window_id=1001,window_size=(900,600),now=NOW)

    def test_tampered_hash_and_invalid_expiry(self):
        *_,obj=ready()
        altered=dict(obj);altered['frame_hashes']=dict(obj['frame_hashes']);altered['frame_hashes'][STATS[0]]='bad'
        with self.assertRaises(HandoffError):validate_handoff(altered,now=NOW)
        altered=dict(obj);altered['expires_at']=(NOW+timedelta(days=1)).isoformat()
        with self.assertRaises(HandoffError):validate_handoff(altered,now=NOW)

    def test_bad_file_size(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'hint';p.write_bytes(b'a'*50000)
            with self.assertRaises(HandoffError):load_handoff(p)

    def test_island_ticket_must_be_reviewed(self):
        session,report,profile,state,_=ready()
        state.island_tickets=1
        new_report=session.compare(profile,state)
        with self.assertRaises(HandoffError):
            create_handoff(session,new_report,profile,state,window_id=1001,window_size=(900,600),now=NOW)


class GateTests(unittest.TestCase):
    def setUp(self):
        *_,self.obj=ready()
        self.hit=ButtonHit(self.obj['suggestion'],.45,.83,.98,76,48)
        self.gate=HintGate()

    def observe(self,**updates):
        params={'hwnd':1001,'size':(900,600),'scene':'훈련','hits':[self.hit],'active':True,'now':NOW+timedelta(seconds=9)}
        params.update(updates)
        return self.gate.observe(self.obj,**params)

    def test_hint_requires_validated_button(self):
        self.assertIsNotNone(self.observe())
        self.assertEqual(self.observe().label,self.obj['suggestion'])

    def test_wrong_scene_revokes_forever(self):
        self.assertIsNotNone(self.observe())
        self.assertIsNone(self.observe(scene='스킬'))
        self.assertIsNone(self.observe(scene='훈련'))
        self.assertIn(self.obj['id'],self.gate.revoked)

    def test_changed_window_revokes(self):
        self.assertIsNotNone(self.observe())
        self.assertIsNone(self.observe(hwnd=333))
        self.assertIsNone(self.observe())

    def test_focus_loss_revokes(self):
        self.assertIsNotNone(self.observe())
        self.assertIsNone(self.observe(active=False))
        self.assertIsNone(self.observe())

    def test_resize_revokes(self):
        self.assertIsNotNone(self.observe())
        self.assertIsNone(self.observe(size=(1000,600)))
        self.assertIsNone(self.observe())

    def test_missing_or_double_hit(self):
        self.assertIsNone(self.observe(hits=[]))
        self.assertIsNone(self.observe(hits=[self.hit,self.hit]))
        self.assertIsNone(self.observe(hits=[replace(self.hit,score=.5)]))

    def test_new_handoff_reactivates(self):
        self.assertIsNotNone(self.observe())
        self.observe(scene='스킬')
        another=dict(self.obj);another['id']='0b0985e2-1030-44a4-bbd2-44ce45d724e6'
        self.assertIsNotNone(self.gate.observe(another,hwnd=1001,size=(900,600),scene='훈련',hits=[self.hit],active=True,now=NOW))

    def test_expired_bridge_cannot_show(self):
        self.assertIsNone(self.observe(now=NOW+timedelta(seconds=300)))


if __name__=='__main__':unittest.main()
