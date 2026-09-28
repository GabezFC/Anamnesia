"""Query canonicalization, fingerprinting and complexity classification (zero tokens, zero network).

WHY
---
Two things in the pipeline are keyed by the query: the judge cache and the amount of work the
pipeline decides to do. Both were previously driven by the raw string, which is the worst possible
key: "Qual driver do Postgres?" and "Que driver de Postgres?" ask the same thing of the same note
and produced two different cache keys (measured 2026-09-27: 0 cache hits across 204 recorded runs).

Three progressively looser representations are produced here, deliberately kept separate so the
cache can be layered and each layer measured on its own (see app/services/jev_cache.py):

  canonical()    accent-folded, lower-cased, stop-word free, ORDER PRESERVED, punctuation dropped.
                 Safe: two queries with the same canonical form differ only by casing/accents/
                 punctuation/function words.
  term_key()     the same terms, SORTED and de-duplicated. Order-independent, so word order and
                 duplicated terms no longer fork the key. This is the L2 cache layer.
  fingerprint()  ANCHOR terms only: lightly stemmed, with the question's "carrier" vocabulary
                 removed. This is the L3 layer, looser than L2, SHADOW MODE by default.

WHY L3 IS ANCHOR-BASED AND NOT JUST "STEMMED L2" (measured 2026-09-27)
---------------------------------------------------------------------
The first implementation of L3 was term_key() over stemmed terms. Measured against the 20 declared
paraphrase pairs of the synthetic corpus it hit 0/20 — worse than useless, since it cost a lookup
and returned nothing. The reason is visible immediately in the data:

    A: "Me lembra o que ficou registrado a respeito de KrampusDB v7.111-rc0?"
    B: "Qual o registro sobre KrampusDB v7.111-rc0 no vault?"
    terms only in A: ficou, lembra, me, registrado, respeito
    terms only in B: registro, vault
    shared: krampusdb, v7.111-rc0

The two questions agree on exactly the thing that identifies them — the identifier — and disagree on
everything else. What they disagree about is CARRIER vocabulary: the words a human wraps a question
in ("me lembra", "o que diz", "qual o registro", "what does the vault say about", "tem alguma nota
explicando"). Carrier words say how the user is asking; they carry no information about WHAT is being
asked. Set equality over all terms therefore measures phrasing, not intent, which is precisely the
failure mode that made the old cache score 0 hits in 204 runs.

So L3 keys on the ANCHORS: identifier-shaped tokens (versions, ports, hostnames, model names) plus
the remaining content words after carrier removal. Anchors are what a paraphrase cannot change
without becoming a different question.

CARRIER REMOVAL IS CONFINED TO L3 ON PURPOSE. The carrier list is aggressive and corpus-shaped, and
applying it at L1/L2 — or to the tokens used for lexical ranking and snippet extraction — would
silently weaken retrieval. L1 and L2 stay conservative; only the layer that is already gated behind
shadow-mode measurement gets the aggressive normalization.

RESIDUAL RISK, AND WHY IT IS BOUNDED
Two genuinely different questions about the SAME anchor collide ("qual a licenca do asyncpg" vs
"qual a versao do asyncpg" both anchor on {asyncpg}). That is a real false positive, which is why:
  - a cache entry is keyed on (query_repr, CANDIDATE CONTENT HASH), so a collision can only reuse a
    verdict about the very same note, never about a different one;
  - L3 is never served unless `promote_l3` is explicitly enabled;
  - the shadow path records suggested-vs-real relevance and its routing-band disagreement rate, so
    promotion is a decision backed by a measured false-positive number (§12).

The stemmer is intentionally a small suffix stripper, not a real lemmatizer: it must be
deterministic, dependency-free and identical across machines, because it is part of a cache key.
Any change to it, or to the carrier list, must bump QUERY_NORMALIZER_VERSION, which invalidates every
affected entry.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Part of every cache key that depends on query normalization. Bump on ANY behaviour change here.
# qn-v2 (2026-09-27): L3 fingerprint became ANCHOR-based (carrier vocabulary removed) after qn-v1
# measured 0/20 hits on the declared paraphrase pairs; the -ar/-er/-ir infinitive suffixes were also
# removed from the stemmer because they truncated agent nouns ("driver" -> "driv") and desynchronized
# singular from plural. Every qn-v1 entry is unreachable under this version, which is the point.
QUERY_NORMALIZER_VERSION = "qn-v2"

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\.:_]*")

# Portuguese + English function words. Shared vocabulary with the retrievers on purpose: a term
# that carries no retrieval signal must not carry cache-identity signal either.
STOPWORDS = frozenset("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra com
sem e ou que qual quais quando como onde porque porque se ser foi era eh sao esta estao estao mais
menos ja ainda sobre entre ate tambem foram tem ter ha fazer feito sido usa usam use usado usar
meu minha meus minhas seu sua seus suas nosso nossa isso isto esse essa este esta aquele aquela
ao aos eu voce ele ela lhe nao nem mas the of and to in is are was were what how why which who
whom for on with be being been it its this that these those there then than at from by as or not
no do does did can could should would will shall may might must about into over under
me mim te ti se si nos vos lhes meu minha teu tua dele dela deles delas
""".split())

# Interrogatives are stop-words for retrieval but they carry INTENT, so the complexity classifier
# looks at them before they are stripped.
_WH_MULTI = ("quais", "which", "todos", "todas", "all", "compare", "comparar", "diferenca",
             "diferencas", "difference", "versus", " vs ", "relacao", "relation", "impacto",
             "consequencia", "consequencias", "por que", "porque", "why", "como", "how")
_WH_SIMPLE = ("qual", "what", "quando", "when", "onde", "where", "quem", "who", "quanto", "quantos")

# Portuguese plural normalization applied BEFORE suffix stripping. Without it the stemmer is
# inconsistent across number: "migracoes" would strip -acoes -> "migr" while "migracao" strips -cao
# -> "migra", so the singular and plural of the same word would land on different stems and fork the
# cache key — exactly the failure the fingerprint layer exists to prevent.
_PLURAL: tuple[tuple[str, str], ...] = (
    ("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("ois", "ol"), ("uis", "ul"),
    ("ns", "m"), ("res", "r"), ("zes", "z"), ("ses", "s"), ("les", "l"), ("ies", "y"),
)

# Suffixes stripped by the lite stemmer, longest first. Only endings whose removal is
# meaning-preserving for retrieval in this corpus; nothing shorter than 2 chars is stripped, and a
# stem is never reduced below 4 characters.
#
# The verb-infinitive endings -ar/-er/-ir are DELIBERATELY ABSENT. They wreck the agent nouns that
# dominate this corpus: "driver" -> "driv", "server" -> "serv", "container" -> "contain", while the
# plural "drivers" loses only -s and becomes "driver" — so the singular and plural of the same word
# stemmed to different values and forked the very cache key this layer exists to unify (measured
# 2026-09-27). Portuguese infinitives are also almost always stop-words here (usar, ser, ter), so
# stripping them buys nothing and costs correctness.
_SUFFIXES = (
    "mente", "cao", "dade", "ade", "ismo", "ista", "izar", "vel", "ndo", "ing", "ment", "tion",
    "ed", "ly", "s",
)
_MIN_STEM = 4

# CARRIER vocabulary — words that describe HOW a question is asked, never WHAT it asks about.
# Applied ONLY at the L3 fingerprint layer (see the module docstring); never at L1/L2 and never in
# the token stream used for lexical ranking or snippet extraction, because several of these words
# ("nota", "documento") are legitimate retrieval signals in note filenames and headings.
_CARRIER_WORDS = """
lembra lembrar lembre recorda recordar registrado registro registros anotado anotacao anota
respeito refere referente relativo assunto conta contar diz dizer dito fala falar
explica explicando explicacao explicar afirma afirmar afirmacao mostra mostrar informa
say says said tell tells told know knows explain explains mention mentions state states
vault cofre cerebro nota notas note notes pagina paginas documento documentos arquivo
arquivos texto conteudo informacao informacoes detalhe detalhes resumo
alguma algum algo alguem qualquer tudo nada coisa vez
ficou ficar fica existe existir havia tinha
""".split()


def fold(text: str) -> str:
    """Lower-case and strip diacritics: 'decisão' -> 'decisao'."""
    folded = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def tokens(text: str) -> list[str]:
    """Significant tokens in ORIGINAL ORDER. Keeps dots/colons/hyphens inside a token so version
    strings and hostnames survive intact ('asyncpg-0.31', '127.0.0.1:49374', 'qwen2.5-coder:7b')."""
    out: list[str] = []
    for raw in _TOKEN.findall(fold(text)):
        t = raw.strip("-._:")
        if len(t) < 2 or t in STOPWORDS:
            continue
        out.append(t)
    return out


def canonical(query: str) -> str:
    """L1-safe canonical form: same terms, same order, no casing/accents/punctuation/stop-words."""
    return " ".join(tokens(query))


def term_key(query: str) -> tuple[str, ...]:
    """L2 form: sorted unique significant terms. Order- and repetition-independent."""
    return tuple(sorted(set(tokens(query))))


def stem(term: str) -> str:
    """Suffix-stripping stem, in two ordered steps: plural normalization, then suffix removal.

    Never touches tokens carrying digits or structural punctuation: 'asyncpg-0.31' and
    'qwen2.5-coder:7b' are identifiers, and truncating them destroys the only signal that makes
    them findable.
    """
    if any(ch.isdigit() for ch in term) or any(ch in term for ch in ".:_"):
        return term
    t = term
    for plural, singular in _PLURAL:
        if t.endswith(plural) and len(t) - len(plural) + len(singular) >= _MIN_STEM:
            t = t[: -len(plural)] + singular
            break
    for suf in sorted(_SUFFIXES, key=len, reverse=True):
        if t.endswith(suf) and len(t) - len(suf) >= _MIN_STEM:
            return t[: -len(suf)]
    return t


# Built AFTER stem() so carrier membership is tested on stems, which makes the list cover
# inflections ("registrado"/"registro"/"registros") without enumerating each one.
CARRIER: frozenset[str] = frozenset(stem(w) for w in _CARRIER_WORDS)


def fingerprint(query: str) -> tuple[str, ...]:
    """L3 form: sorted unique ANCHOR stems — carrier vocabulary removed. Shadow mode by default.

    Anchors are identifier-shaped tokens plus the content words that remain once the question's
    carrier phrasing is stripped. Degradation is deliberate and ordered:
      - if removing carriers would leave NOTHING, the stemmed term set is returned instead. A key is
        always better than no key, and an all-carrier query ("o que o vault diz?") is degenerate
        anyway — it will simply never match another query's anchors.
      - identifier tokens are never stemmed and never treated as carriers, so a version string always
        anchors the key.
    """
    stems = {stem(t) for t in tokens(query)}
    anchors = {s for s in stems if s not in CARRIER}
    return tuple(sorted(anchors or stems))


@dataclass(frozen=True)
class QueryProfile:
    """Everything the pipeline needs to decide how much work a query deserves."""
    raw: str
    canonical: str
    terms: tuple[str, ...]
    fingerprint: tuple[str, ...]
    n_terms: int
    n_rare: int          # terms that look like identifiers/versions (high-precision signals)
    complexity: str      # SIMPLE | MEDIUM | COMPLEX | AMBIGUOUS
    multi_hop_hint: bool

    def to_dict(self) -> dict:
        return {"query_complexity": self.complexity, "query_terms": self.n_terms,
                "query_rare_terms": self.n_rare, "query_multi_hop_hint": self.multi_hop_hint,
                "query_canonical": self.canonical}


def _is_rare(term: str) -> bool:
    """A token that looks like an identifier: digits, dotted version, colon, or CamelCase-ish."""
    return any(ch.isdigit() for ch in term) or any(ch in term for ch in ".:_") or len(term) >= 12


def classify(query: str) -> QueryProfile:
    """Local query complexity classification (§18). Measurable features only, no model call.

    The classes exist to select top_k / snippet size / strict mode, so the rules are biased toward
    spending MORE when in doubt: a query that is hard to classify is AMBIGUOUS, which buys more
    candidates, never fewer. Under-spending loses recall silently; over-spending only costs money.
    """
    folded = fold(query)
    ts = tokens(query)
    n = len(ts)
    rare = sum(1 for t in ts if _is_rare(t))
    multi = any(w in folded for w in _WH_MULTI)
    # "e"/"and" joining two clauses, or an explicit enumeration, suggests more than one target note.
    conj = len(re.findall(r"\b(e|and)\b", folded)) >= 1 and n >= 6
    multi_hop = bool(multi and (conj or n >= 8))

    if n == 0:
        complexity = "AMBIGUOUS"
    elif n <= 2 and rare == 0 and not multi:
        # Two generic words: could mean anything in the vault. Cheap to judge, dangerous to trim.
        complexity = "AMBIGUOUS"
    elif rare >= 1 and n <= 6 and not multi:
        # An identifier plus a little context: the lexical ranker is usually decisive here.
        complexity = "SIMPLE"
    elif n <= 5 and any(folded.startswith(w) for w in _WH_SIMPLE) and not multi:
        complexity = "SIMPLE"
    elif multi_hop or n >= 12:
        complexity = "COMPLEX"
    else:
        complexity = "MEDIUM"

    return QueryProfile(raw=query, canonical=canonical(query), terms=term_key(query),
                        fingerprint=fingerprint(query), n_terms=n, n_rare=rare,
                        complexity=complexity, multi_hop_hint=multi_hop)
