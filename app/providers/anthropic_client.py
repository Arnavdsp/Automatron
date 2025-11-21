
class AnthropicProvider:
    def __init__(self, api_key, model='claude-3-5-sonnet-20241022'):
        self.api_key = api_key
        self.model = model

    def complete(self, messages, max_tokens=1024):
        import httpx
        headers = {'x-api-key': self.api_key, 'anthropic-version': '2023-06-01'}
        payload = {'model': self.model, 'messages': messages, 'max_tokens': max_tokens}
        r = httpx.post('https://api.anthropic.com/v1/messages',
                       json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
