"""A shared vocabulary of fact relations, so agents store one predicate per meaning.

The extraction model names a relation in the user's words, and two agents told
the same kind of fact name it differently ("climate classification",
"koppen climate", "climate"); DAS matches predicates exactly, so a fact stored
by one agent would not join a fact stored by another. Every relation is mapped
to the closest entry of this vocabulary: by alias first, then by embedding
similarity with the local model memory already uses. A relation close to no
entry is kept as written. All agents run this code, so they converge on the
same names without reading DAS.
"""

import os
import re

try:
    from src.logger import get_logger
except ModuleNotFoundError:
    from logger import get_logger

logger = get_logger(__name__)

# name: (aliases, description). Aliases are matched exactly after
# normalisation; the description is what the relation is compared to.
VOCABULARY = {
    "state": (("state", "home state", "located in state", "us state"),
              "the state or province a place is in"),
    "country": (("country", "nation", "located in country"),
                "the country a place is in"),
    "population": (("population", "inhabitants", "residents", "number of people", "people live", "people living"),
                   "how many people live in a place, its population"),
    "nickname": (("nickname", "is called", "called", "known as", "also known as", "has nickname", "alias"),
                 "a nickname or other name something is called"),
    "climate_classification": (("climate", "climate classification", "koppen climate classification",
                                "koppen classification", "koppen climate", "climate type", "climate zone"),
                               "the climate or Koppen climate classification of a place"),
    "located_near": (("near", "sits near", "located near", "close to", "next to", "sits next to", "beside"),
                     "a place or thing located near another"),
    "located_in": (("located in", "stands in", "is in", "lies in", "situated in", "headquartered in", "based in"),
                   "the place a thing is located in"),
    "lives_in": (("lives in", "live in", "resides in"),
                 "the place where a person lives"),
    "works_at": (("works at", "works for", "employer", "employed by", "job at"),
                 "the company or place where a person works"),
    "job": (("job", "occupation", "profession", "role", "works as"),
            "the job or profession of a person"),
    "favorite_color": (("favorite color", "favourite color", "favourite colour"),
                       "the favorite color of a person"),
    "favorite_food": (("favorite food", "favourite food"),
                      "the favorite food of a person"),
    "founded_in": (("founded in", "established in", "founded"),
                   "the year or place something was founded"),
}

# Relations with a meaning of their own in recall, never mapped.
FIXED = {"is_a", "means", "stands_for", "is_short_for"}

# Cosine similarity of e5 vectors under which a relation keeps its own name.
# Measured: right matches score 0.85 and up ("sits close to" located_near 0.850,
# "number of inhabitants" population 0.918), wrong ones up to 0.84 ("logo color"
# favorite_color 0.839, "capital" country 0.835).
DEFAULT_THRESHOLD = 0.85

_MODEL_NAME = "intfloat/e5-large-v2"
_model = None
_model_failed = False
_entries = None
_cache = {}


def _normalise(relation):
    words = re.sub(r"[_\s]+", " ", str(relation or "").lower()).strip().split()
    while words and words[0] in ("is", "are", "has", "have", "the", "a", "an"):
        words = words[1:]
    return " ".join(words)


_ALIASES = {_normalise(alias): name for name, (aliases, _) in VOCABULARY.items() for alias in (name, *aliases)}


def _load():
    """The embedding model and the vocabulary vectors, or None when the model cannot load."""
    global _model, _model_failed, _entries
    if _model is not None or _model_failed:
        return _model
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        try:
            from lib_llm_ext import initLocalEmbedding
            _model = initLocalEmbedding()
        except Exception:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(_MODEL_NAME)
        names = list(VOCABULARY)
        texts = [f"query: {name.replace('_', ' ')}: {VOCABULARY[name][1]}" for name in names]
        _entries = (names, _model.encode(texts, normalize_embeddings=True))
    except Exception as e:
        logger.warning(f"Relation vocabulary off, the embedding model did not load: {e}")
        _model, _model_failed = None, True
    return _model


def _threshold():
    try:
        from config import config_get_by_key
        return float(config_get_by_key("relationVocabularyThreshold", DEFAULT_THRESHOLD))
    except Exception:
        return DEFAULT_THRESHOLD


def _enabled():
    try:
        from config import config_get_by_key
        value = config_get_by_key("relationVocabulary", True)
    except Exception:
        return True
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _closest(phrase):
    model = _load()
    if model is None:
        return None, 0.0
    names, vectors = _entries
    vector = model.encode([f"query: {phrase}"], normalize_embeddings=True)[0]
    scores = vectors @ vector
    best = int(scores.argmax())
    return names[best], float(scores[best])


def canonical(relation):
    """The vocabulary name for a snake_case relation, or the relation itself when nothing is close."""
    relation = str(relation or "")
    if not relation or relation in FIXED or relation.startswith("is_a_") or not _enabled():
        return relation
    if relation in _cache:
        return _cache[relation]
    phrase = _normalise(relation)
    name = _ALIASES.get(phrase)
    if name is None and phrase:
        best, score = _closest(phrase)
        if best is not None and score >= _threshold():
            name = best
        logger.info(f"relation {relation!r} closest {best!r} at {score:.3f}")
    result = name or relation
    _cache[relation] = result
    return result
