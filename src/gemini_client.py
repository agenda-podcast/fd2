import json
import os
import urllib.error
import urllib.request

# Gemini API (API key) REST endpoint.
# Model list: https://ai.google.dev/gemini-api/docs/models
# Docs: https://ai.google.dev/api/generate-content

DEFAULT_ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-pro"

def _endpoint_for_model(model: str, endpoint_base: str) -> str:
    base = (endpoint_base or DEFAULT_ENDPOINT_BASE).rstrip("/")
    return base + "/models/" + model + ":generateContent"

def call_gemini(api_key: str, prompt: str, timeout_s: int = 240, model: str | None = None, endpoint_base: str | None = None) -> str:
    if not api_key:
        raise RuntimeError("gemini api key is missing")

    use_model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    use_endpoint_base = endpoint_base or os.environ.get("GEMINI_ENDPOINT_BASE") or DEFAULT_ENDPOINT_BASE

    url = _endpoint_for_model(use_model, use_endpoint_base)

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method="POST")
    req.add_header("content-type", "application/json; charset=utf-8")
    # Preferred: send API key via header (avoids logging it in URLs).
    req.add_header("x-goog-api-key", api_key)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        snippet = err_body[:800]
        raise RuntimeError("gemini request failed http=" + str(e.code) + " model=" + use_model + " url=" + url + " body=" + snippet)

    data = json.loads(raw)
    # Gemini responses are structured; we only need the first candidate's first text part.
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError("gemini response parse failed model=" + use_model + " url=" + url + " raw=" + raw[:800])
