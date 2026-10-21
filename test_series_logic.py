# -*- coding: utf-8 -*-
"""kpl_series 的回归测试：覆盖换边、让二追三、官方兜底、重复局号、串场小局。

运行：python test_series_logic.py
"""
from __future__ import annotations

import unittest

from kpl_series import battle_winner_team, summarize_match


def battle(seq: int, win_camp: int, c1: str, c2: str, ts: int, bid: str | None = None) -> dict:
    """构造一局最小数据：每方一名选手，便于同时验证选手归属。"""
    return {
        "battle_id": bid or f"{seq}000_{seq}_{ts}",
        "battle_seq": seq,
        "win_camp": win_camp,
        "camp1": {"team_name": c1},
        "camp2": {"team_name": c2},
        "battle_player_list": [
            {"player_name": f"{c1}-p", "camp": 1, "team_name": c1,
             "kill_num": 1, "death_num": 1, "assist_num": 1, "hurt_total_rate": 0.2},
            {"player_name": f"{c2}-p", "camp": 2, "team_name": c2,
             "kill_num": 1, "death_num": 1, "assist_num": 1, "hurt_total_rate": 0.2},
        ],
    }


def match(c1: str, c2: str, bo: int, winner: str, score: tuple[int, int]) -> dict:
    return {
        "match_id": "m1", "bo": bo, "win_camp": 1 if winner == c1 else 2,
        "start_time": "2026-01-01 19:00:00", "league_id": "L1",
        "camp1": {"team_name": c1, "score": score[0]},
        "camp2": {"team_name": c2, "score": score[1]},
    }


class SeriesLogicTest(unittest.TestCase):
    def test_side_switches_are_resolved_to_team_identity(self):
        """A 每局换边，但 3:1 的系列赛结果必须按战队身份累计。"""
        # A 赢第 1/2/4 局，B 赢第 3 局；每局双方都换边。
        bs = [
            battle(1, 1, "A", "B", 100),
            battle(2, 2, "B", "A", 200),
            battle(3, 2, "A", "B", 300),
            battle(4, 2, "B", "A", 400),
        ]
        res = summarize_match({"match": match("A", "B", 5, "A", (3, 1)), "battles": bs})
        self.assertIsNotNone(res)
        self.assertEqual((res.team1, res.team2), ("A", "B"))
        self.assertEqual(res.score, (3, 1))
        self.assertEqual(res.winner, "A")
        self.assertTrue(res.battle_complete)
        self.assertEqual(res.source, "battles")
        self.assertGreater(res.side_switches, 0)
        # 本局胜方必须能用同一局 camp 队名还原
        self.assertEqual([battle_winner_team(b) for b in res.battles], ["A", "A", "B", "A"])

    def test_reverse_sweep_after_losing_first_two(self):
        """B 先赢两局，A 连扳三局：让二追三应记在 A 头上。"""
        bs = [
            battle(1, 2, "A", "B", 100),   # B 赢
            battle(2, 1, "B", "A", 200),   # B 赢
            battle(3, 1, "A", "B", 300),   # A 赢
            battle(4, 2, "B", "A", 400),   # A 赢
            battle(5, 1, "A", "B", 500),   # A 赢
        ]
        res = summarize_match({"match": match("A", "B", 5, "A", (3, 2)), "battles": bs})
        self.assertEqual(res.score, (3, 2))
        self.assertEqual(res.winner, "A")
        self.assertTrue(res.decisive)
        self.assertTrue(res.reverse_sweep)
        self.assertEqual(res.battle_winners, ("B", "B", "A", "A", "A"))

    def test_official_fallback_when_battles_incomplete(self):
        """逐局只有 1:1，但官方大场 3:1：胜方采用官方，并标记 official。"""
        bs = [
            battle(1, 1, "A", "B", 100),
            battle(2, 1, "B", "A", 200),
        ]
        res = summarize_match({"match": match("A", "B", 5, "A", (3, 1)), "battles": bs})
        self.assertEqual(res.source, "official")
        self.assertFalse(res.battle_complete)
        self.assertEqual(res.winner, "A")
        self.assertEqual(res.score, (3, 1))

    def test_duplicate_seq_with_distinct_battle_ids_are_not_deduped(self):
        """局号损坏导致两局同为 seq=1 时，按 battle_id 保留两局，比分必须是 3:1。"""
        bs = [
            battle(1, 1, "A", "B", 100, bid="x_1_100"),
            battle(1, 1, "B", "A", 200, bid="y_2_200"),
            battle(2, 1, "A", "B", 300, bid="x_2_300"),
            battle(3, 1, "A", "B", 400, bid="y_3_400"),
        ]
        res = summarize_match({"match": match("A", "B", 5, "A", (3, 1)), "battles": bs})
        self.assertEqual(res.score, (3, 1))
        self.assertEqual(len(res.battles), 4)

    def test_cross_team_battle_is_filtered(self):
        """夹带的其他战队小局必须被剔除，不能污染比分和选手数据。"""
        bs = [
            battle(1, 1, "A", "B", 100),
            battle(2, 1, "C", "D", 200),   # 串场
            battle(3, 1, "A", "B", 300),
            battle(4, 1, "A", "B", 400),
        ]
        res = summarize_match({"match": match("A", "B", 5, "A", (3, 0)), "battles": bs})
        self.assertEqual(res.score, (3, 0))
        self.assertTrue(all({b["camp1"]["team_name"], b["camp2"]["team_name"]} == {"A", "B"}
                            for b in res.battles))


if __name__ == "__main__":
    unittest.main(verbosity=2)
