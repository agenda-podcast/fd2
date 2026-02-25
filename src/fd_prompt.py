import os
from typing import List

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def build_prompt(agent_guides_dir: str, role_guide_file: str, wi_path: str) -> str:
    parts: List[str] = []
    parts.append(read_text(os.path.join(agent_guides_dir, "GLOBAL_CONSTRAINTS.txt")))
    parts.append(read_text(os.path.join(agent_guides_dir, "ARTIFACT_CONTRACT.txt")))
    parts.append(read_text(os.path.join(agent_guides_dir, "OUTPUT_MODE.txt")))
    parts.append(read_text(os.path.join(agent_guides_dir, role_guide_file)))
    parts.append("WORK ITEM FILE (EXECUTE THIS):")
    parts.append(read_text(wi_path))
    parts.append("RETURN STRICT OUTPUT MODE ONLY.")
    return "\n\n".join(parts)
