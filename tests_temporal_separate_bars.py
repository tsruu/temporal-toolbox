"""Independent qualification and tightly scoped word spelling tolerance."""
import csv
import io
import unittest
from unittest.mock import patch

from app.tools import temporal as t


class SeparateBarsTests(unittest.TestCase):
    def lookup(self, name, row, *args):
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        with patch('builtins.open', return_value=io.StringIO(stream.getvalue())):
            return getattr(t, name)(*args, csv_path='fixture.csv')

    def test_each_chronological_argument_must_qualify(self):
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            row = dict(entity='CEO of IBM', event='Virginia M. (Ginni) Rometty', answer='gold')
            with self.subTest(tool=name), self.assertRaises(LookupError):
                self.lookup(name, row, 'CEO of Apple', row['event'])
            row = dict(entity='John Grisham', event='The Pelican Brief', answer='gold')
            with self.subTest(tool=name), self.assertRaises(LookupError):
                self.lookup(name, row, row['entity'], 'Pelican')

    def test_requested_typos_reach_gold(self):
        self.assertEqual(t.before_chronological_reference('John Grishm', 'The Pelican Brief'), 'The Firm')
        self.assertEqual(t.before_chronological_reference('John Grisham', 'The Pelican Brif'), 'The Firm')
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            row = dict(entity='Rajshee Production', event='The Pelican Brief', answer='gold')
            self.assertEqual(self.lookup(name, row, 'Rajshree Production', row['event']), 'gold')

    def test_all_lookup_families_share_spelling_score(self):
        for name in ('before_absolute_reference', 'after_absolute_reference', 'entity_time_event'):
            row = dict(entity='John Grisham', time='2000-01-02', answer='gold')
            self.assertEqual(self.lookup(name, row, 'John Grishm', '2000-01-02'), 'gold')
        self.assertEqual(self.lookup('event_time', dict(event='The Pelican Brief', answer='gold'),
                                     'The Pelican Brif'), 'gold')

    def test_alternatives_preserve_exact_priority(self):
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            row = dict(entity='president of America | president of the United States',
                       event='John Adams', answer='gold')
            for entity in row['entity'].split(' | '):
                self.assertEqual(self.lookup(name, row, entity, row['event']), 'gold')
        self.assertEqual(t.lexical_match_rank('president of america',
                         'president of the United States | president of America')[0], True)

    def test_missing_head_coach_role_does_not_qualify(self):
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            row = dict(entity='head coach of the team HNK Rijeka', event='Simon Rožman', answer='gold')
            with self.subTest(tool=name), self.assertRaises(LookupError):
                self.lookup(name, row, 'HNK Rijeka', row['event'])

    def test_exactly_one_edit_and_stored_word_length(self):
        for query in ('grishm', 'grishamm', 'grishxm', 'grihsam'):
            self.assertEqual(t.containment_score(query, 'grisham'), 1.0)
        for query in ('grism', 'grxshxm', 'grihasm', 'unrelated'):
            self.assertEqual(t.containment_score(query, 'grisham'), 0.0)
        self.assertEqual(t.containment_score('brif', 'brief'), 1.0)
        self.assertEqual(t.containment_score('brief', 'brif'), 0.0)
        self.assertFalse(t.one_edit_apart('grisham', 'grisham'))
        self.assertTrue(t.one_edit_apart('brief', 'brie'))
        self.assertTrue(t.one_edit_apart('brief', 'brieff'))

    def test_numbers_and_ordinals_receive_no_spelling_tolerance(self):
        for key, query in [('14th', '15th'), ('12345', '12346'), ('xviii', 'xvii'),
                           ('fourteen', 'fourtee'), ('fourteenth', 'fourteent')]:
            with self.subTest(key=key, query=query):
                self.assertEqual(t.containment_score(query, key), 0.0)
                self.assertEqual(t.containment_score(key, key), 1.0)

    @unittest.expectedFailure
    def test_plan_numeric_mismatch_requires_an_additional_rule(self):
        # The plan also preserves the formula. Exact numeric containment alone
        # cannot enforce its "never matches" requirement: the other words and
        # unchanged trigrams still score above 0.75. Keep this conflict visible.
        row = dict(entity='Pelpuo', event='Member of the 14th Parliament', answer='wrong')
        with self.assertRaises(LookupError):
            self.lookup('before_chronological_reference', row, 'Pelpuo',
                        'Member of the 15th Parliament')

    def test_trigrams_and_completeness_use_exact_characters_and_words(self):
        query, key = 'john grishm', 'john grisham'
        expected = .7 + .3 * t.char_ngram_similarity(query, key)
        self.assertEqual(t.entity_similarity(query, key), expected)
        self.assertEqual(t.event_match_rank(query, key)[2], .5)


if __name__ == '__main__':
    unittest.main()
