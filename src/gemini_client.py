import json
import urllib.request
from typing import Optional

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent"

def call_gemini(api_key: str, prompt: str, timeout_s: int = 120) -> str:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192
        }
    }
    url = GEMINI_ENDPOINT + "?key=" + api_key
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8")
    obj = json.loads(body)
    # Extract text parts only; strict mode should output a single JSON object as text.
    cand = obj.get("candidates", [])
    if not cand:
        raise RuntimeError("gemini: no candidates")
    content = cand[0].get("content", {})
    parts = content.get("parts", [])
    texts = []
    for p in parts:
        t = p.get("text")
        if isinstance(t, str):
            texts.append(t)
    out = "".join(texts).strip()
    if out == "":
        raise RuntimeError("gemini: empty output")
    return out
