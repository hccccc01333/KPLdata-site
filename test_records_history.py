"""Integration checks for the audited early-history records export.

Run after build_records.py: python -m unittest test_records_history -v
"""
import json
import unittest
from pathlib import Path

from kpl_series import summarize_match
from records_history import load_history

SITE = Path(__file__).resolve().parent


class RecordsHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.objects, cls.details, cls.leagues, cls.provenance, cls.excluded = load_history(
            SITE.parent / '02-KPL实时胜率预测系统/data/external/history_2016_2018')
        text = (SITE / 'assets/records.js').read_text(encoding='utf-8')
        cls.records = json.loads(text.split('=', 1)[1].strip().rstrip(';'))

    def test_quality_exclusions_and_export_counts(self):
        self.assertEqual(len(self.objects), 576)
        self.assertEqual(len(self.details), 1882)
        self.assertEqual(len(self.excluded), 8)
        exported = json.loads((SITE / 'assets/records-history-games.json').read_text(encoding='utf-8'))
        self.assertEqual(exported, self.details)
        for m in self.objects:
            result = summarize_match(m)
            self.assertIsNotNone(result)
            self.assertFalse(result.errors, result.match_id)

    def test_year_and_season_scopes_and_real_extrema(self):
        for year, matches, games in [('2016', 74, 206), ('2017', 243, 640), ('2018', 259, 1036)]:
            self.assertEqual(self.records['scopeCounts'][year], {'matches': matches, 'battles': games})
            durations = [b['game_duration'] / 60000 for m in self.objects
                         if m['match']['start_time'].startswith(year) for b in m['battles']
                         if 360000 <= b['game_duration'] <= 2700000]
            cell = self.records['scopes'][year]['game_dur']
            self.assertEqual(cell['max'][0]['v'], round(max(durations), 1))
            self.assertEqual(cell['min'][0]['v'], round(min(durations), 1))
        for league in self.leagues:
            self.assertIn(league['id'], self.records['scopes'])

    def test_missing_fields_never_become_zero_records(self):
        self.assertNotIn('p_dmg_abs', self.records['scopes']['2017'])
        for league in self.leagues:
            self.assertNotIn('season_player_mvp', self.records['scopes'][league['id']])
        for game in self.details.values():
            self.assertEqual(len(game['players']), 10)
            self.assertEqual(sum(p['c'] == 1 for p in game['players']), 5)
            if game['source'] == 'scoregg':
                self.assertTrue(all(p['g'] is None and p['dmg'] is None and p['bh'] is None
                                    and p['mvp'] is None for p in game['players']))

    def test_every_early_rank_has_working_provenance_and_details(self):
        excluded = {x['id'] for x in self.excluded}
        for scope in self.records['scopes'].values():
            for metric, cell in scope.items():
                for row in cell['max'] + cell['min']:
                    self.assertNotIn(row.get('mid'), excluded)
                    if row.get('early'):
                        self.assertTrue(row['url'].startswith('https://'))
                        if row.get('bid'):
                            self.assertIn(row['bid'], self.details)
                    if metric == 'p_perfect':
                        self.assertIsInstance(row['d'], str)


if __name__ == '__main__':
    unittest.main()
