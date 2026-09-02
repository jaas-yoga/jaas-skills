# jaas-client

Thin Python client for the [JaaS](https://github.com/jaas-yoga) skill
registry REST API — search, read metadata, and pull a published skill's
files. No framework-specific behavior lives here; see the sibling
`jaas-langgraph`, `jaas-crewai`, and `jaas-autogen` packages for adapters
that expose registry skills as tools in each framework's own conventions.

```python
from jaas_client import JaasRegistryClient

client = JaasRegistryClient("https://registry.example.com", token="<PAT>")
results = client.search(query="summarizer")
files = client.pull(results[0].id, "latest")
```
