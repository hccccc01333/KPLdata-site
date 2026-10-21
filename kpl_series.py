# -*- coding: utf-8 -*-
"""KPL 系列赛结算口径（唯一权威实现）。

原始接口里的 ``camp1/camp2`` 是**每一小局**的阵营（蓝/红方），不是战队身份：
同一支战队在不同小局可以换边。因此任何与 ``win_camp`` 有关的计算都必须先落回
**本局**的 camp 队名，再按战队身份累计；绝不能拿大场级 ``win_camp`` 去套所有小局。

本模块把这条规则集中实现，供 build_deep_data.py、质量检查脚本和后续分析复用。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def team_name_of(battle: dict, camp: int) -> str:
    """取某局（或大场）某个阵营的战队名；占位符「待定」视为无效。"""
    data = battle.get(f"camp{camp}")
    if not isinstance(data, dict):
        return ""
    name = str(data.get("team_name") or "").strip()
    return "" if name in ("", "待定") else name


def battle_winner_team(battle: dict) -> str:
    """本局胜方战队名。

    ``win_camp`` 只能和**同一局**的 camp 队名配对使用，这是本模块存在的唯一理由。
    """
    camp = _int(battle.get("win_camp"))
    if camp not in (1, 2):
        return ""
    return team_name_of(battle, camp)


def battle_team_set(battle: dict) -> set[str]:
    return {team_name_of(battle, 1), team_name_of(battle, 2)} - {""}


@dataclass(frozen=True)
class SeriesResult:
    match_id: str
    league_id: str
    date: str
    stage: str
    bo: int
    need: int
    team1: str
    team2: str
    team1_wins: int
    team2_wins: int
    winner: str
    loser: str
    score: tuple[int, int]
    battle_complete: bool
    resolved: bool
    source: str                     # battles / official
    official_winner: str
    official_score: tuple[int, int] | None
    official_conflict: bool
    side_switches: int
    first_game: str
    decisive: bool
    reverse_sweep: bool
    battle_winners: tuple[str, ...]
    battles: tuple[dict, ...]
    errors: tuple[str, ...]

    @property
    def games(self) -> int:
        return len(self.battles)

    @property
    def score_text(self) -> str:
        """胜方在前，用于页面展示。"""
        if not self.resolved:
            return ""
        w, l = self.score if self.winner == self.team1 else (self.score[1], self.score[0])
        return f"{w}:{l}"

    @property
    def decisive_battle(self) -> dict | None:
        if not self.decisive or not self.battles:
            return None
        return self.battles[-1]


def _clean_battles(raw: list[Any], official_teams: set[str]) -> list[dict]:
    """按官方大场队名过滤 + 按 battle_id 去重，剔除串场/占位小局。

    注意：历史数据里存在同一场两个来源的 battle_id 共用一个 battle_seq 的情况
    （2021-11-18 TTG/DRG、2021-04-21 EDG/RNG）。它们不是重复局，而是局号字段损坏；
    因此这里只按 battle_id 去重，排序时用 battle_id 尾部的 Unix 时间戳作为局号并列时的
    真实先后依据。若按 seq 去重，会丢掉一整局并把 3:1 算成 3:0。
    """
    rows: list[tuple[int, int, int, int, dict]] = []
    for i, b in enumerate(raw):
        if not isinstance(b, dict) or _int(b.get("win_camp")) not in (1, 2):
            continue
        teams = battle_team_set(b)
        if len(teams) != 2:
            continue
        if official_teams and teams != official_teams:
            continue
        seq = _int(b.get("battle_seq"))
        ts = 0
        tail = str(b.get("battle_id") or "").rsplit("_", 1)[-1]
        if tail.isdigit():
            ts = int(tail)
        players = len(b.get("battle_player_list") or [])
        rows.append((seq, ts, -players, i, b))

    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    out: list[dict] = []
    seen_bid: set[str] = set()
    for _seq, _ts, _neg_players, _i, b in rows:
        bid = str(b.get("battle_id") or "")
        if bid:
            if bid in seen_bid:
                continue
            seen_bid.add(bid)
        out.append(b)
    return out


def summarize_match(obj: dict, fallback_id: str = "") -> SeriesResult | None:
    """把一个 match JSON 结算为一个可验证的系列赛结果。

    数据完整时以逐局结果为准；逐局缺失但官方大场胜负存在时回退到官方口径，
    并显式记录 ``source='official'``，绝不把阵营计数伪装成战队胜负。
    """
    match = obj.get("match") if isinstance(obj, dict) else None
    if not isinstance(match, dict):
        return None

    raw = obj.get("battles") or []
    if not isinstance(raw, list):
        return None

    official_teams: set[str] = set()
    for camp in (1, 2):
        name = team_name_of(match, camp)
        if name:
            official_teams.add(name)
    if len(official_teams) != 2:
        official_teams = set()

    battles = _clean_battles(raw, official_teams)
    if not battles:
        return None

    # 展示顺序沿用首局 camp1/camp2；若首局无效，则用官方大场顺序。
    first = battles[0]
    team1 = team_name_of(first, 1)
    team2 = team_name_of(first, 2)
    if not team1 or not team2:
        team1 = team_name_of(match, 1)
        team2 = team_name_of(match, 2)
    if not team1 or not team2 or team1 == team2:
        return None

    allowed = {team1, team2}
    battles = [b for b in battles if battle_team_set(b) == allowed]
    if not battles:
        return None

    winners = tuple(battle_winner_team(b) for b in battles)
    wins = Counter(w for w in winners if w in allowed)
    for team in allowed:
        wins.setdefault(team, 0)

    bo = _int(match.get("bo"))
    if bo <= 0:
        bo = max(1, 2 * len(battles) - 1)
    need = bo // 2 + 1
    battle_complete = max(wins.values()) == need
    battle_score = (wins[team1], wins[team2])

    mw = _int(match.get("win_camp"))
    official_winner = team_name_of(match, mw) if mw in (1, 2) else ""
    if official_winner not in allowed:
        official_winner = ""

    official_score = None
    if official_winner:
        s1 = _int((match.get("camp1") or {}).get("score"))
        s2 = _int((match.get("camp2") or {}).get("score"))
        if s1 + s2 > 0:
            by_team = {team_name_of(match, 1): s1, team_name_of(match, 2): s2}
            official_score = (by_team.get(team1, 0), by_team.get(team2, 0))

    errors: list[str] = []
    if battle_complete:
        winner = team1 if wins[team1] == need else team2
        loser = team2 if winner == team1 else team1
        score = battle_score
        source = "battles"
        official_conflict = bool(official_winner and official_winner != winner)
        if official_conflict:
            errors.append("official_winner_conflict")
        if official_score is not None and official_score != battle_score:
            errors.append("official_score_conflict")
    elif official_winner:
        winner = official_winner
        loser = team2 if winner == team1 else team1
        score = official_score if official_score is not None else battle_score
        source = "official"
        official_conflict = False
    else:
        winner = loser = ""
        score = battle_score
        source = "unresolved"
        official_conflict = False
        errors.append("no_winner")

    resolved = bool(winner)
    side_switches = sum(1 for b in battles if team_name_of(b, 1) != team1)
    first_game = winners[0] if winners and winners[0] in allowed else ""

    went_distance = (
        battle_complete
        and len(battles) >= 3
        and (
            (score[0] == need and score[1] == need - 1)
            or (score[1] == need and score[0] == need - 1)
        )
    )
    reverse_sweep = (
        battle_complete
        and bo >= 5
        and len(winners) >= 3
        and winners[0] == winners[1]
        and bool(winner)
        and winner != winners[0]
    )

    return SeriesResult(
        match_id=str(match.get("match_id") or fallback_id),
        league_id=str(match.get("league_id") or ""),
        date=str(match.get("start_time") or ""),
        stage=str(match.get("match_stage_name") or ""),
        bo=bo,
        need=need,
        team1=team1,
        team2=team2,
        team1_wins=score[0],
        team2_wins=score[1],
        winner=winner,
        loser=loser,
        score=score,
        battle_complete=battle_complete,
        resolved=resolved,
        source=source,
        official_winner=official_winner,
        official_score=official_score,
        official_conflict=official_conflict,
        side_switches=side_switches,
        first_game=first_game,
        decisive=went_distance,
        reverse_sweep=reverse_sweep,
        battle_winners=winners,
        battles=tuple(battles),
        errors=tuple(errors),
    )
