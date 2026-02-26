import json
import os
import time
import urllib.error
import urllib.request

# Gemini API (API key) REST endpoint.
# Docs: https://ai.google.dev/api/generate-content

DEFAULT_ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-pro"

def _endpoint_for_model(model: str, endpoint_base: str) -> str:
    base = (endpoint_base or DEFAULT_ENDPOINT_BASE).rstrip("/")
    return base + "/models/" + model + ":generateContent"

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default

def _extract_text_from_response(data: dict) -> str:
    cands = data.get("candidates")
    if not isinstance(cands, list) or not cands:
        return ""
    c0 = cands[0]
    content = c0.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        return ""
    texts = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        # If includeThoughts is enabled, thought summaries can appear with thought=true.
        if p.get("thought") is True:
            continue
        t = p.get("text")
        if isinstance(t, str) and t.strip() != "":
            texts.append(t)
    if texts:
        return "\n".join(texts)
    # Fallback: if only thought parts exist, return any text so caller can decide.
    for p in parts:
        if isinstance(p, dict) and isinstance(p.get("text"), str):
            return str(p.get("text"))
    return ""

def call_gemini(api_key: str, prompt: str, timeout_s: int = 240, model: str | None = None, endpoint_base: str | None = None) -> str:
    if not api_key:
        raise RuntimeError("gemini api key is missing")

    use_model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    use_endpoint_base = endpoint_base or os.environ.get("GEMINI_ENDPOINT_BASE") or DEFAULT_ENDPOINT_BASE
    url = _endpoint_for_model(use_model, use_endpoint_base)

    # Controls
    # - Set maxOutputTokens high by default, but allow removing the limit by setting FD_GEMINI_MAX_OUTPUT_TOKENS=0.
    # - Set thinkingBudget to avoid the model consuming the entire output budget on thoughts.
    max_out = _env_int("FD_GEMINI_MAX_OUTPUT_TOKENS", 8192)
    think_budget = _env_int("FD_GEMINI_THINKING_BUDGET", 1024)
    retries = _env_int("FD_GEMINI_RETRIES", 2)

    def _make_payload(max_output_tokens: int, thinking_budget: int) -> dict:
        gen = {
            "temperature": 0.2,
            "responseMimeType": os.environ.get("FD_GEMINI_RESPONSE_MIME", "text/plain"),
            "thinkingConfig": {
                "includeThoughts": False,
                "thinkingBudget": thinking_budget,
            },
        }
        if max_output_tokens > 0:
            gen["maxOutputTokens"] = max_output_tokens
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen,
        }

    last_raw = ""
    last_err = ""
    for attempt in range(1, retries + 1):
        # Attempt 1: configured values.
        # Attempt 2+: aggressively disable thinking and remove output limit to avoid empty-part responses.
        if attempt == 1:
            payload = _make_payload(max_out, think_budget)
            use_timeout = timeout_s
        else:
            payload = _make_payload(0, 0)
            use_timeout = max(timeout_s, 600)

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url=url, data=body, method="POST")
        req.add_header("content-type", "application/json; charset=utf-8")
        req.add_header("x-goog-api-key", api_key)

        try:
            with urllib.request.urlopen(req, timeout=use_timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                last_raw = raw
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            snippet = err_body[:800]
            raise RuntimeError("gemini request failed http=" + str(e.code) + " model=" + use_model + " url=" + url + " body=" + snippet)
        except Exception as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
                continue
            raise

        data = json.loads(last_raw)
        text = _extract_text_from_response(data)
        if text.strip() != "":
            return text

        # Empty text: if model hit MAX_TOKENS and produced no parts, retry with thinking disabled and no maxOutputTokens.
        finish = ""
        try:
            finish = str(data.get("candidates", [{}])[0].get("finishReason", ""))
        except Exception:
            finish = ""
        if attempt < retries and finish == "MAX_TOKENS":
            last_err = "empty text with finishReason=MAX_TOKENS"
            continue

        raise RuntimeError("gemini response parse failed model=" + use_model + " url=" + url + " raw=" + last_raw[:800] + " err=" + last_err)

    raise RuntimeError("gemini response parse failed model=" + use_model + " url=" + url + " raw=" + last_raw[:800] + " err=" + last_err)
