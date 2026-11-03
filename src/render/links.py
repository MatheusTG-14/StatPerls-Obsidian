"""Tier 1 linking: exact, case-insensitive mentions of article titles and
deterministic aliases. Closed world: targets come only from the title index.

Policy: first mention per note per target; no self-links; single-word keys
need 5+ letters and must not be in the stoplist; all-caps abbreviations and
keys under 5 characters are never auto-linked (design notes).
"""
import re

TOKEN = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’-][0-9A-Za-zÀ-ÖØ-öø-ÿ]+)*")
STOPLIST = {
    "pain", "fever", "shock", "cough", "fatigue", "nausea", "vomiting", "itching", "anxiety", "depression",
    "obesity", "trauma", "stress", "aging", "death", "sleep", "exercise", "nutrition", "ethics", "consent",
    "triage", "delirium", "edema", "syncope", "headache", "dizziness", "weakness", "malnutrition", "dehydration",
    "inflammation", "infection", "sepsis", "hypoxia", "toxicity", "pharmacokinetics", "pharmacodynamics",
    "hemorrhage", "bleeding", "physiology", "anatomy", "embryology", "histology", "biochemistry", "genetics",
    "prognosis", "screening", "palpitations", "dyspnea", "constipation", "diarrhea", "jaundice", "cyanosis",
    # generic research / practice terms: dominate link counts, rarely what the reader wants (link report 2026-10-27)
    "incidence", "prevalence", "median", "collaboration", "adverse events", "medical history", "public health",
    "informed consent", "electrolytes",
}
# A match is skipped when it is only the head of a longer term ("adenosine triphosphate", "interferon regulatory factor").
NEXT_BLOCK = {
    "monophosphate", "diphosphate", "triphosphate", "regulatory", "receptor", "receptors", "agonist", "agonists",
    "antagonist", "antagonists", "inhibitor", "inhibitors", "gene", "genes", "deaminase", "kinase", "synthase",
    "factor", "factors", "analog", "analogs", "analogue", "derivative", "derivatives", "pathway", "resistance",
}
PREV_BLOCK = {"cyclic", "anti", "pseudo", "non", "haemophilus", "hemophilus"}


def norm_key(s):
    return " ".join(TOKEN.findall(s)).lower()


class TitleIndex:
    def __init__(self, entries):
        """entries: iterable of (surface_key_text, target_id). Ambiguous keys are dropped."""
        seen = {}
        for text, target in entries:
            key = norm_key(text)
            if not self._eligible(text, key):
                continue
            seen.setdefault(key, set()).add(target)
        self.keys = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
        self.ambiguous = sorted(k for k, v in seen.items() if len(v) > 1)
        self.by_first = {}
        for k in self.keys:
            toks = k.split(" ")
            self.by_first.setdefault(toks[0], []).append((len(toks), toks))
        for v in self.by_first.values():
            v.sort(key=lambda x: (-x[0], x[1]))

    @staticmethod
    def _eligible(text, key):
        if len(key) < 5:
            return False
        toks = key.split(" ")
        if key in STOPLIST or (len(toks) == 1 and not key.isalpha()):
            return False
        letters = re.sub(r"[^A-Za-z]", "", text)
        if letters and letters.isupper():
            return False
        return True

    def find(self, text):
        """Yield (start, end, target) for non-overlapping longest matches."""
        toks = [(m.group(0).lower(), m.start(), m.end()) for m in TOKEN.finditer(text)]
        i = 0
        while i < len(toks):
            hit = None
            for n, ktoks in self.by_first.get(toks[i][0], ()):
                if i + n > len(toks):
                    continue
                if all(toks[i + j][0] == ktoks[j] for j in range(n)):
                    span = text[toks[i][1]:toks[i + n - 1][2]]
                    if norm_key(span) == " ".join(ktoks) and _gaps_ok(span):
                        nxt = toks[i + n][0] if i + n < len(toks) and _adjacent(text, toks[i + n - 1][2], toks[i + n][1]) else None
                        prv = toks[i - 1][0] if i > 0 and _adjacent(text, toks[i - 1][2], toks[i][1]) else None
                        if nxt in NEXT_BLOCK or prv in PREV_BLOCK:
                            hit = (None, None, None, n)
                        else:
                            hit = (toks[i][1], toks[i + n - 1][2], self.keys[" ".join(ktoks)], n)
                        break
            if hit:
                if hit[2] is not None:
                    yield hit[:3]
                i += hit[3]
            else:
                i += 1


def _adjacent(text, end, start):
    """Two tokens belong to one phrase when only a space or hyphen separates them."""
    return re.fullmatch(r"[ \-]", text[end:start]) is not None


def _gaps_ok(span):
    """Matched words must be separated by spaces, hyphens or commas only (no sentence breaks)."""
    gaps = TOKEN.sub("\0", span).split("\0")[1:-1]
    return all(re.fullmatch(r"[ ,\-–/]{1,3}", g) for g in gaps)
