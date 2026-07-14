import json
import os

from frontforge.agents.planner_agent import PlannerAgent
from frontforge.agents.component_agent import ComponentAgent
from frontforge.agents.package_manager_agent import PackageManagerAgent

PLAN_OUTPUT_PATH = os.path.join("generated_project", "plan.json")


def run(requirement: str, model: str = "qwen2.5:3b") -> None:
    planner = PlannerAgent(model=model)
    component_agent = ComponentAgent(model=model)

    print("\n[Planner Agent] Generating project plan...")
    plan = planner.plan(requirement)

    os.makedirs(os.path.dirname(PLAN_OUTPUT_PATH), exist_ok=True)
    with open(PLAN_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(plan.model_dump(), f, indent=2)
    print(f"[Planner Agent] Plan saved to {PLAN_OUTPUT_PATH}")
    print(f"[Planner Agent] Pages: {[p.name for p in plan.pages]}")
    print(f"[Planner Agent] Components: {[c.name for c in plan.components]}")

    print("\n[Component Agent] Generating component files...")
    
    for component in plan.components:
        print(f"  - generating {component.name}...")
        generated = component_agent.generate(component, plan)
        path = component_agent.write_to_disk(generated)
        print(f"    written to {path}")

    print("\n[Package Manager Agent] Writing package.json...")
    package_manager = PackageManagerAgent()
    manifest_path = package_manager.generate(plan)
    print(f"[Package Manager Agent] Written to {manifest_path}")

    print("[Package Manager Agent] Writing Vite scaffold + pages/App.jsx...")
    scaffold_paths = package_manager.scaffold(plan)
    for path in scaffold_paths:
        print(f"  - {path}")

    print("[Package Manager Agent] Running npm install...")
    try:
        result = package_manager.install()
        if result.returncode == 0:
            print("[Package Manager Agent] npm install succeeded.")
        else:
            print(
                "[Package Manager Agent] npm install failed "
                f"(exit code {result.returncode}). stderr:\n{result.stderr}"
            )
    except FileNotFoundError as e:
        print(f"[Package Manager Agent] Skipped install: {e}")

    print("\nDone. Project plan + components + package.json are under 'generated_project/'.")


if __name__ == "__main__":
    user_requirement = input("Describe the app you want FrontForge AI to build:\n> ")
    run(user_requirement)