import sys
import os

# Add backend to path
sys.path.append(os.path.abspath('backend'))

from utils.product_synonyms import _AI_SYNONYM_CATALOG

# Hardcoded nested ones we MUST keep
_core = (
    ("external fire hose box", "HYDRANT", "FIRE HOSE BOX"),
    ("fire hose cabinet", "HYDRANT", "FIRE HOSE BOX"),
    ("fire hose box", "HYDRANT", "FIRE HOSE BOX"),
    ("hose cabinet", "HYDRANT", "FIRE HOSE BOX"),
    ("hose box", "HYDRANT", "FIRE HOSE BOX"),
    ("fire hose reel", "HYDRANT", "FIRE HOSE REEL"),
    ("hose reel", "HYDRANT", "FIRE HOSE REEL"),
    ("short branch pipe", "HYDRANT", "SHORT BRANCH PIPE"),
    ("branch pipe", "HYDRANT", "BRANCH PIPE"),
)

_raw = list(_core)

# Exclude materials/short generic words that might cause bad overrides
# "pipe", "valve", "pump", "tank" on their own shouldn't override specific extraction
_exclude = {"ms", "gi", "ss", "ci", "di", "pipe", "valve", "pump", "tank", "hose", "abc", "co2", "dcp", "foam", "pvc"}

for (cat, sub), syns in _AI_SYNONYM_CATALOG.items():
    phrase = sub.lower()
    if phrase not in _exclude and len(phrase) > 3:
        _raw.append((phrase, cat, sub))
    for syn in syns:
        sp = syn.lower()
        if sp not in _exclude and len(sp) > 3:
            _raw.append((sp, cat, sub))

unique = list(set(_raw))
unique.sort(key=lambda x: len(x[0]), reverse=True)

for p, c, s in unique:
    print(f'("{p}", "{c}", "{s}"),')
