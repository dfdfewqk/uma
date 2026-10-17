"""R50 batch checkpoint: never overwrite earlier outcomes or auto-resume unknown run."""
from __future__ import annotations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import unittest

from batch_checkpoint_r50 import (
    BatchCheckpoint,save_checkpoint,load_checkpoint,
    restore_finished_only,current_snapshot,
)
from autopilot_bridge_r50 import LiveBatchSupervisor
from target_selector_r39 import Target,kind_for_round


def goal():
    return Target(kind_for_round(2),2,"추입")


def record(*,ids=("run-1",),active=None,pending=None,total=20):
    return BatchCheckpoint("loh-2","추입","island_post_patch_v1",total,
                           ids,{k:"ordinary" for k in ids},active,pending).validate()


class CheckpointTests(unittest.TestCase):
    def test_atomic_round_trip_preserves_identical_record(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"r50_batch_progress.json"
            saved=record()
            save_checkpoint(p,saved)
            self.assertEqual(load_checkpoint(p,goal(),20),saved)
            runner=LiveBatchSupervisor(goal(),20,dry_run=True)
            restore_finished_only(runner,saved)
            self.assertEqual(runner.planner.remaining,19)
            self.assertEqual(runner.planner.completed_ids,{"run-1"})
            self.assertIsNone(runner.active_run_id)
            self.assertEqual(current_snapshot(runner).completed_ids,("run-1",))

    def test_checkpoint_pending_or_current_run_blocks_unreviewed_resume(self):
        for snap in (record(active="running-now"),record(pending="free_tp_item")):
            with self.subTest(snapshot=snap):
                runner=LiveBatchSupervisor(goal(),20,dry_run=True)
                with self.assertRaises(ValueError):
                    restore_finished_only(runner,snap)

    def test_different_plan_not_imported(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"batch.json"
            save_checkpoint(p,record())
            with self.assertRaises(ValueError):
                load_checkpoint(p,Target(kind_for_round(1),1,"추입"),20)
            with self.assertRaises(ValueError):
                load_checkpoint(p,goal(),30)
            self.assertEqual(load_checkpoint(p,goal(),20),record())

    def test_no_completed_ids_can_disappear(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"batch.json"
            save_checkpoint(p,record(ids=("run-1","run-2")))
            old=p.read_bytes()
            with self.assertRaises(ValueError):
                save_checkpoint(p,record(ids=("run-1",)))
            self.assertEqual(p.read_bytes(),old)

    def test_completed_outcome_never_relabelled(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"batch.json"
            save_checkpoint(p,record())
            corrupt=BatchCheckpoint("loh-2","추입","island_post_patch_v1",20,
                                    ("run-1",),{"run-1":"failed"},None,None)
            with self.assertRaises(ValueError):
                save_checkpoint(p,corrupt)

    def test_symlink_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"batch.json"
            other=Path(tmp)/"outside.json"
            other.write_text("outside")
            try:p.symlink_to(other)
            except (OSError,NotImplementedError):return
            with self.assertRaises(ValueError):
                load_checkpoint(p,goal(),20)
            with self.assertRaises(ValueError):
                save_checkpoint(p,record())
            self.assertEqual(other.read_text(),"outside")

    def test_completion_cap_and_pending_action_integrity(self):
        with self.assertRaises(ValueError):
            record(ids=("run-1","run-1"))
        with self.assertRaises(ValueError):
            record(total=1,ids=("run-1","run-2"))
        with self.assertRaises(ValueError):
            record(pending="buy_premium")
        with self.assertRaises(ValueError):
            record(active="run-1")


if __name__=="__main__":
    unittest.main()
