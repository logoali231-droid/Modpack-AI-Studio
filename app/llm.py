"""Adapters for Ollama, OpenAI Responses API, and Google Gemini."""
import json, os, re
import requests

# Ollama's default context window is small (a few thousand tokens). Long prompts are
# then silently truncated from the start, which can drop the system prompt itself.
DEFAULT_NUM_CTX = 8192


class LLMClient:
    def __init__(self, provider, key, model, log, base_url="http://localhost:11434", num_ctx=None):
        self.provider, self.key, self.model, self.log = provider, key, model, log
        self.base_url = base_url.rstrip("/")
        self.num_ctx = int(num_ctx or os.environ.get("MODPACK_AI_NUM_CTX") or DEFAULT_NUM_CTX)
        self.session = requests.Session()

    def text(self, system, user):
        self.log(f"AI: contacting {self.provider} ({self.model})")
        try:
            if self.provider == "OpenAI":
                r = self.session.post("https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={"model": self.model, "instructions": system, "input": user}, timeout=(15,180))
                self._check(r); data = r.json()
                result = "\n".join(c.get("text","") for o in data.get("output",[])
                    for c in o.get("content",[]) if c.get("type") == "output_text")
            elif self.provider == "Google Gemini":
                r = self.session.post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self.key},
                    json={"systemInstruction":{"parts":[{"text":system}]},
                          "contents":[{"parts":[{"text":user}]}],
                          "generationConfig":{"temperature":0.25,"responseMimeType":"application/json"}}, timeout=(15,180))
                self._check(r); data = r.json()
                result = "\n".join(p.get("text","") for p in data["candidates"][0]["content"]["parts"])
            else:
                r = self.session.post(f"{self.base_url}/api/chat",
                    json={"model":self.model,"stream":False,"format":"json",
                          "options":{"num_ctx":self.num_ctx,"temperature":0.25},
                          "messages":[{"role":"system","content":system},{"role":"user","content":user}]}, timeout=(10,300))
                self._check(r); result = r.json().get("message",{}).get("content","")
        except requests.Timeout as e: raise RuntimeError(f"{self.provider} timed out: {e}") from e
        except requests.RequestException as e: raise RuntimeError(f"{self.provider} connection failed: {e}") from e
        if not result.strip(): raise RuntimeError(f"{self.provider} returned an empty response.")
        return result

    @staticmethod
    def _check(response):
        if not response.ok:
            try: detail = response.json().get("error",{}).get("message",response.text[:300])
            except Exception: detail = response.text[:300]
            raise RuntimeError(f"API error {response.status_code}: {detail}")

    @staticmethod
    def json_from(text):
        cleaned = re.sub(r"^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$", "", text.strip(), flags=re.I)
        try: return json.loads(cleaned)
        except json.JSONDecodeError:
            start = next((i for i,c in enumerate(cleaned) if c in "[{"), None)
            if start is None: raise ValueError("AI response did not contain JSON.")
            opening=cleaned[start]; closing="]" if opening=="[" else "}"; depth=0; quoted=False; escaped=False
            for i,c in enumerate(cleaned[start:],start):
                if quoted:
                    if escaped: escaped=False
                    elif c=="\\": escaped=True
                    elif c=='"': quoted=False
                elif c=='"': quoted=True
                elif c==opening: depth+=1
                elif c==closing:
                    depth-=1
                    if depth==0: return json.loads(cleaned[start:i+1])
            raise ValueError("AI response contained incomplete JSON.")


