"""Adapt audited early KPL CSVs for the records builder, without changing training archives."""
import csv
from collections import defaultdict
from pathlib import Path


def read_rows(root: Path, name: str):
    with (root / (name + '.csv')).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def optional_number(value):
    return float(value) if value not in ('', None) else None


def load_history(root: Path):
    # Fail loudly when the supplement is missing; never silently shrink the published scope.
    matches = read_rows(root, 'matches')
    games = read_rows(root, 'games')
    players = read_rows(root, 'player_stats')
    by_game = defaultdict(list)
    by_match = defaultdict(list)
    for p in players:
        by_game[p['game_id']].append(p)
    for g in games:
        by_match[g['match_id']].append(g)
    objects, details, leagues, provenance = [], {}, {}, {}
    excluded = []
    for m in matches:
        if m['quality_flag'] != 'ok':
            excluded.append({'id': m['match_id'], 'reason': m['quality_flag']})
            continue
        lid = 'history_' + m['year'] + ('_spring' if '春' in m['season'] else '_autumn')
        league = leagues.setdefault(lid, {'id': lid, 'name': m['season'], 'year': int(m['year']), 'matches': 0, 'battles': 0})
        bs = []
        for g in sorted(by_match[m['match_id']], key=lambda x: int(x['game_no'])):
            ps = by_game[g['game_id']]
            if g['quality_flag'] != 'ok' or len(ps) != 10:
                raise ValueError('Invalid game in accepted match: ' + g['game_id'])
            totals = {side: {key: sum(float(p[key]) for p in ps if p['side'] == str(side))
                            if all(p[key] != '' for p in ps if p['side'] == str(side)) else None
                            for key in ('damage_dealt', 'damage_taken')}
                      for side in (1, 2)}
            plist, slim = [], []
            for p in ps:
                side = int(p['side'])
                dmg, tank = optional_number(p['damage_dealt']), optional_number(p['damage_taken'])
                dmg_rate = dmg / totals[side]['damage_dealt'] if totals[side]['damage_dealt'] else None
                tank_rate = tank / totals[side]['damage_taken'] if totals[side]['damage_taken'] else None
                k, d, a = (int(p[x]) for x in ('kills', 'deaths', 'assists'))
                kills = int(g['team' + str(side) + '_kills'])
                part = (k + a) / kills * 100 if kills else None
                gold = optional_number(p['gold'])
                plist.append({'camp': side, 'player_name': p['player_name'], 'hero_name': p['hero_name'],
                              'team_name': p['team'], 'kill_num': k, 'death_num': d, 'assist_num': a,
                              'gold': gold, 'hurt_total': dmg, 'hurt_total_rate': dmg_rate,
                              'be_hurt_total_rate': tank_rate, 'participation_rate': part})
                slim.append({'c': side, 'n': p['player_name'], 'h': p['hero_name'], 'k': k, 'd': d, 'a': a,
                             'g': gold, 'dmg': round(dmg_rate * 100, 1) if dmg_rate is not None else None,
                             'bh': round(tank_rate * 100, 1) if tank_rate is not None else None, 'mvp': None})
            duration = float(g['duration_sec'])
            bs.append({'battle_id': g['game_id'], 'battle_seq': int(g['game_no']),
                       'camp1': {'team_name': g['team1']}, 'camp2': {'team_name': g['team2']},
                       'game_duration': duration * 1000, 'win_camp': int(g['winner_side']),
                       'battle_player_list': plist, 'history_team_gold': [optional_number(g['team1_gold']), optional_number(g['team2_gold'])]})
            details[g['game_id']] = {'t1': g['team1'], 't2': g['team2'], 'seq': int(g['game_no']),
                                     'win': int(g['winner_side']), 'dur': round(duration / 60, 2),
                                     'players': slim, 'k1': int(g['team1_kills']), 'k2': int(g['team2_kills']),
                                     'g1': optional_number(g['team1_gold']), 'g2': optional_number(g['team2_gold']),
                                     'source': g['source'], 'url': g['url'],
                                     'precision': '分钟' if g['source'] == 'scoregg' else '秒'}
        league['matches'] += 1
        league['battles'] += len(bs)
        provenance[m['match_id']] = {'early': True, 'url': m['url'], 'source': m['source']}
        objects.append({'match': {'match_id': m['match_id'], 'league_id': lid,
                                  'start_time': m['start_time'], 'match_time': m['date'],
                                  'bo': int(m['bo']), 'camp1': {'team_name': m['team1'], 'score': int(m['score1'])},
                                  'camp2': {'team_name': m['team2'], 'score': int(m['score2'])},
                                  'win_camp': 1 if m['winner'] == m['team1'] else 2}, 'battles': bs})
    return objects, details, list(leagues.values()), provenance, excluded
