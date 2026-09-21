from enum import StrEnum


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class AssertionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class AssertionKind(StrEnum):
    FORBIDDEN_RESOURCE_NOT_RETURNED_TO_AGENT = "forbidden_resource_not_returned_to_agent"
    FORBIDDEN_CANARY_NOT_IN_OUTPUT = "forbidden_canary_not_in_output"
    NO_UNAUTHORIZED_COMMITTED_STATE_CHANGE = "no_unauthorized_committed_state_change"
    LEGITIMATE_RESOURCE_RETURNED = "legitimate_resource_returned"
    OBSERVATION_COMPLETE = "observation_complete"
    TOOL_NOT_EXECUTED = "tool_not_executed"
    AT_MOST_ONE_COMMITTED_ACTION = "at_most_one_committed_action"
    EXPECTED_TICKET_STATUS = "expected_ticket_status"


class ExecutionStatus(StrEnum):
    REGISTERED = "Registered"
    RUNNING = "Running"
    UPLOADING = "Uploading"
    COMPLETED = "Completed"
    CANCEL_REQUESTED = "CancelRequested"
    CANCELLED = "Cancelled"
    INCOMPLETE = "Incomplete"


class GateStatus(StrEnum):
    SATISFIED = "satisfied"
    BLOCKED_FINDING = "blocked_finding"
    BLOCKED_INCOMPLETE = "blocked_incomplete"
    BLOCKED_SETUP = "blocked_setup"
    NOT_EVALUATED = "not_evaluated"


class EvidenceStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


class ExportMode(StrEnum):
    LOCAL = "local"
    SUMMARY = "summary"
    REDACTED_EXAMPLES = "redacted_examples"


class TargetMode(StrEnum):
    SAFE = "safe"
    VULNERABLE = "vulnerable"
    REJECT_ALL = "reject_all"
