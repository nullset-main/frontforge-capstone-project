"""
Planner Agent

Takes a natural language requirement and returns a ProjectPlan (pages,
components, routing, dependencies). This is the first step of the
sequential pipeline: Planner -> ... -> Component Agent.

No LangGraph is used here on purpose (per project constraints) - this is a
plain LangChain LCEL chain: prompt | llm | parser, with one retry that
repairs common small-model JSON mistakes (markdown fences, trailing commas).
"""

import json
import re

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

from frontforge.llm import get_llm
from frontforge.schemas import ProjectPlan
from frontforge.prompts.planner_prompt import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_USER_PROMPT,
)


class PlannerAgent:
    def __init__(self, model: str = "qwen2.5:3b"):
        self.llm = get_llm(model=model, temperature=0.2)
        self.parser = PydanticOutputParser(pydantic_object=ProjectPlan)

        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PLANNER_SYSTEM_PROMPT),
                ("human", PLANNER_USER_PROMPT),
            ]
        ).partial(format_instructions=self.parser.get_format_instructions())

        self.chain = self.prompt | self.llm

    @staticmethod
    def _clean_json(raw_text: str) -> str:
        """
        Small local models frequently wrap JSON in ```json fences or add a
        stray sentence before/after. Strip that so the parser has a clean
        shot at it.
        """
        text = raw_text.strip()
        text = re.sub(r"^```(json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

        # If there's leading/trailing prose, grab the outermost {...} block.
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            text = text[first : last + 1]
        return text

    def plan(self, requirement: str) -> ProjectPlan:
        response = self.chain.invoke({"requirement": requirement})
        raw = response.content if hasattr(response, "content") else str(response)
        cleaned = self._clean_json(raw)

        try:
            return self.parser.parse(cleaned)
        except Exception as first_error:
            # One repair attempt: ask the same model to fix its own JSON.
            repair_prompt = (
                "The following text should be valid JSON matching this schema "
                f"but failed to parse with error: {first_error}\n\n"
                f"Schema:\n{self.parser.get_format_instructions()}\n\n"
                f"Text to fix:\n{cleaned}\n\n"
                "Return ONLY the corrected JSON, nothing else."
            )
            repaired = self.llm.invoke(repair_prompt)
            repaired_text = self._clean_json(
                repaired.content if hasattr(repaired, "content") else str(repaired)
            )
            return self.parser.parse(repaired_text)


if __name__ == "__main__":
    agent = PlannerAgent()
    plan = agent.plan(
        "A simple admin dashboard with a sidebar, a topbar, a stats "
        "overview page with 3 charts, and a users table page."
    )
    print(json.dumps(plan.model_dump(), indent=2))
