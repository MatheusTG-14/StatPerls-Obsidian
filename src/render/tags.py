"""Deterministic tags from frozen rules (schema/vocab/*.yaml mirrors these lists)."""
import re

ARTICLE_TYPES = ["disease", "procedure", "concept", "drug", "anatomy", "basic-science", "toxicology", "lab-test", "nursing", "other"]

IMAGE_MODALITIES = [
    ("video", None),
    ("ecg", r"electrocardiogra|\bECGs?\b|\bEKGs?\b|rhythm strip"),
    ("histology", r"\bH ?& ?E\b|hematoxylin|haematoxylin|histolog|histopatholog|micrograph|biopsy|cytolog|\bsmear\b|\bstain(ed|ing)?\b|magnification|\b\d+ ?[x×]\b|immunohisto"),
    ("ct", r"(?i:computed tomograph)|\bCT\b|\bCTA\b|\bHRCT\b"),
    ("mri", r"(?i:magnetic resonance)|\bMRI\b|\bMRA\b|T[12][- ]weighted|\bFLAIR\b"),
    ("ultrasound", r"ultrason|sonogra|echocardiogra|\bdoppler\b|\bPOCUS\b|\bTTE\b|\bTEE\b"),
    ("angiography", r"angiogra|arteriogra|venogra|fluorosc|cholangiogra|\bERCP\b"),
    ("radiograph", r"radiograph|x-?ray|plain film|\bfilm\b"),
    ("endoscopy", r"endoscop|colonoscop|bronchoscop|laparoscop|arthroscop|cystoscop|laryngoscop|gastroscop|hysteroscop"),
    ("ophthalmic", r"fundus|fundoscop|slit[- ]lamp|optical coherence tomography|\bOCT\b|retinal photo"),
    ("chart-table", r"\btable\b|\bchart\b|algorithm|flowchart|flow chart|\bgraph\b|criteria|\bscore\b"),
    ("diagram", r"illustrat|diagram|schemat|drawing|depict|cartoon|artwork"),
    ("clinical-photo", r"photograph|\bphoto\b|clinical image|lesions?\b|\brash\b|\bpatient\b|\bpapules?\b|\bplaques?\b|\bnodules?\b|\bulcers?\b|erythema"),
]
MODALITY_VALUES = [m for m, _ in IMAGE_MODALITIES] + ["unclassified"]

CREDIT_CLASSES = [
    ("public-domain", r"public domain|not subject to copyright"),
    ("cc-by-sa", r"CC[ -]?BY[ -]?SA|by-sa"),
    ("cc-by", r"CC[ -]?BY|creativecommons"),
    ("dermnet", r"dermnet"),
    ("contributed", r"contributed|courtesy|illustrated by|made by|created by|provided by"),
]
CREDIT_VALUES = [c for c, _ in CREDIT_CLASSES] + ["other"]


def article_type(rec):
    """Works on a full L1 record or an l1_index entry (which carries "h2")."""
    h = set(rec["h2"]) if "h2" in rec else {s["title"] for s in rec["sections"]}
    t = rec["title"]
    if rec["kind"] == "nursing":
        return "nursing"
    if "Mechanism of Action" in h and ("Administration" in h or "Adverse Effects" in h):
        return "drug"
    if "Toxicokinetics" in h:
        return "toxicology"
    if t.startswith("Anatomy,") or "Structure and Function" in h:
        return "anatomy"
    if h & {"Equipment", "Technique or Treatment", "Preparation"}:
        return "procedure"
    if h & {"Cellular Level", "Molecular Level", "Organ Systems Involved"} or t.startswith(
        ("Physiology,", "Biochemistry,", "Histology,", "Embryology,", "Genetics,", "Microbiology,", "Neuroanatomy,")
    ):
        return "basic-science"
    if h & {"Interfering Factors", "Specimen Requirements and Procedure", "Results, Reporting, and Critical Findings"}:
        return "lab-test"
    if h & {"Etiology", "Pathophysiology", "Differential Diagnosis"}:
        return "disease"
    if h & {"Definition/Introduction", "Issues of Concern", "Clinical Significance"}:
        return "concept"
    return "other"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def anatomy_region(title):
    m = re.match(r"(?:Anatomy|Neuroanatomy), ([^:,]+)[:,]", title)
    return slug(m.group(1)) if m else None


def anatomy_structure(title):
    m = re.match(r"(?:Anatomy|Neuroanatomy), [^:]+: (.+)$", title)
    return m.group(1).strip() if m else None


def modality(caption, kind):
    if kind == "video":
        return "video"
    for name, rx in IMAGE_MODALITIES[1:]:
        if re.search(rx, caption, re.I if name not in ("ct", "mri") else 0):
            return name
    return "unclassified"


def credit_class(caption):
    for name, rx in CREDIT_CLASSES:
        if re.search(rx, caption, re.I):
            return name
    return "other"
