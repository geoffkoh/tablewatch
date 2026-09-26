"""JUnit XML, the format every CI system can display.

One test suite per dataset, one test case per check. `fail` becomes a
<failure>, `error` an <error>. JUnit has no notion of a warning, so a warn
passes and carries its message in <system-out>.
"""

from __future__ import annotations

from collections.abc import Iterable
from xml.etree import ElementTree as ET

from tablewatch.checks.model import Outcome
from tablewatch.engine.runner import CheckResult, RunResult


def render(run: RunResult) -> str:
    suites = ET.Element("testsuites", name=run.project)
    by_dataset: dict[str, list[CheckResult]] = {}
    for result in run.results:
        by_dataset.setdefault(result.check.dataset.name, []).append(result)
    for dataset, results in by_dataset.items():
        suite = ET.SubElement(
            suites,
            "testsuite",
            name=dataset,
            tests=str(len(results)),
            failures=str(_count(results, Outcome.FAIL)),
            errors=str(_count(results, Outcome.ERROR)),
            skipped=str(_count(results, Outcome.SKIPPED)),
            time=f"{(results[0].duration_ms / 1000) if results else 0:.3f}",
        )
        for result in results:
            case = ET.SubElement(
                suite,
                "testcase",
                classname=dataset,
                name=result.check.name,
                file=result.check.location.path.as_posix(),
                line=str(result.check.location.line),
            )
            text = (
                f"{result.display_value}: {result.message}"
                if result.message
                else result.display_value
            )
            match result.outcome:
                case Outcome.FAIL:
                    ET.SubElement(case, "failure", message=text).text = text
                case Outcome.ERROR:
                    ET.SubElement(case, "error", message=text).text = text
                case Outcome.SKIPPED:
                    ET.SubElement(case, "skipped", message=text)
                case Outcome.WARN:
                    ET.SubElement(case, "system-out").text = f"WARN {text}"
                case Outcome.PASS:
                    pass
    ET.indent(suites)
    return ET.tostring(suites, encoding="unicode", xml_declaration=True)


def _count(results: Iterable[CheckResult], outcome: Outcome) -> int:
    return sum(1 for r in results if r.outcome is outcome)
