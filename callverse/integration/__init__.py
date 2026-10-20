"""The unified CallVerse workflow, shared by every channel (text, voice, later the simulator).

    message -> Intake -> Router -> specialist agent -> Coordinator -> response writer -> reply

Each stage uses the team's REAL module when it exists in the repository, and says so in the result
("steps"). A stage that is not built yet is never faked: it is marked "not built" and the workflow does
the safe thing (no action is executed without the Coordinator). See docs/integration.md.
"""
