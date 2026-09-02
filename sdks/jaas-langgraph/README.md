# jaas-langgraph

LangGraph tool adapter for the JaaS skill registry. Wraps `jaas-client` to
expose two real LangChain-core tools (LangGraph's `ToolNode` and prebuilt
agents consume `langchain_core.tools.BaseTool` instances directly):

```python
from jaas_client import JaasRegistryClient
from jaas_langgraph import build_jaas_tools

client = JaasRegistryClient("https://registry.example.com", token="<PAT>")
tools = build_jaas_tools(client)  # [search_skills, get_skill] -- BaseTool instances
```
