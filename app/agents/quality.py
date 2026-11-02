"""Quality Checker: deterministic rules (no AI, works offline) that decide pass / needs-revision for a script."""
from __future__ import annotations

import re

from app.agents.base import Agent, AgentResult, Brief
from app.agents.accuracy import script_flags
from app.scripts import parser

ABSOLUTES = re.compile(r"\b(100% (?:proven|true|certain)|scientists (?:all )?agree|no one can explain|everyone knows|guaranteed)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


class QualityAgent(Agent):
    name = "quality"
    role = "Pass / revise decision for a script"

    def check(self, brief: Brief, script_text: str, facts_text: str) -> AgentResult:
        ps = parser.parse(script_text)
        issues: list[dict] = []

        def add(sev: str, msg: str) -> None:
            issues.append({"severity": sev, "message": msg})

        if not ps.title:
            add("error", "Title: line missing.")
        if len(ps.scenes) < 3:
            add("error", f"Sirf {len(ps.scenes)} scene — kam se kam 3 chahiye.")
        elif len(ps.scenes) < 5:
            add("warn", f"{len(ps.scenes)} scene hain; 5-9 behtar hain.")
        narr = [ln for s in ps.scenes for ln in s.lines if ln.kind != "action"]
        if not narr:
            add("error", "Narration lines nahi hain.")
        seen: dict[str, int] = {}
        for ln in narr:
            k = _norm(ln.text)
            if len(k) > 12:
                seen[k] = seen.get(k, 0) + 1
        dups = [k for k, n in seen.items() if n > 1]
        if len(dups) >= 2:
            add("error", f"{len(dups)} lines repeat ho rahi hain.")
        elif dups:
            add("warn", "Ek line repeat ho rahi hai.")
        for s in ps.scenes:
            if not any(ln.kind != "action" for ln in s.lines):
                add("error", f"Scene {s.number} me narration nahi hai.")
        visuals = sum(1 for s in ps.scenes for ln in s.lines if ln.kind == "action" and ln.text.lower().startswith("show"))
        if ps.scenes and visuals < len(ps.scenes) * 0.6:
            add("warn", "Kai scenes me (show: ...) visual hint nahi hai — editor ko footage nahi milegi.")
        if narr and len(narr[0].text.split()) > 30:
            add("warn", "Hook bahut lamba hai (30 words se kam rakho).")
        t = brief.target_seconds
        if t and not (0.6 * t <= ps.seconds <= 1.5 * t):
            add("warn", f"Length ~{ps.seconds:.0f}s hai, target {t}s.")
        for s in ps.scenes:
            for ln in s.lines:
                if ln.kind != "action" and ABSOLUTES.search(ln.text):
                    add("warn", f"Scene {s.number}: bada daawa ('{ABSOLUTES.search(ln.text).group(0)}') — soften karo.")
        flags = script_flags(script_text, facts_text + " " + brief.topic) if facts_text else []
        if flags:
            add("warn", f"{len(flags)} line(s) me aise numbers/saal hain jo research me nahi the: "
                        + "; ".join(f"S{f['scene']}: {', '.join(f['numbers'])}" for f in flags[:4]))
        errors = sum(1 for i in issues if i["severity"] == "error")
        warns = len(issues) - errors
        score = max(0, 100 - 25 * errors - 7 * warns)
        res = AgentResult(self.name, ok=errors == 0, data={"score": score, "issues": issues, "seconds": ps.seconds,
                                                           "scenes": len(ps.scenes), "unbacked_numbers": flags})
        self.save(brief.project_id, res)
        return res

    @staticmethod
    def revision_instruction(result: AgentResult) -> str:
        return "Fix these problems and change nothing else: " + " ".join(i["message"] for i in result.data["issues"])[:450]
