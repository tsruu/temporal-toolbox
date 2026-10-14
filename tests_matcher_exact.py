"""Differential arithmetic, matching, cache invalidation and first-use tests."""
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch

from app.tools import temporal as new
from scripts.verify_matcher_exact import baseline_module, outcome, ROOT


class ExactMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = baseline_module()

    def assert_bits_equal(self, actual, expected):
        self.assertEqual(struct.pack("!d", actual), struct.pack("!d", expected))

    def test_six_thousand_random_word_sets_and_scores_are_bit_identical(self):
        rng = random.Random(20261014)
        vocabulary = [
            "", "1", "2", "14th", "15th", "²", "１２", "one", "first", "fourteenth",
            "iv", "viii", "vii", "III", "NASA", "NASAs", "US", "us", "UKes",
            "series", "serie", "status", "bus", "class", "classes", "coach", "coaches",
            "team", "teams", "tean", "coac", "states", "estate", "Williams", "Andreas",
            "école", "ecole", "e\u0301cole", "écoles", "ÉCOLES", "œuvre", "straße",
            "αβγδε", "中文文字测试", "a_b", "don't", "abcde", "abdce", "abxde", "abcdf",
        ]
        alphabet = "abcdefgxyzéα"
        for _ in range(300):
            word = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 12)))
            vocabulary.extend((word, word + "s", word.upper(), word[:-1]))
        counts = 0
        for _ in range(6000):
            words = set(rng.sample(vocabulary, rng.randrange(0, 10)))
            key_word = rng.choice(vocabulary)
            for plural in (False, True):
                expected = self.old.word_present(key_word, words, plural)
                self.assertEqual(new.word_present(key_word, words, plural), expected)
                # word_present accepts arbitrary sets, including an empty word;
                # test its prepared predicate directly against exactly that set.
                singulars, lengths = new._query_word_forms(frozenset(words))
                self.assertEqual(new._prepared_word_present(key_word, words, singulars, lengths, plural), expected)
                counts += 2
            query = " ".join(words)
            key = " ".join(rng.sample(vocabulary, rng.randrange(0, 9)))
            plural_words = frozenset(rng.sample(vocabulary, rng.randrange(0, 9))) | frozenset(key.split()[::2])
            self.assert_bits_equal(new.containment_score(query, key, plural_words),
                                   self.old.containment_score(query, key, plural_words))
            self.assert_bits_equal(new.entity_similarity(query, key, plural_words),
                                   self.old.entity_similarity(query, key, plural_words))
            forms = new._AlternativeForms(key, new._word_set(key), plural_words, new._trigram_set(key))
            rank = new._QueryScorer(query).surface_rank(forms)
            self.assertEqual(rank[0], bool(query) and query == key)
            self.assert_bits_equal(rank[1], self.old.entity_similarity(query, key, plural_words))
            expected_total = len(set(query.split())) + len(set(key.split()))
            expected_completeness = (2 * len(set(query.split()) & set(key.split())) / expected_total
                                     if expected_total else 0.0)
            self.assert_bits_equal(rank[2], expected_completeness)
            counts += 4
        print(f"6000 random combinations; {counts} differential assertions; differences 0", flush=True)

    def test_alternative_and_candidate_rank_operation_order(self):
        rng = random.Random(71234)
        surfaces = ["", "The coaches", "NASA", "NASAs", "I", "Team | teams", "2011",
                    "King Henry VIII", "École française", "other event", "Phir Dhoom",
                    "Member of the 5th Parliament", "coach of men’s-team", "a | an | the"]
        for _ in range(3000):
            row = {"entity": rng.choice(surfaces), "event": rng.choice(surfaces)}
            q_entity = new.normalize_entity(rng.choice(surfaces))
            q_event = new.normalize_entity(rng.choice(surfaces))
            old_rank, old_qualifies = self.old._chronological_candidate(q_entity, q_event, row)
            entity = new._QueryScorer(q_entity).cell_rank(tuple(new._alternative_forms(s) for s in row["entity"].split("|")))
            event = new._QueryScorer(q_event).cell_rank(tuple(new._alternative_forms(s) for s in row["event"].split("|")))
            rank = (entity[0] and event[0], 0.6 * entity[1] + 0.4 * event[1], 0.6 * entity[2] + 0.4 * event[2])
            self.assertEqual(rank[0], old_rank[0])
            self.assert_bits_equal(rank[1], old_rank[1])
            self.assert_bits_equal(rank[2], old_rank[2])
            self.assertEqual(entity[1] >= new.COMPONENT_BAR and event[1] >= new.COMPONENT_BAR, old_qualifies)
        print("3000 random candidate ranks and thresholds; differences 0", flush=True)

    def test_custom_csv_paths_invalidation_order_and_concurrent_first_use(self):
        with tempfile.TemporaryDirectory(prefix="matcher-fixture-") as directory:
            path = Path(directory) / "references.csv"

            def write(answer, extra=""):
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=("entity", "event", "answer"))
                    writer.writeheader()
                    writer.writerows([
                        {"entity": "coaches | trainer", "event": "tournament", "answer": answer},
                        {"entity": "coaches", "event": "tournament", "answer": "later" + extra},
                        {"entity": " | other", "event": " | unknown", "answer": "empty"},
                    ])

            write("first")
            args = ("coach", "tournament", path)
            for name in ("before_chronological_reference", "after_chronological_reference"):
                with patch.object(new.csv, "DictReader", wraps=csv.DictReader) as reader:
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        values = list(pool.map(lambda _: getattr(new, name)(*args), range(16)))
                    self.assertEqual(values, ["first"] * 16)
                    self.assertLessEqual(reader.call_count, 1)
                self.assertEqual(outcome(new, name, args), outcome(self.old, name, args))
                for pair in [("", ""), ("unrelated", "no event"), ("trainer", "tournament")]:
                    self.assertEqual(outcome(new, name, (*pair, path)), outcome(self.old, name, (*pair, path)))
            stat = path.stat()
            write("other")  # Same-size change must invalidate by nanosecond mtime.
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            self.assertEqual(new.before_chronological_reference(*args), "other")
            stat = path.stat()
            write("third", " longer")  # Same mtime must invalidate by size.
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertEqual(new.after_chronological_reference(*args), "third")
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                new.before_chronological_reference(*args)
            new._CHRONOLOGICAL_TABLES.pop(str(path), None)

    def test_unstatable_open_fixture_is_never_cached(self):
        for answer in ("first", "other"):
            content = f"entity,event,answer\nteam,event,{answer}\n"
            with patch("builtins.open", return_value=io.StringIO(content)):
                self.assertEqual(new.before_chronological_reference("team", "event", "nonexistent-fixture.csv"), answer)

    def test_nonmatching_rows_do_not_access_missing_answer(self):
        with tempfile.TemporaryDirectory(prefix="matcher-missing-answer-") as directory:
            path = Path(directory) / "references.csv"
            path.write_text("entity,event\nteam,event\n", encoding="utf-8")
            for name in ("before_chronological_reference", "after_chronological_reference"):
                self.assertEqual(outcome(new, name, ("unrelated", "unknown", path)),
                                 outcome(self.old, name, ("unrelated", "unknown", path)))
                with self.assertRaisesRegex(KeyError, "answer"):
                    getattr(new, name)("team", "event", path)
            new._CHRONOLOGICAL_TABLES.pop(str(path), None)


if __name__ == "__main__":
    unittest.main()
