import json
from pathlib import Path

ROLE_MAP_FILE = Path(__file__).resolve().parent.parent / "agent_guides" / "ROLE_MODEL_MAP.json"

DEFAULT_ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_ROLE_MODEL = "gemini-2.5-flash-lite"
DEFAULT_CODE_MODEL = "gemini-2.5-pro"

_GUIDE_TO_ROLE = {
    "ROLE_PM.txt": "PM",
    "ROLE_TECH_LEAD.txt": "TECH_LEAD",
    "ROLE_TECH_WRITER.txt": "TECH_WRITER",
    "ROLE_QA.txt": "QA",
    "ROLE_DEVOPS.txt": "DEVOPS",
    "ROLE_FE.txt": "FE",
    "ROLE_BE.txt": "BE",
    "ROLE_BUILDER.txt": "BUILDER",
    "ROLE_REVIEWER.txt": "REVIEWER",
}

def load_role_model_map() -> dict:
    if not ROLE_MAP_FILE.exists():
        return {
            "endpoint_base": DEFAULT_ENDPOINT_BASE,
            "roles": {},
        }
    text = ROLE_MAP_FILE.read_text(encoding="ascii")
    return json.loads(text)

def role_from_guide_filename(role_guide_filename: str) -> str:
    name = (role_guide_filename or "").strip()
    if name in _GUIDE_TO_ROLE:
        return _GUIDE_TO_ROLE[name]
    # Fallback: try to normalize common names
    upper = name.upper()
    for k, v in _GUIDE_TO_ROLE.items():
        if upper == k.upper():
            return v
    return "PM"

def normalize_role_name(raw: str) -> str:
    s = (raw or "").strip()
    if s == "":
        return ""
    u = s.upper()
    # Common canonical names
    if u in ("PM", "PRODUCT MANAGER", "PRODUCT"):
        return "PM"
    if u.startswith("TECH LEAD") or u.startswith("ARCHITECT") or "DELIVERY LEAD" in u:
        return "TECH_LEAD"
    if u.startswith("TECH WRITER") or u.startswith("DOCUMENTATION"):
        return "TECH_WRITER"
    if u.startswith("QA") or "QUALITY" in u:
        return "QA"
    if u.startswith("DEVOPS") or "PLATFORM" in u:
        return "DEVOPS"
    if u.startswith("FRONTEND") or u == "FE":
        return "FE"
    if u.startswith("BUILDER") or u == "BUILDER" or "FULLSTACK" in u:
        return "BUILDER"
    if u.startswith("BACKEND") or u == "BE":
        return "BE"
    if u.startswith("CODE REVIEW") or u.startswith("REVIEWER"):
        return "REVIEWER"
    # Try to match tokens like "Tech Lead (Architecture / Delivery Lead)"
    if "PM" == u:
        return "PM"
    if "TECH LEAD" in u:
        return "TECH_LEAD"
    if "TECH WRITER" in u:
        return "TECH_WRITER"
    if "DEVOPS" in u:
        return "DEVOPS"
    if "FRONTEND" in u:
        return "FE"
    if "BUILDER" in u:
        return "BUILDER"
    if "BACKEND" in u:
        return "BE"
    if "REVIEW" in u:
        return "REVIEWER"
    if "QA" in u:
        return "QA"
    return u.replace(" ", "_")

def model_for_role(role: str, role_map: dict) -> str:
    r = (role or "").strip().upper()
    roles = role_map.get("roles", {})
    if r in roles and isinstance(roles[r], dict) and roles[r].get("model"):
        return str(roles[r]["model"])
    if r in ("FE", "BE", "REVIEWER", "BUILDER"):
        return DEFAULT_CODE_MODEL
    return DEFAULT_ROLE_MODEL

def endpoint_base(role_map: dict) -> str:
    base = role_map.get("endpoint_base")
    if base:
        return str(base)
    return DEFAULT_ENDPOINT_BASE
