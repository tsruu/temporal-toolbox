# app/tools/temporal.py
import re
from datetime import datetime
import csv
import re
import string
import unicodedata
from datetime import datetime
from typing import Tuple, Optional
import os

BASE_DIR = os.path.dirname(__file__)

BEFORE_ABSOLUTE_CSV = os.path.join(BASE_DIR, "before_absolute_reference.csv")
BEFORE_CHRONOLOGICAL_CSV = os.path.join(BASE_DIR, "before_chronological_reference.csv")

AFTER_ABSOLUTE_CSV = os.path.join(BASE_DIR, "after_absolute_reference.csv")
AFTER_CHRONOLOGICAL_CSV = os.path.join(BASE_DIR, "after_chronological_reference.csv")

ENTITY_TIME_EVENT_CSV = os.path.join(BASE_DIR, "entity_time_event.csv")
EVENT_TIME_CSV = os.path.join(BASE_DIR, "event_time.csv")

# =========================
# Entity normalization
# =========================

def normalize_entity(text: str) -> str:
    """
    Safe normalization:
    - lowercase
    - remove possessive 's
    - remove punctuation
    - collapse whitespace
    """
    text = text.lower()
    text = text.replace("'s", "")
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text).strip()
    return text


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

def containment_score(query: str, key: str) -> float:
    """
    Directional token containment:
    How much of the canonical key appears in the query
    """
    Q = set(query.split())
    K = set(key.split())
    if not K:
        return 0.0
    return len(Q & K) / len(K)


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


def entity_similarity(query_norm: str, key_norm: str) -> float:
    """
    Combined lexical similarity score
    """
    c1 = containment_score(query_norm, key_norm)
    c2 = char_ngram_similarity(query_norm, key_norm)
    return 0.7 * c1 + 0.3 * c2

def before_absolute_reference(
    entity: str,
    time: str,
    csv_path: str = BEFORE_ABSOLUTE_CSV
) -> str:
    q_entity = normalize_entity(entity)
    q_year, q_month = normalize_time(time)

    best_answer = None
    best_score = 0.0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_year, r_month = normalize_time(row["time"])

            # Time must match the reference time
            if r_year != q_year:
                continue
            if q_month is not None and r_month is not None and q_month != r_month:
                continue

            score = entity_similarity(
                q_entity,
                normalize_entity(row["entity"])
            )

            if score > best_score:
                best_score = score
                best_answer = row["answer"]

    if best_answer is None or best_score < 0.75:
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
    best_score = 0.0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            score = (
                0.6 * entity_similarity(q_entity, normalize_entity(row["entity"])) +
                0.4 * entity_similarity(q_event, normalize_entity(row["event"]))
            )

            if score > best_score:
                best_score = score
                best_answer = row["answer"]

    if best_answer is None or best_score < 0.75:
        raise LookupError("No matching before-chronological reference found")

    return best_answer

def after_absolute_reference(
    entity: str,
    time: str,
    csv_path: str = AFTER_ABSOLUTE_CSV
) -> str:
    q_entity = normalize_entity(entity)
    q_year, q_month = normalize_time(time)

    best_answer = None
    best_score = 0.0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_year, r_month = normalize_time(row["time"])

            # Time must match the reference time
            if r_year != q_year:
                continue
            if q_month is not None and r_month is not None and q_month != r_month:
                continue

            score = entity_similarity(
                q_entity,
                normalize_entity(row["entity"])
            )

            if score > best_score:
                best_score = score
                best_answer = row["answer"]

    if best_answer is None or best_score < 0.75:
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
    best_score = 0.0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            score = (
                0.6 * entity_similarity(q_entity, normalize_entity(row["entity"])) +
                0.4 * entity_similarity(q_event, normalize_entity(row["event"]))
            )

            if score > best_score:
                best_score = score
                best_answer = row["answer"]

    if best_answer is None or best_score < 0.75:
        raise LookupError("No matching after-chronological reference found")

    return best_answer

def event_time(
    event: str,
    csv_path: str = EVENT_TIME_CSV
) -> str:
    q_event = normalize_entity(event)

    best_time = None
    best_score = 0.0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            score = entity_similarity(
                q_event,
                normalize_entity(row["event"])
            )

            if score > best_score:
                best_score = score
                best_time = row["answer"]

    if best_time is None or best_score < 0.75:
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
    best_score = 0.0

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

            key_norm = normalize_entity(row["entity"])
            score = entity_similarity(q_entity, key_norm)

            if score > best_score:
                best_score = score
                best_event = row["answer"]

    if best_event is None or best_score < 0.75:
        raise LookupError("No matching entity-time event found")

    return best_event