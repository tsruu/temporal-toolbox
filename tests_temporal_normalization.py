"""Round-2 surface rules and safeguards, exercised through all lookup tools."""
import unittest
from unittest.mock import patch

from app.tools import temporal as t
import tests_temporal_separate_bars as separate


class NormalizationTests(unittest.TestCase):
    def equal_forms(self, *forms):
        self.assertEqual(len({t.normalize_entity(v) for v in forms}), 1, forms)

    def test_articles_only_at_word_boundaries(self):
        self.equal_forms('The coach of a team in an arena', 'coach of team in arena')
        self.assertEqual(t.normalize_entity('Theodore at Rome in theater'),
                         'theodore at rome in theater')

    def test_regular_plural_s_and_es(self):
        for forms in [('team', 'teams'), ('coach', 'coaches'), ('class', 'classes'),
                      ('box', 'boxes'), ('hero', 'heroes'), ('series', 'series')]:
            self.equal_forms(*forms)
        self.assertEqual(t.normalize_entity('series'), 'series')
        self.assertNotEqual(t.normalize_entity('series'), t.normalize_entity('serie'))
        for word in ('US', 'NASA', 'UK', 'gas', 'bus', 'status'):
            self.assertEqual(t.normalize_entity(word), word.lower())

    def test_acronyms_and_numbers_do_not_pluralize(self):
        for word in ('US', 'NASA', 'UK', 'III', '2011', '14th', 'fourteenth'):
            for suffix in ('s', 'es'):
                self.assertNotEqual(t.normalize_entity(word), t.normalize_entity(word + suffix))
        self.assertEqual(t.normalize_entity('as is'), 'as is')

    def test_possessives(self):
        self.equal_forms("men’s team", 'men team')
        self.equal_forms("men's", 'mens', 'men’s', 'men', "mens'")

    def test_unicode_and_punctuation(self):
        self.equal_forms('ＡＣＭＥ—F.C. & Bouaïcha', 'ACME FC and Bouaicha',
                         'ACME-FC and Bouaicha', 'ACME–FC and Bouaicha')
        self.equal_forms('U.S.', 'US')
        self.equal_forms('“team”  ‘coach’', 'team coach')

    def test_no_synonyms_or_additional_stemming(self):
        for a, b in [('IBM', 'Apple'), ('coaching', 'coach'), ('city', 'cities'),
                     ('director', 'chair'), ('2011', '2012'), ('14th', '15th')]:
            self.assertNotEqual(t.normalize_entity(a), t.normalize_entity(b))

    def test_numeric_guard_includes_ordinals_and_roman_numerals(self):
        for a, b in [('Member of 14th Parliament', 'Member of 15th Parliament'),
                     ('Championship 2011', 'Championship 2012'),
                     ('King Henry VIII', 'King Henry VII')]:
            self.assertEqual(t.entity_similarity(t.normalize_entity(a), t.normalize_entity(b)), 0)

    def test_shared_rules_and_threshold_in_all_tools(self):
        fixture = separate.SeparateBarsTests()
        for name in ('before_absolute_reference', 'after_absolute_reference', 'entity_time_event',
                     'before_chronological_reference', 'after_chronological_reference', 'event_time'):
            chronological = 'chronological' in name
            row = dict(event='The coaches of men’s-team | Other event', answer='gold') if name == 'event_time' else (
                dict(entity='The coaches of men’s-team | Other owner', event='The teams', answer='gold')
                if chronological else dict(entity='The coaches of men’s-team | Other owner', time='2011', answer='gold'))
            args = ('coach of men team',) if name == 'event_time' else (
                ('coach of men team', 'team') if chronological else ('coach of men team', '2011'))
            with self.subTest(tool=name):
                self.assertEqual(fixture.lookup(name, row, *args), 'gold')
                # Missing a role must be controlled by the parameter in every family.
                field = 'event' if name == 'event_time' else 'entity'
                row[field] = 'head coach of team'
                args = ('coach of team', *args[1:])
                score = t.entity_similarity(t.normalize_entity(args[0]), t.normalize_entity(row[field]))
                with patch.object(t, 'COMPONENT_BAR', score + .01), self.assertRaises(LookupError):
                    fixture.lookup(name, row, *args)
                with patch.object(t, 'COMPONENT_BAR', score - .01):
                    self.assertEqual(fixture.lookup(name, row, *args), 'gold')


if __name__ == '__main__':
    unittest.main()
