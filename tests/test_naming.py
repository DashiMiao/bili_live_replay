import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bili_live_replay as b


def ts(day, hour, minute=0, month=11):
    return int(datetime(2026, month, day, hour, minute, tzinfo=b.CST).timestamp())


def replay(rid, start, end):
    return {"replay_id": rid, "start_time": start, "end_time": end}


class ReplayNamingTests(unittest.TestCase):
    def test_single_replay_per_day_keeps_plain_name(self):
        replays = [replay(1, ts(10, 20), ts(10, 21)),
                   replay(2, ts(11, 20), ts(11, 21))]
        plan = b.build_replay_plan(replays)
        self.assertEqual([p for _r, _d, p in plan], ["2026_11_10", "2026_11_11"])

    def test_multiple_replays_in_one_day_get_time_ordered_suffix(self):
        replays = [
            replay(3, ts(23, 21), ts(23, 22)),   # 最晚
            replay(1, ts(23, 9), ts(23, 10)),    # 最早
            replay(2, ts(23, 15), ts(23, 16)),
        ]
        plan = b.build_replay_plan(replays)
        prefixes = {r["replay_id"]: p for r, _d, p in plan}
        self.assertEqual(prefixes, {
            1: "2026_11_23_1",
            2: "2026_11_23_2",
            3: "2026_11_23_3",
        })
        # 下载顺序保持不变（调用方决定），只改命名
        self.assertEqual([r["replay_id"] for r, _d, _p in plan], [3, 1, 2])

    def test_subset_download_uses_full_day_indices(self):
        all_replays = [
            replay(1, ts(23, 9), ts(23, 10)),
            replay(2, ts(23, 15), ts(23, 16)),
            replay(3, ts(23, 21), ts(23, 22)),
        ]
        plan = b.build_replay_plan([all_replays[2]], all_replays)
        self.assertEqual(plan[0][2], "2026_11_23_3")

    def test_duplicate_replay_id_is_ignored(self):
        r = replay(1, ts(23, 9), ts(23, 10))
        plan = b.build_replay_plan([r, dict(r)], [r, dict(r)])
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0][2], "2026_11_23")

    def test_different_days_are_numbered_independently(self):
        replays = [
            replay(1, ts(22, 9), ts(22, 10)),
            replay(2, ts(23, 9), ts(23, 10)),
            replay(3, ts(22, 20), ts(22, 21)),
        ]
        prefixes = {r["replay_id"]: p for r, _d, p in b.build_replay_plan(replays)}
        self.assertEqual(prefixes, {
            1: "2026_11_22_1",
            2: "2026_11_23",
            3: "2026_11_22_2",
        })

    def test_filter_by_dates_returns_all_replays_in_time_order(self):
        replays = [
            replay(2, ts(23, 15), ts(23, 16)),
            replay(1, ts(23, 9), ts(23, 10)),
            replay(3, ts(24, 9), ts(24, 10)),
        ]
        matched = b.filter_by_dates(replays, ["2026-11-23"])
        self.assertEqual([r["replay_id"] for r in matched["2026-11-23"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
