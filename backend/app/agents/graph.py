"""The agent pipeline as a LangGraph state graph.

LangGraph runs a graph of "nodes" (our agents and tools) that pass a shared *state*
along the edges. Our state is a single `MangaProject`. Every node:
  1. skips itself if its output is already in the project (that's how resume works),
  2. does its work (an LLM agent, image generation, layout...),
  3. saves project.json, so a crash or a pause loses nothing.

A conditional edge after the character sheets either continues to panel generation
(cast approved, or auto-approve) or ends the run with status "awaiting_approval";
approving the cast in the UI re-queues the job and it resumes from disk.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..providers.base import ImageProvider, LLMProvider
from .runner import AgentFailed
from .state import MangaProject

log = logging.getLogger("manga.graph")

# Progress stages shown in the UI, in order.
STAGES = ["writer", "director", "characters", "sheets", "approval", "prompts", "panels",
          "consistency", "layout", "export"]

ProgressFn = Callable[[str, float, str], None]


@dataclass
class Ctx:
    """Things nodes need that are not part of the saved state."""

    settings: Settings
    llm: LLMProvider
    image: ImageProvider
    job_dir: Path
    progress: ProgressFn = lambda stage, fraction, message: None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def prices(self) -> tuple[float | None, float | None]:
        return (self.settings.llm_input_price, self.settings.llm_output_price)


class GraphState(TypedDict):
    project: MangaProject


@dataclass
class Node:
    name: str
    stage: str
    label: str
    run: Callable[[MangaProject, Ctx], None]
    done: Callable[[MangaProject], bool]


def _wrap(node: Node, ctx: Ctx) -> Callable[[GraphState], GraphState]:
    def run(state: GraphState) -> GraphState:
        project = state["project"]
        if node.done(project):
            ctx.progress(node.stage, 1.0, f"{node.label}: done earlier (resumed)")
            return {"project": project}
        ctx.progress(node.stage, 0.0, node.label)
        started = time.monotonic()
        try:
            node.run(project, ctx)
        except AgentFailed as exc:
            project.add_step(exc.step)  # keep the failed attempts visible in the timeline
            project.save(ctx.job_dir)
            raise
        project.timings[node.name] = round(time.monotonic() - started, 3)
        project.save(ctx.job_dir)
        ctx.progress(node.stage, 1.0, f"{node.label}: done")
        return {"project": project}

    return run


def build_graph(nodes: list[Node], ctx: Ctx, gate_after: str | None = None,
                gate: Callable[[MangaProject], bool] | None = None):
    """Chain the nodes in order. If `gate_after` is set, `gate(project)` decides whether to
    continue after that node or stop (pause) the run."""
    builder = StateGraph(GraphState)
    for node in nodes:
        builder.add_node(node.name, _wrap(node, ctx))
    builder.add_edge(START, nodes[0].name)
    for a, b in zip(nodes, nodes[1:]):
        if gate_after == a.name and gate is not None:
            builder.add_conditional_edges(a.name, lambda s: "go" if gate(s["project"]) else "stop",
                                          {"go": b.name, "stop": END})
        else:
            builder.add_edge(a.name, b.name)
    builder.add_edge(nodes[-1].name, END)
    return builder.compile()


def run_graph(project: MangaProject, nodes: list[Node], ctx: Ctx, gate_after: str | None = None,
              gate: Callable[[MangaProject], bool] | None = None) -> MangaProject:
    graph = build_graph(nodes, ctx, gate_after, gate)
    result = graph.invoke({"project": project}, {"recursion_limit": 100})
    return result["project"]
