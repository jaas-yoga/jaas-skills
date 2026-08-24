"""Shared valid-document fixtures for validation tests."""

VALID_MANIFEST = {
    "apiVersion": "v1",
    "id": "acme.text.summarizer",
    "name": "Summarizer",
    "version": "1.2.3",
    "description": "Summarizes text",
    "owner": {"team": "platform", "contact": "platform@acme.com"},
    "entrypoint": "executor.py",
    "category": "nlp",
    "tags": ["summarization", "nlp"],
    "runtime": [{"family": "python", "versionRange": ">=3.10.0,<4.0.0"}],
}

VALID_IO_SCHEMA = {
    "inputs": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "outputs": {"type": "object", "properties": {"summary": {"type": "string"}}},
}

VALID_PERMISSIONS = ["fs:read", "network:egress"]

VALID_DEPENDENCIES = [{"id": "acme.util.tokenizer", "versionConstraint": ">=1.0.0,<2.0.0"}]
