import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-pro"

def _env_int(name: str, default: int) -> int:
    v = (os.environ.get(name) or "").strip()
    if v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default

def _endpoint(base: str, model: str) -> str:
    b = (base or DEFAULT_ENDPOINT).rstrip("/")
    return b + "/models/" + model + ":generateContent"

def call_gemini(prompt: str, timeout_s: int = 900) -> str:
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if api_key == "":
        raise RuntimeError("FD_FAIL: missing GEMINI_API_KEY")
    model = (os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL).strip()
    base = (os.environ.get("GEMINI_ENDPOINT_BASE") or DEFAULT_ENDPOINT).strip()
    url = _endpoint(base, model)

    retries = _env_int("FD_GEMINI_RETRIES", 2)
    think_budget = _env_int("FD_GEMINI_THINKING_BUDGET", 0)
    max_out = _env_int("FD_GEMINI_MAX_OUTPUT_TOKENS", 0)  # 0 => omit
    resp_mime = (os.environ.get("FD_GEMINI_RESPONSE_MIME") or "text/plain").strip()

    def payload() -> dict:
        gen = {
            "temperature": 0.2,
            "responseMimeType": resp_mime,
            "thinkingConfig": {"includeThoughts": False, "thinkingBudget": think_budget},
        }
        if max_out > 0:
            gen["maxOutputTokens"] = max_out
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}

    last_raw = ""
    for attempt in range(1, retries + 1):
        body = json.dumps(payload()).encode("utf-8")
        req = urllib.request.Request(url=url, data=body, method="POST")
        req.add_header("content-type", "application/json; charset=utf-8")
        req.add_header("x-goog-api-key", api_key)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                last_raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            b = ""
            try:
                b = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError("FD_FAIL: gemini http=" + str(e.code) + " body=" + b[:800])
        except Exception:
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
                continue
            raise

        data = json.loads(last_raw)
        cands = data.get("candidates") or []
        if isinstance(cands, list) and cands:
            c0 = cands[0]
            content = c0.get("content") if isinstance(c0, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                texts = []
                for p in parts:
                    if isinstance(p, dict) and isinstance(p.get("text"), str):
                        texts.append(p["text"])
                if texts:
                    return "\n".join(texts)
        # allow retry if no parts
        if attempt < retries:
            continue
        raise RuntimeError("FD_FAIL: gemini parse raw=" + last_raw[:800])
