"""Single canonical stub installer for the agent tests (audit 2026-08-05, TS-03).

Five test files used to carry their own ``_install_stubs`` guarded by
``sys.modules.setdefault``: only the first imported file's stub actually
installed, the other copies were dead code, and one copy declared START/END as
bare strings while the others used ``_Sentinel(str)`` - so a file rename could
silently change which contract the agent code loads against. This module is the
ONE version of the stub surface: ``dataiku`` (api_client, Dataset,
SQLExecutor2), ``dataiku.llm.python.BaseLLM``,
``dataiku.llm.agent_tools.BaseAgentTool`` and a ``langgraph`` import surface
with ``_Sentinel`` START/END (the graph is never run in these tests).

Not collected by unittest discovery (the filename does not match ``test*.py``).
"""

import importlib.util
import sys
import types


class _Sentinel(str):
    pass


def install():
    """Install the canonical stub modules; idempotent (existing modules win)."""
    if "dataiku" not in sys.modules:
        dataiku_mod = types.ModuleType("dataiku")
        dataiku_mod.api_client = lambda: None
        dataiku_mod.Dataset = lambda *a, **k: None
        dataiku_mod.SQLExecutor2 = lambda *a, **k: None
        sys.modules["dataiku"] = dataiku_mod
    else:
        dataiku_mod = sys.modules["dataiku"]

    if "dataiku.llm" not in sys.modules:
        llm_pkg = types.ModuleType("dataiku.llm")
        sys.modules["dataiku.llm"] = llm_pkg
        dataiku_mod.llm = llm_pkg
    else:
        llm_pkg = sys.modules["dataiku.llm"]

    if "dataiku.llm.python" not in sys.modules:
        llm_python = types.ModuleType("dataiku.llm.python")

        class BaseLLM(object):
            pass

        llm_python.BaseLLM = BaseLLM
        llm_pkg.python = llm_python
        sys.modules["dataiku.llm.python"] = llm_python

    if "dataiku.llm.agent_tools" not in sys.modules:
        agent_tools = types.ModuleType("dataiku.llm.agent_tools")

        class BaseAgentTool(object):
            pass

        agent_tools.BaseAgentTool = BaseAgentTool
        llm_pkg.agent_tools = agent_tools
        sys.modules["dataiku.llm.agent_tools"] = agent_tools

    if "langgraph" not in sys.modules:
        lg = types.ModuleType("langgraph")
        lg_graph = types.ModuleType("langgraph.graph")
        lg_graph.START = _Sentinel("__start__")
        lg_graph.END = _Sentinel("__end__")

        class _StateGraph(object):
            def __init__(self, *a, **k):
                pass

            def add_node(self, *a, **k):
                pass

            def add_edge(self, *a, **k):
                pass

            def add_conditional_edges(self, *a, **k):
                pass

            def compile(self, *a, **k):
                return self

            def stream(self, *a, **k):
                return iter(())

        lg_graph.StateGraph = _StateGraph
        lg_config = types.ModuleType("langgraph.config")
        lg_config.get_stream_writer = lambda: (lambda *a, **k: None)
        lg.graph = lg_graph
        lg.config = lg_config
        sys.modules["langgraph"] = lg
        sys.modules["langgraph.graph"] = lg_graph
        sys.modules["langgraph.config"] = lg_config
