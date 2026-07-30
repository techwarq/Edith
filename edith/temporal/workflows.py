"""Single generic workflow — every scheduled job (nightly reflection, one-off
reminders, recurring jobs created via schedule_job) is a natural-language
instruction run through the same Agent.handle_turn path used everywhere else,
so there's no bespoke workflow per feature."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from edith.temporal import activities


@workflow.defn
class RunAgentInstructionWorkflow:
    @workflow.run
    async def run(self, instruction: str) -> str:
        return await workflow.execute_activity(
            activities.run_agent_instruction,
            instruction,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


def _phase1_scan(findings: str) -> str:
    return """\
This is an unattended overnight research job — nobody is watching live, so work
autonomously and thoroughly; don't ask questions, make reasonable calls yourself.

Goal: surface promising startup/product ideas for me to consider building, grounded in
real web research — not ideas pulled from your own training knowledge alone.

1. Use web_search repeatedly to scan for current momentum: recent funding rounds, product
   launches, "state of X" reports, Show HN / Product Hunt trends, subreddit/forum
   complaints, regulatory or platform shifts (new APIs, new laws, new consumer behavior) —
   anything from roughly the last 6-12 months that signals a moment worth acting on.
2. From what you find, generate 12-15 distinct candidate ideas. For each: one line on what
   it is, and one line on the specific signal that makes it timely — cite what you actually
   found, don't invent statistics or sources.
3. Skip anything you already strongly suspect is oversaturated (e.g. "another AI chatbot
   wrapper", "another Notion clone") — note briefly why you excluded categories like that,
   so the next round doesn't waste budget re-discovering them.

Output a numbered list of the 12-15 candidates with their timing signal. This is an
intermediate research artifact, not a final answer — a later round will narrow it down, so
don't over-polish.
"""


def _phase2_eliminate(findings: str) -> str:
    return f"""\
Overnight research, round 2 of 3 — narrowing the candidate list from your last round.

Here is what you found last round:
---
{findings}
---

For each candidate above, use web_search to specifically check two things:
1. Market saturation: are there already multiple funded/established players doing exactly
   this? Name them if so. A crowded space isn't automatically disqualifying, but a lack of
   any differentiation is.
2. Willingness to pay: is there real evidence people pay for this or something adjacent —
   existing pricing pages, paid competitors, people asking "is there a paid version of X",
   complaints about a free tool's limits? Vague "this would be nice to have" is not evidence.

Cut anything where saturation is high AND you found no differentiation angle, or where you
found no willingness-to-pay evidence at all. Be genuinely critical — the point of this round
is to kill weak ideas, not defend all of them.

Output the surviving 6-8 ideas, each with what changed your confidence (up or down) based on
what you just found, and, for anything you cut, a one-line reason why.
"""


def _phase3_synthesize(findings: str) -> str:
    return f"""\
Overnight research, final round — turn the survivors into your actual recommendation.

Survivors from the last round:
---
{findings}
---

For each, do one more targeted web_search pass to sharpen the specific angle: who exactly
the first paying customer would be, what a v1 could realistically look like, and the
strongest reason "now" is the right time rather than 2 years ago or 2 years from now.

Then pick your best 3-4 — not the ones you found first, the ones with the strongest
combination of (real demand signal) + (room to differentiate) + (timing). Ranked as ones
you'd bet on if you actually had to build one this quarter.

Your final reply IS the deliverable — nobody is watching this live, it gets read later, so
write it as a clear, self-contained brief: for each of the 3-4 ideas, what it is, the
evidence for demand, the competitive gap, why now, and a realistic first step. Skip
pleasantries and don't pad it out.
"""


_DEEP_RESEARCH_PHASES = [_phase1_scan, _phase2_eliminate, _phase3_synthesize]


@workflow.defn
class DeepResearchWorkflow:
    """Overnight product-idea research: three rounds — broad scan, elimination, final
    synthesis — separated by real sleep (not three activities back to back) so the run
    spreads across the night instead of bursting all at once. Each round's findings are
    threaded through explicitly as workflow state (the phase functions above take/return
    plain strings) rather than relying on the shared jobs-session chat history, since other
    scheduled jobs (nightly reflection, one-offs) can interleave in that same session
    overnight and would otherwise push a prior round's findings out of context.

    budget_usd/sleep_hours are passed in by the caller (schedules.start_deep_research,
    reading edith.config) rather than read from config here — workflow code must stay
    deterministic/side-effect-free, and reading env vars inside the workflow body would
    violate that.
    """

    @workflow.run
    async def run(self, budget_usd: float, sleep_hours: float) -> str:
        findings = ""
        spent = 0.0
        for i, build_instruction in enumerate(_DEEP_RESEARCH_PHASES):
            if spent >= budget_usd:
                workflow.logger.info(
                    "Deep research stopping early before round %d — budget exhausted ($%.2f spent).",
                    i + 1,
                    spent,
                )
                break
            result = await workflow.execute_activity(
                activities.run_deep_research_round,
                build_instruction(findings),
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            findings = result["reply"]
            spent += result["cost_usd"]
            if i < len(_DEEP_RESEARCH_PHASES) - 1:
                await workflow.sleep(timedelta(hours=sleep_hours))

        await workflow.execute_activity(
            activities.notify_deep_research_done,
            findings,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return findings


@workflow.defn
class RunEvalsWorkflow:
    """Separate from RunAgentInstructionWorkflow (which takes a natural-language
    instruction) because running the eval suite is a direct Python call
    (evals.run_eval_suite), not something expressible as agent instruction
    text — see activities.run_nightly_evals."""

    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(
            activities.run_nightly_evals,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
