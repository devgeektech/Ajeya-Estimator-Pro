import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.boq.services.product_matching_service import _normalize_text
from utils.product_synonyms import labels_equivalent

class DummyRate:
    def __init__(self, cat, sub, cls):
        self.Category = cat
        self.Sub_Category = sub
        self.Class = cls

extracted = {
    "category": "HYDRANT",
    "sub_category": "FIRE MAN AXE",
    "description_hint": "standard Fireman's Axe with heavy insulated rubber handle.",
}

rate36 = DummyRate("HYDRANT", "FIRE MAN AXE", "FORGED STEEL")
rate39 = DummyRate("HYDRANT", "FIRE BRIGADE SUCTION HOSE COUPLING", "RUBBER")

extract_sub = _normalize_text(extracted.get("sub_category"))
extract_cat = _normalize_text(extracted.get("category"))

def _taxonomy_score(rate):
    score = 0.0
    if extract_sub and labels_equivalent(extract_sub, _normalize_text(rate.Sub_Category)):
        score += 1.0
    if extract_cat and _normalize_text(rate.Category) == extract_cat:
        score += 0.5
    return score

print("Taxonomy 36:", _taxonomy_score(rate36))
print("Taxonomy 39:", _taxonomy_score(rate39))
