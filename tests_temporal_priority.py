"""Regression coverage for full matches, completeness and stable row order."""
import csv
import io
import unittest
from unittest.mock import patch

from app.tools import temporal


class MatchPriorityTests(unittest.TestCase):
    def lookup(self, name, rows, *args):
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        with patch('builtins.open', return_value=io.StringIO(stream.getvalue())):
            return getattr(temporal, name)(*args, csv_path='fixture.csv')

    def test_chronological_full_match_and_alternatives(self):
        rows = [
            dict(entity='Band', event='Dhoom', answer='short'),
            dict(entity='Euphoria | Band', event='Other | Phir Dhoom', answer='full'),
            dict(entity='Band', event='Phir Dhoom', answer='later'),
        ]
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            with self.subTest(tool=name):
                self.assertEqual(self.lookup(name, rows, 'BÁND!', 'Phir Dhoom'), 'full')
                self.assertEqual(self.lookup(name, rows, 'Band', 'Dhoom'), 'short')

    def test_partial_ties_prefer_complete_numeric_anchor(self):
        rows = [
            dict(entity='Pelpuo', event='Member of Parliament', answer='short'),
            dict(entity='Pelpuo', event='Member of the 5th Parliament', answer='fifth'),
            dict(entity='Pelpuo', event='Member of the 6th Parliament', answer='sixth'),
        ]
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            for number, expected in [('5th', 'fifth'), ('6th', 'sixth')]:
                with self.subTest(tool=name, number=number):
                    self.assertEqual(self.lookup(name, rows, 'Pelpuo',
                        f'Member of the {number} Parliament of Ghana'), expected)

    def test_full_entity_and_event_are_both_required_for_exact_priority(self):
        rows = [
            dict(entity='Euphoria', event='Phir Dhoom Live Festival Recording', answer='complete'),
            dict(entity='Euphoria band', event='Dhoom', answer='short event'),
        ]
        self.assertEqual(self.lookup('after_chronological_reference', rows,
                         'Euphoria band', 'Phir Dhoom Live Festival Recording'), 'complete')

    def test_time_filtered_tools_prefer_full_entity_then_row_order(self):
        rows = [
            dict(entity='Systems', time='2000-01', answer='short'),
            dict(entity='Other | Open Systems', time='2000-01', answer='full'),
            dict(entity='Open Systems', time='2000-01', answer='later'),
            dict(entity='Open Systems', time='2000-02', answer='February'),
        ]
        for name in ('before_absolute_reference', 'after_absolute_reference', 'entity_time_event'):
            with self.subTest(tool=name):
                self.assertEqual(self.lookup(name, rows, 'Open Systems', '2000-01'), 'full')
                self.assertEqual(self.lookup(name, rows, 'Open Systems', '2000-02'), 'February')
                with self.assertRaises(LookupError):
                    self.lookup(name, rows, 'Open Systems', '2001')

    def test_event_time_prefers_full_event_and_stable_ties(self):
        rows = [dict(event='Dhoom', answer='short'),
                dict(event='Phir Dhoom', answer='full'),
                dict(event='Phir Dhoom', answer='later')]
        self.assertEqual(self.lookup('event_time', rows, 'Phir Dhoom'), 'full')
        self.assertEqual(self.lookup('event_time', rows, 'new Phir Dhoom'), 'full')

    def test_score_precedes_completeness_and_threshold_is_preserved(self):
        rows = [dict(event='Phir Dhoom', answer='contained'),
                dict(event='new Phir Dhooom', answer='typo')]
        self.assertEqual(self.lookup('event_time', rows, 'new Phir Dhoom'), 'contained')
        with self.assertRaises(LookupError):
            self.lookup('event_time', rows, 'unrelated')

    def test_real_reported_failures(self):
        for entity, event, expected in [
            ('Euphoria', 'Phir Dhoom', 'Gully'),
            ('Moxie Marlinspike', 'Open Whisper Systems', 'Signal Messenger'),
            ('Abdul-Rashid Pelpuo', 'Member of the 5th Parliament of the 4th Republic of Ghana',
             'Member of the 6th Parliament of the 4th Republic of Ghana'),
            ('Abdul-Rashid Pelpuo', 'Member of the 6th Parliament of the 4th Republic of Ghana',
             'Member of the 7th Parliament of the 4th Republic of Ghana'),
        ]:
            with self.subTest(entity=entity, event=event):
                self.assertEqual(temporal.after_chronological_reference(entity, event), expected)

    def test_prc_held_exact_duplicates_keep_first_answer(self):
        self.assertEqual(temporal.after_absolute_reference(
            "People's Republic of China", '2003-03'), 'Hu Jintao')


if __name__ == '__main__':
    unittest.main()
