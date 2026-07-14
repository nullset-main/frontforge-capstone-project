"""
Component Agent

Takes one ComponentSpec (produced by the Planner Agent) plus the surrounding
ProjectPlan for context, and generates the actual .jsx source code for that
component. Also responsible for writing the file to disk under
generated_project/src/components/.

A rag_context string can optionally be passed in (this is where the RAG
pipeline described in the assignment would plug in later - retrieved React /
Tailwind / Recharts doc snippets get inserted here as plain text). It is
left empty by default so this agent works standalone right now.
"""

import os
import re

from langchain_core.prompts import ChatPromptTemplate

from frontforge.llm import get_llm
from frontforge.schemas import ComponentSpec, ProjectPlan, GeneratedComponent
from frontforge.prompts.component_prompt import (
    COMPONENT_SYSTEM_PROMPT,
    COMPONENT_USER_PROMPT,
)

OUTPUT_DIR = os.path.join("generated_project", "src", "components")


class ComponentAgent:
    def __init__(self, model: str = "qwen2.5:3b"):
        self.llm = get_llm(model=model, temperature=0.3)

        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", COMPONENT_SYSTEM_PROMPT),
                ("human", COMPONENT_USER_PROMPT),
            ]
        )
        self.chain = self.prompt | self.llm

    @staticmethod
    def _clean_code(raw_text: str) -> str:
        """Strip markdown code fences small models tend to add anyway."""
        text = raw_text.strip()
        text = re.sub(r"^```(jsx|tsx|javascript|js)?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"```$", "", text)
        return text.strip() + "\n"

    def generate(
        self,
        component: ComponentSpec,
        plan: ProjectPlan,
        rag_context: str = "",
    ) -> GeneratedComponent:
        sibling_names = [c.name for c in plan.components if c.name != component.name]

        response = self.chain.invoke(
            {
                "project_name": plan.project_name,
                "styling": plan.styling,
                "framework": plan.framework,
                "sibling_components": ", ".join(sibling_names) or "none",
                "rag_context": rag_context or "(none provided)",
                "name": component.name,
                "type": component.type,
                "description": component.description,
                "props": ", ".join(component.props) or "none",
                "depends_on": ", ".join(component.depends_on) or "none",
            }
        )
        raw = response.content if hasattr(response, "content") else str(response)
        code = self._clean_code(raw)
        filename = f"{component.name}.jsx"

        return GeneratedComponent(name=component.name, filename=filename, code=code)

    @staticmethod
    def write_to_disk(generated: GeneratedComponent, output_dir: str = OUTPUT_DIR) -> str:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, generated.filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(generated.code)
        return path


if __name__ == "__main__":
    from frontforge.schemas import PageSpec

    demo_plan = ProjectPlan(
        project_name="DemoDashboard",
        summary="A demo admin dashboard.",
        dependencies=["react-router-dom"],
        pages=[PageSpec(name="Dashboard", route="/", description="Main page", components=["StatsCard"])],
        components=[
            ComponentSpec(
                name="StatsCard",
                type="ui",
                description="A card showing a single KPI number with a label and trend arrow.",
                props=["label", "value", "trend"],
            )
        ],
    )
    agent = ComponentAgent()
    result = agent.generate(demo_plan.components[0], demo_plan)
    print(result.code)
