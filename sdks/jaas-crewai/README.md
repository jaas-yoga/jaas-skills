# jaas-crewai

CrewAI tool adapter for the JaaS skill registry. Wraps `jaas-client` to
expose two real `crewai.tools.BaseTool` instances that a CrewAI `Agent` can
use directly:

```python
from jaas_client import JaasRegistryClient
from jaas_crewai import build_jaas_tools

client = JaasRegistryClient("https://registry.example.com", token="<PAT>")
tools = build_jaas_tools(client)  # [SearchSkillsTool(), GetSkillTool()]
```
