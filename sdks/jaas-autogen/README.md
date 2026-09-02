# jaas-autogen

AutoGen tool adapter for the JaaS skill registry (targets the current
`autogen-core`/`autogen-agentchat` packages, not the legacy `pyautogen`/
AG2 fork). Wraps `jaas-client` to expose two real
`autogen_core.tools.FunctionTool` instances an AutoGen agent's `tools` list
can use directly:

```python
from jaas_client import JaasRegistryClient
from jaas_autogen import build_jaas_tools

client = JaasRegistryClient("https://registry.example.com", token="<PAT>")
tools = build_jaas_tools(client)  # [FunctionTool(search_skills), FunctionTool(get_skill)]
```
