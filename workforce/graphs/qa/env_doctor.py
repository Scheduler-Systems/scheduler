"""env_doctor: report which deployment env vars exist (LENGTHS only, never values)."""
import os
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
_WATCH = ["GITHUB_APP_ID","FLEET_APP_ID","GITHUB_APP_PRIVATE_KEY","GITHUB_APP_PRIVATE_KEY_B64",
          "GITHUB_APP_PRIVATE_KEY_GZ_B64","GITHUB_TOKEN","GEMINI_API_KEY","GOOGLE_API_KEY"]
class S(TypedDict, total=False):
    present: dict
def check(state: S) -> dict:
    return {"present": {k: (len(os.environ.get(k,"")) ) for k in _WATCH}}
builder = StateGraph(S); builder.add_node("check", check)
builder.add_edge(START, "check"); builder.add_edge("check", END)
graph = builder.compile()
