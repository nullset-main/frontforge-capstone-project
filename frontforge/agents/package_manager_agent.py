"""
Package Manager Agent

Takes the ProjectPlan produced by the Planner Agent and turns
`plan.dependencies` (+ `plan.framework` / `plan.styling`) into a real
`package.json`, then (optionally) runs `npm install` against it.

It also writes the static Vite scaffolding a React project needs to
actually build and run: `index.html`, `vite.config.js`, `src/main.jsx`,
`src/index.css`, and (if styling is Tailwind) `tailwind.config.js` /
`postcss.config.js`. None of these depend on what the app is *about* - a
portfolio site and a dashboard need the exact same index.html - so they're
templated here rather than left to the Component Agent, which only knows
how to generate individual named components, not entry-point boilerplate.

This agent also stitches the Component Agent's output into something
`npm run build` can actually reach: a `src/App.jsx` (with react-router-dom
routing if there's more than one page) and one `src/pages/*.jsx` per page,
composed from `ComponentSpec.used_in_pages` on the plan. This is a stand-in
for what will eventually be the UI Architect Agent's job (page/route
composition) - it's here for now because without *something* rendering the
generated components, `npm run build` succeeds on an app that shows a blank
page, which defeats the point of a build check.

This agent is deliberately *not* an LLM call for any of this. All of the
above is deterministic templating from the ProjectPlan and the already
-generated component list, not a generation problem - asking a 3B local
model to hand-write JSON/JSX scaffolding here would just reintroduce the
exact parsing fragility the Planner Agent already has to work around, and
it would fail unpredictably right before the one thing (`npm run build`)
this whole phase is supposed to verify.

Output: generated_project/package.json, index.html, vite.config.js,
src/main.jsx, src/index.css, src/App.jsx, src/pages/*.jsx, and (if
Tailwind) tailwind.config.js + postcss.config.js. install() additionally
produces generated_project/node_modules/ + package-lock.json.
"""

import json
import os
import re
import subprocess

from frontforge.schemas import ProjectPlan

OUTPUT_DIR = "generated_project"

# Every project gets these regardless of what the Planner Agent listed,
# since a React app is non-functional without them.
BASE_DEPENDENCIES = ["react", "react-dom"]
BASE_DEV_DEPENDENCIES = ["vite", "@vitejs/plugin-react"]

# Pinned to reasonable current majors so output is stable/reproducible
# rather than always resolving to "latest".
VERSION_PINS = {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.1",
    "tailwindcss": "^3.4.10",
    "postcss": "^8.4.41",
    "autoprefixer": "^10.4.20",
    "recharts": "^2.12.7",
    "framer-motion": "^11.3.0",
    "styled-components": "^6.1.12",
    "clsx": "^2.1.1",
}
DEFAULT_VERSION = "latest"


class PackageManagerAgent:
    def __init__(self, output_dir: str = OUTPUT_DIR):
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # dependency resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _slugify(name: str) -> str:
        """PersonalPortfolio -> personal-portfolio (npm package names must
        be lowercase, no spaces)."""
        s = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
        s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
        return s or "frontforge-app"

    def _resolve_dependencies(self, plan: ProjectPlan) -> tuple[dict, dict]:
        deps = {name: VERSION_PINS.get(name, DEFAULT_VERSION) for name in BASE_DEPENDENCIES}
        dev_deps = {name: VERSION_PINS.get(name, DEFAULT_VERSION) for name in BASE_DEV_DEPENDENCIES}

        # Anything the Planner Agent listed. It sometimes forgets things
        # (e.g. leaves out react-router-dom even when pages have distinct
        # routes) so this is additive, not authoritative on its own.
        for dep in plan.dependencies:
            dep = dep.strip()
            if not dep:
                continue
            if dep in BASE_DEV_DEPENDENCIES or dep in ("tailwindcss", "postcss", "autoprefixer"):
                dev_deps[dep] = VERSION_PINS.get(dep, DEFAULT_VERSION)
            else:
                deps[dep] = VERSION_PINS.get(dep, DEFAULT_VERSION)

        # Fill in gaps the Planner Agent tends to leave: routing when
        # there's more than one distinct page route, Tailwind's build-time
        # deps when styling says Tailwind but only the runtime dep (if any)
        # was listed.
        if len({p.route for p in plan.pages}) > 1:
            deps.setdefault("react-router-dom", VERSION_PINS["react-router-dom"])

        if "tailwind" in plan.styling.lower():
            dev_deps.setdefault("tailwindcss", VERSION_PINS["tailwindcss"])
            dev_deps.setdefault("postcss", VERSION_PINS["postcss"])
            dev_deps.setdefault("autoprefixer", VERSION_PINS["autoprefixer"])

        # plan.dependencies is only a prediction the Planner Agent made
        # *before* any code existed - the Component Agent's LLM call isn't
        # constrained to honor it, and small local models routinely import
        # things nobody asked for (styled-components instead of Tailwind
        # classes is the recurring one). So the plan is not authoritative;
        # what the generated files actually `import` is. Reconcile against
        # that too, whenever there's already generated code on disk to scan.
        for pkg in self.scan_generated_imports():
            if pkg not in deps and pkg not in dev_deps:
                deps[pkg] = VERSION_PINS.get(pkg, DEFAULT_VERSION)

        return deps, dev_deps

    # ------------------------------------------------------------------
    # scanning already-generated code for real imports
    # ------------------------------------------------------------------

    _IMPORT_RE = re.compile(r"""import\s+(?:[^'";]+?\sfrom\s+)?['"]([^'"]+)['"]""")

    # Node/browser built-ins and relative paths never belong in dependencies.
    _IGNORED_IMPORTS = {"react", "react-dom"}  # already in BASE_DEPENDENCIES

    @classmethod
    def _package_name_from_import(cls, spec: str) -> str | None:
        if spec.startswith(".") or spec.startswith("/"):
            return None  # local file, not an npm package
        parts = spec.split("/")
        name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
        return None if name in cls._IGNORED_IMPORTS else name

    def scan_generated_imports(self) -> set:
        """Scans every .jsx/.tsx/.js/.ts file under <output_dir>/src for
        `import ... from 'package'` statements and returns the set of npm
        package names referenced. Relative imports (own components/pages)
        are excluded. Returns an empty set if src/ doesn't exist yet
        (e.g. Package Manager Agent run before the Component Agent)."""
        packages = set()
        src_dir = os.path.join(self.output_dir, "src")
        if not os.path.isdir(src_dir):
            return packages

        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                if not fname.endswith((".jsx", ".tsx", ".js", ".ts")):
                    continue
                path = os.path.join(root, fname)
                try:
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                except OSError:
                    continue
                for match in self._IMPORT_RE.finditer(content):
                    pkg = self._package_name_from_import(match.group(1))
                    if pkg:
                        packages.add(pkg)
        return packages

    # ------------------------------------------------------------------
    # package.json generation
    # ------------------------------------------------------------------

    def build_manifest(self, plan: ProjectPlan) -> dict:
        dependencies, dev_dependencies = self._resolve_dependencies(plan)

        return {
            "name": self._slugify(plan.project_name),
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview",
            },
            "dependencies": dict(sorted(dependencies.items())),
            "devDependencies": dict(sorted(dev_dependencies.items())),
        }

    def write_to_disk(self, manifest: dict) -> str:
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, "package.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        return path

    def generate(self, plan: ProjectPlan) -> str:
        """Build the manifest from the plan and write it to disk. Returns
        the path to the written package.json."""
        manifest = self.build_manifest(plan)
        return self.write_to_disk(manifest)

    # ------------------------------------------------------------------
    # static Vite scaffolding (index.html, config, entry point)
    # ------------------------------------------------------------------

    def _write(self, relative_path: str, content: str) -> str:
        path = os.path.join(self.output_dir, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def write_scaffold(self, plan: ProjectPlan) -> list[str]:
        """Writes index.html, vite.config.js, src/main.jsx, src/index.css,
        and Tailwind config (if applicable). Returns the list of paths
        written."""
        is_tailwind = "tailwind" in plan.styling.lower()
        written = []

        written.append(self._write(
            "index.html",
            f'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{plan.project_name}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
''',
        ))

        written.append(self._write(
            "vite.config.js",
            '''import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
''',
        ))

        written.append(self._write(
            os.path.join("src", "main.jsx"),
            '''import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
''',
        ))

        if is_tailwind:
            written.append(self._write(
                os.path.join("src", "index.css"),
                '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n',
            ))
            written.append(self._write(
                "tailwind.config.js",
                '''/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: { extend: {} },
  plugins: [],
}
''',
            ))
            written.append(self._write(
                "postcss.config.js",
                '''export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
''',
            ))
        else:
            written.append(self._write(
                os.path.join("src", "index.css"),
                '* { box-sizing: border-box; }\nbody { margin: 0; font-family: system-ui, sans-serif; }\n',
            ))

        return written

    # ------------------------------------------------------------------
    # page / App.jsx composition
    #
    # Stand-in for the future UI Architect Agent. Uses
    # ComponentSpec.used_in_pages (populated correctly by the Planner
    # Agent) rather than PageSpec.components (which the Planner Agent
    # currently tends to leave empty) to work out what each page renders.
    # ------------------------------------------------------------------

    @staticmethod
    def _pascal_case(name: str) -> str:
        parts = re.split(r"[^A-Za-z0-9]+", name)
        return "".join(p[:1].upper() + p[1:] for p in parts if p) or "Page"

    def write_pages_and_app(self, plan: ProjectPlan) -> list[str]:
        written = []
        pages_dir = os.path.join("src", "pages")
        use_router = len({p.route for p in plan.pages}) > 1

        page_component_names = []  # (page, PascalName)
        for page in plan.pages:
            component_names = [
                c.name for c in plan.components if page.name in (c.used_in_pages or [])
            ]
            pascal = self._pascal_case(page.name)
            page_component_names.append((page, pascal))

            imports = "\n".join(
                f"import {name} from '../components/{name}.jsx'" for name in component_names
            )
            body = "\n      ".join(f"<{name} />" for name in component_names) or (
                f"<p>{page.description}</p>"
            )

            page_src = f'''{imports}

export default function {pascal}() {{
  return (
    <>
      {body}
    </>
  )
}}
'''
            written.append(self._write(os.path.join(pages_dir, f"{pascal}.jsx"), page_src))

        if use_router:
            page_imports = "\n".join(
                f"import {pascal} from './pages/{pascal}.jsx'" for _, pascal in page_component_names
            )
            routes = "\n        ".join(
                f'<Route path="{page.route}" element={{<{pascal} />}} />'
                for page, pascal in page_component_names
            )
            app_src = f'''import {{ BrowserRouter, Routes, Route }} from 'react-router-dom'
{page_imports}

export default function App() {{
  return (
    <BrowserRouter>
      <Routes>
        {routes}
      </Routes>
    </BrowserRouter>
  )
}}
'''
        else:
            _, pascal = page_component_names[0]
            app_src = f'''import {pascal} from './pages/{pascal}.jsx'

export default function App() {{
  return <{pascal} />
}}
'''
        written.append(self._write(os.path.join("src", "App.jsx"), app_src))
        return written

    def scaffold(self, plan: ProjectPlan) -> list[str]:
        """Runs write_scaffold + write_pages_and_app together."""
        return self.write_scaffold(plan) + self.write_pages_and_app(plan)

    # ------------------------------------------------------------------
    # install step
    # ------------------------------------------------------------------

    def install(self, timeout: int = 600) -> subprocess.CompletedProcess:
        """Runs `npm install` inside self.output_dir. Raises FileNotFoundError
        with a clear message if npm isn't on PATH, rather than a raw
        OSError, since this is meant to run unattended."""
        try:
            return subprocess.run(
                ["npm", "install"],
                cwd=self.output_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                "npm was not found on PATH. Install Node.js/npm to let the "
                "Package Manager Agent run `npm install` automatically, or "
                "run it manually inside 'generated_project/'."
            ) from e


if __name__ == "__main__":
    from frontforge.schemas import PageSpec, ComponentSpec

    demo_plan = ProjectPlan(
        project_name="PersonalPortfolio",
        framework="React (Vite)",
        styling="Tailwind CSS",
        summary="A simple personal portfolio website.",
        dependencies=["react", "react-dom", "vite"],
        pages=[
            PageSpec(name="Home", route="/", description="Homepage", components=[]),
            PageSpec(name="About", route="/about", description="About page", components=[]),
            PageSpec(name="Projects", route="/projects", description="Projects page", components=[]),
        ],
        components=[
            ComponentSpec(name="Header", type="layout", description="Header"),
        ],
    )
    agent = PackageManagerAgent()
    written_path = agent.generate(demo_plan)
    print(f"Wrote {written_path}")
    with open(written_path) as f:
        print(f.read())