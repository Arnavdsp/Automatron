
class GroqProvider:
    def __init__(self, api_key, model='llama3-70b-8192'):
        self.api_key = api_key
        self.model = model

    def complete(self, messages, stream=False):
        import httpx
        headers = {'Authorization': f'Bearer {self.api_key}'}
        payload = {'model': self.model, 'messages': messages, 'stream': stream}
        r = httpx.post('https://api.groq.com/openai/v1/chat/completions',
                       json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json() if not stream else r.iter_lines()

def _sanitise_error(msg: str) -> str:
    """Strip API keys from error strings before logging."""
    import re
    return re.sub(r'Bearer [A-Za-z0-9_\-\.]{20,}', 'Bearer [REDACTED]', msg)
