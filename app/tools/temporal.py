# app/tools/temporal.py
import re
from datetime import datetime
import csv
import re
import unicodedata
from datetime import datetime
from typing import Tuple, Optional
import os
from functools import lru_cache

BASE_DIR = os.path.dirname(__file__)

BEFORE_ABSOLUTE_CSV = os.path.join(BASE_DIR, "before_absolute_reference.csv")
BEFORE_CHRONOLOGICAL_CSV = os.path.join(BASE_DIR, "before_chronological_reference.csv")

AFTER_ABSOLUTE_CSV = os.path.join(BASE_DIR, "after_absolute_reference.csv")
AFTER_CHRONOLOGICAL_CSV = os.path.join(BASE_DIR, "after_chronological_reference.csv")

ENTITY_TIME_EVENT_CSV = os.path.join(BASE_DIR, "entity_time_event.csv")
EVENT_TIME_CSV = os.path.join(BASE_DIR, "event_time.csv")
COMPONENT_BAR = 0.75

# =========================
# Entity normalization
# =========================

def _singular_surface(word: str) -> str:
    """Pairwise regular plural comparison, never global name normalization."""
    folded = _fold(word)
    if (not word.isalpha() or len(word) < 3 or is_number_word(folded)
            or (word.isupper() and len(word) <= 4)
            or folded == "series" or folded.endswith(("ss", "us", "is"))):
        return folded
    # An acronym with an explicitly appended lowercase suffix stays distinct.
    if any(word.endswith(suffix) and word[:-len(suffix)].isupper()
           and len(word[:-len(suffix)]) <= 4 for suffix in ("s", "es")):
        return folded
    if any(folded.endswith(suffix) and is_number_word(folded[:-len(suffix)])
           for suffix in ("s", "es")):
        return folded
    if folded.endswith(("ches", "shes", "xes", "zes", "sses", "oes")) and len(folded[:-2]) >= 3:
        return folded[:-2]
    if folded.endswith("s") and len(folded[:-1]) >= 3:
        return folded[:-1]
    return folded


@lru_cache(maxsize=50000)
def _surface_words(text: str) -> tuple:
    """Retain stored casing until plural eligibility has been established."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    text = re.sub(r"(?<=\w)'s\b|(?<=s)'(?=\W|$)", "", text, flags=re.I)
    text = re.sub(r"[-‐‑‒–—−]", " ", text)
    text = text.replace("&", " and ")
    # Existing dot removal already makes F.C./U.S. equal FC/US.
    text = re.sub(r"[^\w\s]|_", "", text)
    return tuple(word for word in text.split() if _fold(word) not in {"the", "a", "an"})


@lru_cache(maxsize=50000)
def normalize_entity(text: str) -> str:
    """Case-independent surface cleanup; preserve names and plural endings."""
    return " ".join(_fold(word) for word in _surface_words(text))


@lru_cache(maxsize=50000)
def stored_plural_words(text: str) -> frozenset:
    """Only words written entirely lowercase in this stored alternative qualify."""
    return frozenset(_fold(word) for word in _surface_words(text)
                     if word.isalpha() and word.islower() and len(word) >= 3
                     and not is_number_word(_fold(word)))


# =========================
# Time normalization
# =========================

# Month names in the dataset's languages (en, fr, de, ro, es, it, pt),
# lowercased and accent-folded.
MONTH_NAMES = {}
for _month, _names in enumerate([
    "january jan janvier janv januar janner ianuarie ian enero ene gennaio janeiro",
    "february feb fevrier fevr fev februar februarie febrero febbraio fevereiro",
    "march mar mars marz maerz martie marzo marco",
    "april apr avril avr aprilie abril aprile",
    "may mai mayo maggio maio",
    "june jun juin juni iunie iun junio giugno junho",
    "july jul juillet juil juli iulie iul julio luglio julho",
    "august aug aout agosto ago",
    "september sep sept septembre septembrie septiembre setiembre settembre setembro",
    "october oct octobre oktober okt octombrie octubre ottobre outubro",
    "november nov novembre noiembrie noi noviembre novembro",
    "december dec decembre dezember dez decembrie diciembre dic dicembre dezembro",
], start=1):
    for _name in _names.split():
        MONTH_NAMES[_name] = _month

# "Jun, 2015", "June 10, 2015", "10. März 2010" (after accent folding)
MONTH_YEAR_RE = re.compile(
    r"\b([a-z]+)\.?,?\s+(?:\d{1,2}(?:st|nd|rd|th)?\.?,?\s+)?(\d{4})\b"
)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def normalize_time(t: str) -> Tuple[int, Optional[int]]:
    """
    Returns (year, month or None)
    Accepts:
      YYYY
      YYYY-MM
      YYYY-MM-DD
      Jul 2005 / July 2005 / Jul, 2005 / July 10, 2005
      month names in fr, de, ro, es, it, pt (e.g. iunie 2020, février 1929)
    """
    t = t.strip()

    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.year, dt.month if "%m" in fmt else None
        except ValueError:
            pass

    m = re.search(r"([A-Za-z]+)\s+(\d{4})", t)
    if m:
        try:
            month = datetime.strptime(m.group(1)[:3], "%b").month
            return int(m.group(2)), month
        except ValueError:
            pass

    for m in MONTH_YEAR_RE.finditer(_fold(t)):
        month = MONTH_NAMES.get(m.group(1))
        if month is not None:
            return int(m.group(2)), month

    raise ValueError(
        f"could not parse time '{t}'. Use YYYY, YYYY-MM, YYYY-MM-DD or "
        f"'Month YYYY' (e.g. 2015-06 or June 2015)."
    )


# =========================
# Lexical similarity
# =========================

NUMBER_WORDS = set((
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
    "thirty forty fifty sixty seventy eighty ninety hundred thousand million "
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh "
    "twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth "
    "nineteenth twentieth thirtieth fortieth fiftieth hundredth"
).split())
ORDINAL_WORDS = NUMBER_WORDS - set((
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
    "thirty forty fifty sixty seventy eighty ninety hundred thousand million"
).split())
ROMAN_NUMBER_RE = re.compile(r"m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})")


def is_number_word(word: str) -> bool:
    """Digits, ordinals and Roman numerals receive no spelling tolerance."""
    return (any(c.isdigit() for c in word) or word in ORDINAL_WORDS
            or bool(word) and ROMAN_NUMBER_RE.fullmatch(word) is not None)


def one_edit_apart(a: str, b: str) -> bool:
    """Exactly one insertion, deletion, substitution or adjacent swap."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        differences = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(differences) == 1:
            return True
        if len(differences) == 2:
            i, j = differences
            return j == i + 1 and a[i] == b[j] and a[j] == b[i]
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def word_present(key_word: str, query_words: set, plural_allowed: bool = False) -> bool:
    """A stored word of at least five letters may contain one spelling edit."""
    if key_word in query_words:
        return True
    if plural_allowed and any(
            word.isalpha() and len(word) >= 3 and not is_number_word(word)
            and _singular_surface(key_word) == _singular_surface(word)
            for word in query_words):
        return True
    # Compare original words only: no spelling edit after a plural change.
    return (len(key_word) >= 5 and not is_number_word(key_word)
            and any(not is_number_word(word) and one_edit_apart(key_word, word)
                    for word in query_words))


def containment_score(query: str, key: str, plural_words: frozenset = frozenset()) -> float:
    """
    Directional token containment:
    How much of the canonical key appears in the query
    """
    Q = set(query.split())
    K = set(key.split())
    if not K:
        return 0.0
    return sum(word_present(word, Q, word in plural_words) for word in K) / len(K)


def char_ngrams(s: str, n: int = 3) -> set:
    return {s[i:i+n] for i in range(len(s) - n + 1)}


def char_ngram_similarity(a: str, b: str) -> float:
    """
    Directional char n-gram similarity
    """
    A = char_ngrams(a)
    B = char_ngrams(b)
    if not B:
        return 0.0
    return len(A & B) / len(B)


def entity_similarity(query_norm: str, key_norm: str,
                      plural_words: frozenset = frozenset()) -> float:
    """
    Combined lexical similarity score
    """
    if query_norm and query_norm == key_norm:
        return 1.0
    c1 = containment_score(query_norm, key_norm, plural_words)
    c2 = char_ngram_similarity(query_norm, key_norm)
    return 0.7 * c1 + 0.3 * c2

def row_entity_similarity(query_norm: str, entity_cell: str) -> float:
    """Score the best alternative, splitting before punctuation normalization."""
    return lexical_match_rank(query_norm, entity_cell)[1]


def event_match_rank(query_norm: str, cell: str) -> tuple:
    """Rank the best event alternative before normalization removes pipes."""
    return max(_surface_match_rank(query_norm, alternative) for alternative in cell.split("|"))


def _surface_match_rank(query_norm: str, cell: str) -> tuple:
    key = normalize_entity(cell)
    query_tokens = set(query_norm.split())
    key_tokens = set(key.split())
    total = len(query_tokens) + len(key_tokens)
    completeness = 2 * len(query_tokens & key_tokens) / total if total else 0.0
    return (bool(query_norm) and query_norm == key,
            entity_similarity(query_norm, key, stored_plural_words(cell)), completeness)


def lexical_match_rank(query_norm: str, cell: str) -> tuple:
    """Exact entity alternative, existing score, then token completeness."""
    return max(event_match_rank(query_norm, alternative)
               for alternative in cell.split("|"))


def chronological_match_rank(q_entity: str, q_event: str, row: dict) -> tuple:
    return _chronological_candidate(q_entity, q_event, row)[0]


def _chronological_candidate(q_entity: str, q_event: str, row: dict) -> tuple:
    """Each score must qualify; the weighted score only ranks qualifying rows."""
    entity = lexical_match_rank(q_entity, row["entity"])
    event = event_match_rank(q_event, row["event"])
    rank = (entity[0] and event[0], 0.6 * entity[1] + 0.4 * event[1],
            0.6 * entity[2] + 0.4 * event[2])
    return rank, entity[1] >= COMPONENT_BAR and event[1] >= COMPONENT_BAR

def normalize_time_key(t: str) -> Tuple[int, Optional[int], Optional[int]]:
    """Preserve an explicit day while retaining normalize_time's public API."""
    year, month = normalize_time(t)
    text = _fold(t.strip())
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return year, month, datetime.strptime(text, "%Y-%m-%d").day
    # Month-first English dates and day-first localized dates.
    match = re.search(r"\b[a-z]+\.?\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+\d{4}\b", text)
    if match is None:
        match = re.search(r"\b(\d{1,2})[.]?\s+[a-z]+\.?[,]?\s+\d{4}\b", text)
    day = int(match.group(1)) if match else None
    if day is not None:
        datetime(year, month, day)  # Reject impossible explicit dates.
    return year, month, day


def time_keys_match(query, row) -> bool:
    """Match every date component supplied by both query and table row."""
    return query[0] == row[0] and all(
        q is None or r is None or q == r for q, r in zip(query[1:], row[1:])
    )


def before_absolute_reference(
    entity: str,
    time: str,
    csv_path: str = BEFORE_ABSOLUTE_CSV
) -> str:
    q_entity = normalize_entity(entity)
    q_time = normalize_time_key(time)

    best_answer = None
    best_rank = (False, 0.0, 0.0)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_time = normalize_time_key(row["time"])

            # Time must match the reference time
            if not time_keys_match(q_time, r_time):
                continue

            rank = lexical_match_rank(q_entity, row["entity"])

            if rank[1] >= COMPONENT_BAR and rank > best_rank:
                best_rank = rank
                best_answer = row["answer"]

    if best_answer is None:
        raise LookupError("No matching before-absolute reference found")

    return best_answer

def before_chronological_reference(
    entity: str,
    event: str,
    csv_path: str = BEFORE_CHRONOLOGICAL_CSV
) -> str:
    q_entity = normalize_entity(entity)
    q_event = normalize_entity(event)

    best_answer = None
    best_rank = (False, 0.0, 0.0)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rank, qualifies = _chronological_candidate(q_entity, q_event, row)

            if qualifies and rank > best_rank:
                best_rank = rank
                best_answer = row["answer"]

    if best_answer is None:
        raise LookupError("No matching before-chronological reference found")

    return best_answer

def after_absolute_reference(
    entity: str,
    time: str,
    csv_path: str = AFTER_ABSOLUTE_CSV
) -> str:
    q_entity = normalize_entity(entity)
    q_time = normalize_time_key(time)

    best_answer = None
    best_rank = (False, 0.0, 0.0)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_time = normalize_time_key(row["time"])

            # Time must match the reference time
            if not time_keys_match(q_time, r_time):
                continue

            rank = lexical_match_rank(q_entity, row["entity"])

            if rank[1] >= COMPONENT_BAR and rank > best_rank:
                best_rank = rank
                best_answer = row["answer"]

    if best_answer is None:
        raise LookupError("No matching after-absolute reference found")

    return best_answer

def after_chronological_reference(
    entity: str,
    event: str,
    csv_path: str = AFTER_CHRONOLOGICAL_CSV
) -> str:
    q_entity = normalize_entity(entity)
    q_event = normalize_entity(event)

    best_answer = None
    best_rank = (False, 0.0, 0.0)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rank, qualifies = _chronological_candidate(q_entity, q_event, row)

            if qualifies and rank > best_rank:
                best_rank = rank
                best_answer = row["answer"]

    if best_answer is None:
        raise LookupError("No matching after-chronological reference found")

    return best_answer

def event_time(
    event: str,
    csv_path: str = EVENT_TIME_CSV
) -> str:
    q_event = normalize_entity(event)

    best_time = None
    best_rank = (False, 0.0, 0.0)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rank = event_match_rank(q_event, row["event"])

            if rank[1] >= COMPONENT_BAR and rank > best_rank:
                best_rank = rank
                best_time = row["answer"]

    if best_time is None:
        raise LookupError("No matching event time found")

    return best_time

def entity_time_event(entity: str, time: str, csv_path: str = ENTITY_TIME_EVENT_CSV) -> str:
    """
    Lookup (entity, time) -> event from CSV.
    Entity matching is robust to syntactic variation.
    Time must match year, and month if present. (in YYYY-MM-DD format)
    """
    q_entity = normalize_entity(entity)
    q_year, q_month = normalize_time(time)

    best_event = None
    best_rank = (False, 0.0, 0.0)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_year, r_month = normalize_time(row["time"])

            # Time filtering (hard constraint)
            if r_year != q_year:
                continue
            if q_month is not None and r_month is not None:
                if q_month != r_month:
                    continue

            rank = lexical_match_rank(q_entity, row["entity"])

            if rank[1] >= COMPONENT_BAR and rank > best_rank:
                best_rank = rank
                best_event = row["answer"]

    if best_event is None:
        raise LookupError("No matching entity-time event found")

    return best_event
