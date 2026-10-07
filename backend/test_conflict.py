import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.boq.services.product_matching_service import product_type_conflicts, _significant_type_tokens, _normalize_text

extracted = {
    "description_hint": "class MS cable tray (non catalogued MEP product), 300 mm width x 50 mm depth",
    "category": "PIPE",
    "sub_category": "MS",
    "class": "C",
    "size": 50,
    "unit": "mm"
}

class FakeRate:
    def __init__(self):
        self.Category = "PIPE"
        self.Sub_Category = "MS"
        self.Class = "C"
        self.Size = 50

rate = FakeRate()
hint = extracted.get("description_hint")
hint_tokens = _significant_type_tokens(hint)
print("hint_tokens:", hint_tokens)

catalog_tokens = set()
for value in (rate.Category, rate.Sub_Category, rate.Class):
    catalog_tokens |= _significant_type_tokens(value)
print("catalog_tokens:", catalog_tokens)
print("intersection:", hint_tokens & catalog_tokens)

extract_sub = extracted.get("sub_category", "").strip().upper()
catalog_sub = (rate.Sub_Category or "").strip().upper()
print("extract_sub:", extract_sub)
print("catalog_sub:", catalog_sub)

print("product_type_conflicts:", product_type_conflicts(extracted, rate))  # type: ignore
