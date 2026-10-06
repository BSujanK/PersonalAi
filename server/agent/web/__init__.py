"""Web tools: ``web_search`` (Tavily), ``web_read`` and ``hf_models`` (Hugging Face).

These are the only code paths that send text derived from the owner's conversation to the
internet, so each layer is deliberately narrow: the model's arguments are checked for personal
data before they leave (``guard``), ``web_read`` can only fetch URLs ``web_search`` returned in the
same turn, every URL is public https on port 443 (``urls``), and everything that comes back is
size-capped, flattened to text and treated as untrusted data (CLAUDE.md rules 3 and 4).
"""
