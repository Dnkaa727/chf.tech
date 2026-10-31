"""Validated catalog/rubric snapshots; legacy scoring data never enters v3."""
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from app.retrieval import normalize, related_token, term_in_query, tokens
from .json_validation import strict_json_loads

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT/'data'/'knowledge_base.json'
RUBRICS_PATH = ROOT/'data'/'rubrics_all_25.json'


class RegistryValidationError(ValueError):
    pass


class CardNotFound(LookupError):
    pass


class AmbiguousCardSelection(ValueError):
    def __init__(self, candidates):
        super().__init__('Specify a topic or choose an explicit card_id')
        self.candidates = candidates


def _require(condition, message):
    if not condition:
        raise RegistryValidationError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _index(rows, key):
    _require(isinstance(rows, list), 'Expected an array of cards or rubrics')
    result = {}; seen = set()
    for row in rows:
        _require(isinstance(row, dict) and _text(row.get(key)), 'Invalid card identifier')
        identifier = row[key]
        _require(identifier == identifier.strip(), 'Whitespace in card identifier')
        _require(identifier.casefold() not in seen, 'Duplicate card or rubric ID')
        seen.add(identifier.casefold()); result[identifier] = row
    return result


@dataclass(frozen=True)
class CardSnapshot:
    card: dict
    rubric: dict
    registry_version: str
    rubric_version: str
    rubric_hash: str


def public_card(card):
    """Explicit allowlist: no criteria, anchors, flags, prompts or follow-ups."""
    return {'card_id': card['id'], 'competency': card['competency'],
            'topic': card['topic'], 'question': card['question'],
            'target_level': card['target_level'], 'demo_priority': card['priority_for_demo'],
            'review_status': card['review_status'], 'aliases': list(card['aliases']),
            'retrieval_tags': list(card['retrieval_tags']),
            'source_urls': [s['url'] for s in card['source_vacancies']]}


class CardRegistry:
    def __init__(self, knowledge_base, rubric_data):
        _require(isinstance(knowledge_base, dict) and knowledge_base.get('schema_version') == '2.0',
                 'Expected the v2 catalog without legacy scoring fields')
        _require(isinstance(rubric_data, dict) and rubric_data.get('schema_version') == '3.0',
                 'Unsupported rubric format')
        cards = _index(knowledge_base.get('cards'), 'id')
        rubrics = _index(rubric_data.get('rubrics'), 'card_id')
        _require(len(cards) == len(rubrics) == 25 and set(cards) == set(rubrics),
                 'Expected exactly one rubric for each of the 25 cards')
        criterion_ids = set()
        for cid, card in cards.items():
            forbidden = {'criteria', 'followup_questions', 'red_flag_definitions', 'decision_policy', 'anchors'}
            _require(not forbidden.intersection(card), 'Scoring data belongs only in Rubrics')
            for field in ('competency', 'topic', 'question', 'target_level', 'review_status', 'priority_for_demo'):
                _require(_text(card.get(field)), 'Missing catalog metadata: '+field)
            for field in ('aliases', 'retrieval_tags'):
                _require(isinstance(card.get(field), list) and all(_text(x) for x in card[field]),
                         'Invalid catalog search metadata')
            sources = card.get('source_vacancies')
            _require(isinstance(sources, list) and bool(sources) and all(
                isinstance(s, dict) and _text(s.get('vacancy_id')) and _text(s.get('url'))
                and s['url'].startswith('https://') for s in sources), 'Missing source provenance')
            rubric = rubrics[cid]
            for field in ('competency', 'topic', 'question', 'target_level'):
                _require(rubric.get(field) == card[field], 'Catalog/rubric mismatch: '+field)
            _require(rubric.get('source_card_id') == cid, 'Rubric source_card_id mismatch')
            _require(_text(rubric.get('version')) and _text(rubric.get('status')), 'Missing rubric version/status')
            criteria = rubric.get('criteria')
            _require(isinstance(criteria, list) and len(criteria) == 5, 'Expected five criteria per rubric')
            for criterion in criteria:
                _require(isinstance(criterion, dict) and _text(criterion.get('id')), 'Invalid criterion')
                key = criterion['id']
                _require(key not in criterion_ids, 'Duplicate criterion ID')
                criterion_ids.add(key)
                _require(key.startswith(cid+'-') and _text(criterion.get('name')), 'Criterion/card mismatch')
                _require(type(criterion.get('max_points')) is int and criterion['max_points'] == 2,
                         'Expected criteria with maximum two points')
                anchors = criterion.get('anchors')
                _require(isinstance(anchors, dict) and set(anchors) == {'0', '1', '2'}
                         and all(_text(v) for v in anchors.values()), 'Invalid 0/1/2 anchors')
                _require(_text(criterion.get('followup_question')), 'Missing criterion follow-up')
            flags = rubric.get('red_flag_definitions')
            _require(isinstance(flags, list) and bool(flags), 'Missing rubric red flags')
            flag_ids = set()
            for flag in flags:
                _require(isinstance(flag, dict) and _text(flag.get('id'))
                         and _text(flag.get('definition')), 'Invalid red flag definition')
                _require(flag['id'] not in flag_ids, 'Duplicate red flag ID')
                flag_ids.add(flag['id'])
            policy = rubric.get('decision_policy')
            _require(isinstance(policy, dict) and type(policy.get('high_evidence_threshold')) is int
                     and policy['high_evidence_threshold'] == 8
                     and type(policy.get('max_followups_per_topic')) is int
                     and policy['max_followups_per_topic'] == 2, 'Unsupported interview decision policy')
        self._cards = deepcopy(cards)
        self._rubrics = deepcopy(rubrics)
        self._version = _hash({'knowledge_base': knowledge_base, 'rubrics': rubric_data})

    @classmethod
    def load(cls, kb_path=None, rubrics_path=None):
        kb = strict_json_loads(Path(kb_path or KB_PATH).read_text(encoding='utf-8'))
        rs = strict_json_loads(Path(rubrics_path or RUBRICS_PATH).read_text(encoding='utf-8'))
        return cls(kb, rs)

    @property
    def version(self):
        return self._version

    def cards(self):
        return deepcopy(self._cards)

    def rubrics(self):
        return deepcopy(self._rubrics)

    def get(self, card_id):
        if card_id not in self._cards:
            raise CardNotFound('Unknown card_id')
        rubric = self._rubrics[card_id]
        return CardSnapshot(deepcopy(self._cards[card_id]), deepcopy(rubric), self.version,
                            rubric['version'], _hash(rubric))

    def public_cards(self):
        return [public_card(c) for c in self._cards.values()]

    def select(self, *, card_id=None, query='', competency=None):
        cards = list(self._cards.values())
        if competency:
            f = normalize(competency)
            cards = [c for c in cards if any(normalize(n) == f
                     for n in (c['competency'], *c['aliases']))]
        if card_id:
            if not any(c['id'] == card_id for c in cards):
                raise CardNotFound('Unknown card_id or conflicting competency')
            return self.get(card_id)
        q = normalize(query)
        if not q and not competency:
            raise ValueError('Specify query, competency or card_id')
        if q:
            exact = [c for c in cards if q in (normalize(c['id']), normalize(c['topic']), normalize(c['question']))]
            generic = [c for c in cards if any(normalize(n) == q
                       for n in (c['competency'], *c['aliases']))]
            query_tokens = tokens(q)
            topical = [c for c in cards if any(term_in_query(t, q) for t in c['retrieval_tags'])
                       or any(len(w) > 3 and any(related_token(w, t) for t in query_tokens)
                              for w in tokens(c['topic']))]
            cards = exact or generic or topical
        if not cards:
            raise CardNotFound('No matching card')
        if len(cards) != 1:
            # Priority and alphabetical ordering cannot turn ambiguity into selection.
            raise AmbiguousCardSelection([public_card(c) for c in cards])
        return self.get(cards[0]['id'])


@lru_cache(maxsize=1)
def get_registry():
    """Load once per process; refresh explicitly/restart for a new data release."""
    return CardRegistry.load()
