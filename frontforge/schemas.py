"""
Shared data contracts between agents.

The Planner Agent's job is to produce a ProjectPlan. The Component Agent's
job is to consume one ComponentSpec at a time (plus the surrounding plan for
context) and emit JSX/TSX code. Keeping this in one schemas.py file means
both agents agree on the exact same shape without duplicating field names.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ComponentSpec(BaseModel):
    name: str = Field(..., description="PascalCase component name, e.g. 'NavBar'")
    type: str = Field(
        ...,
        description="One of: 'layout', 'page', 'ui', 'form', 'chart'. "
        "Helps the Component Agent choose sensible defaults.",
    )
    description: str = Field(..., description="What this component renders/does")
    props: List[str] = Field(
        default_factory=list,
        description="Prop names this component accepts, e.g. ['title', 'items']",
    )
    used_in_pages: List[str] = Field(
        default_factory=list, description="Which pages import/use this component"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="Other component names this one imports (children, siblings)",
    )


class PageSpec(BaseModel):
    name: str = Field(..., description="PascalCase page name, e.g. 'Dashboard'")
    route: str = Field(..., description="React Router path, e.g. '/dashboard'")
    description: str = Field(..., description="Purpose/content of this page")
    components: List[str] = Field(
        default_factory=list, description="Component names rendered on this page"
    )


class ProjectPlan(BaseModel):
    project_name: str
    framework: str = Field(default="React (Vite)", description="Target framework")
    styling: str = Field(default="Tailwind CSS", description="Styling approach")
    summary: str = Field(..., description="One paragraph summary of the app")
    dependencies: List[str] = Field(
        default_factory=list,
        description="npm packages required, e.g. ['react-router-dom', 'recharts']",
    )
    pages: List[PageSpec] = Field(default_factory=list)
    components: List[ComponentSpec] = Field(default_factory=list)


class GeneratedComponent(BaseModel):
    name: str
    filename: str
    code: str
