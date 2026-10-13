"""Entity alternatives with unchanged event scoring and date filtering."""
import csv
import random
import io
from unittest.mock import patch
import unittest

from app.tools import temporal


class EntityAlternativeTests(unittest.TestCase):
    def setUp(self):
        self.csv_text = ''
        self.open_mock = patch('builtins.open', side_effect=lambda *args, **kwargs: io.StringIO(self.csv_text))
        self.open_mock.start()
        self.addCleanup(self.open_mock.stop)

    def table(self, rows):
        with io.StringIO(newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            self.csv_text = stream.getvalue()
        return 'test_rows.csv'

    def test_any_alternative_scores_before_normalization(self):
        for entity in ('achieved freedom', 'attained freedom', 'Independence'):
            self.assertEqual(temporal.row_entity_similarity(
                temporal.normalize_entity(entity),
                'Independence | achieved freedom | attained freedom'), 1.0)
        self.assertEqual(temporal.row_entity_similarity('esa',
            'European Space Agency | ESA'), 1.0)
        self.assertEqual(temporal.row_entity_similarity('freedom',
            'unrelated | FREÉDOM'), 1.0)

    def test_single_cells_have_exactly_the_original_score(self):
        rng = random.Random(4)
        cells = ['Bouaïcha', "country's", 'Formula One 1970', 'the G-20 summit',
                 '', 'a', 'won the Best Picture Academy Award', 'John Adams']
        cells += [' '.join(rng.choices(cells, k=3)) for _ in range(100)]
        for query in cells:
            normalized = temporal.normalize_entity(query)
            for key in cells:
                self.assertEqual(temporal.row_entity_similarity(normalized, key),
                    temporal.entity_similarity(normalized, temporal.normalize_entity(key)))
                self.assertEqual(temporal.lexical_match_rank(normalized, key)[1],
                    temporal.entity_similarity(normalized, temporal.normalize_entity(key)))
                self.assertEqual(temporal.event_match_rank(normalized, key)[1],
                    temporal.entity_similarity(normalized, temporal.normalize_entity(key)))

    def test_chronological_alternatives_and_event_ties(self):
        path = self.table([
            dict(entity='Independence | achieved freedom', event='Kazakhstan', answer='first'),
            dict(entity='Independence | achieved freedom', event='Kyrgyzstan', answer='other'),
            dict(entity='Independence | achieved freedom', event='Kazakhstan', answer='last'),
        ])
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            for query in ('Independence', 'achieved freedom'):
                with self.subTest(tool=name, query=query):
                    self.assertEqual(getattr(temporal, name)(query, 'Kazakhstan', path), 'first')
                    self.assertEqual(getattr(temporal, name)(query, 'Kyrgyzstan', path), 'other')

    def test_absolute_and_entity_time_filtering_and_ties(self):
        path = self.table([
            dict(entity='European Space Agency | ESA', time='2000-01', answer='January'),
            dict(entity='European Space Agency | ESA', time='2000-02', answer='February'),
            dict(entity='European Space Agency | ESA', time='2000-02', answer='last'),
        ])
        for name in ('before_absolute_reference', 'after_absolute_reference', 'entity_time_event'):
            for query in ('European Space Agency', 'ESA'):
                with self.subTest(tool=name, query=query):
                    self.assertEqual(getattr(temporal, name)(query, '2000-02', path), 'February')
                    self.assertEqual(getattr(temporal, name)(query, '2000', path), 'January')
                    with self.assertRaises(LookupError):
                        getattr(temporal, name)(query, '2001', path)

    def test_event_alternatives_are_scored_individually(self):
        path = self.table([dict(event='one | two', answer='year')])
        for event in ('one', 'two'):
            self.assertEqual(temporal.event_time(event, path), 'year')
        with self.assertRaises(LookupError):
            temporal.event_time('one two', path)  # different numeric tokens in each alternative

    def test_chronological_event_alternatives_are_scored_individually(self):
        path = self.table([dict(entity='Owner', event='one | supercalifragilistic',
                                answer='year')])
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            with self.subTest(tool=name):
                self.assertEqual(getattr(temporal, name)('Owner', 'one', path), 'year')
                self.assertEqual(getattr(temporal, name)(
                    'Owner', 'one supercalifragilistic', path), 'year')

    def test_event_punctuation_score_and_separate_eligibility(self):
        cells = ('one | two', 'one | supercalifragilistic',
                 'Member of the 5th | Parliament', '', 'a', 'Phir Dhoom')
        queries = ('one', 'two', 'one two', 'one supercalifragilistic',
                   'Member of the 6th Parliament', '', 'a', 'Phir Dhoom')
        for cell in cells:
            for query in queries:
                normalized = temporal.normalize_entity(query)
                score = max(temporal.entity_similarity(normalized, temporal.normalize_entity(alt))
                            for alt in cell.split('|'))
                self.assertEqual(temporal.event_match_rank(normalized, cell)[1], score)
                probes = [('event_time', dict(event=cell, answer='year'), (query,), score)]
                probes += [(name, dict(entity='Owner | Proprietor', event=cell, answer='year'),
                            ('Owner', query), score)
                           for name in ('before_chronological_reference',
                                        'after_chronological_reference')]
                for name, row, args, expected_score in probes:
                    with self.subTest(tool=name, cell=cell, query=query):
                        path = self.table([row])
                        if expected_score >= .75:
                            self.assertEqual(getattr(temporal, name)(*args, path), 'year')
                        else:
                            with self.assertRaises(LookupError):
                                getattr(temporal, name)(*args, path)

    def test_absolute_dates_distinguish_same_month_transitions(self):
        path = self.table([
            dict(entity='Germany', time='1974-05-07', answer='Willy Brandt'),
            dict(entity='Germany', time='1974-05-16', answer='Walter Scheel'),
        ])
        for name in ('before_absolute_reference', 'after_absolute_reference'):
            with self.subTest(tool=name):
                lookup = getattr(temporal, name)
                self.assertEqual(lookup('Germany', 'May 7, 1974', path), 'Willy Brandt')
                self.assertEqual(lookup('Germany', '1974-05-16', path), 'Walter Scheel')
                self.assertEqual(lookup('Germany', '16. Mai 1974', path), 'Walter Scheel')
                self.assertEqual(lookup('Germany', '1974-05', path), 'Willy Brandt')
                with self.assertRaises(LookupError):
                    lookup('Germany', '1974-05-08', path)
        self.assertEqual(temporal.normalize_time('1974-05-16'), (1974, 5))
        with self.assertRaises(ValueError):
            temporal.normalize_time_key('May 32, 1974')

    def test_threshold_and_no_match_are_unchanged(self):
        path = self.table([dict(entity='Independence | achieved freedom',
                              event='Kazakhstan', answer='first')])
        for name in ('before_chronological_reference', 'after_chronological_reference'):
            with self.assertRaises(LookupError):
                getattr(temporal, name)('no lexical overlap', 'Kazakhstan', path)


if __name__ == '__main__':
    unittest.main()
