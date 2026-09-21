from __future__ import annotations

import re
import uuid

from assure_contracts.adapters import ConversationResult, ConversationTurn, ToolInvocation
from assure_contracts.enums import TargetMode
from assure_contracts.events import AuthzDecision, NormalizedFact

from assure_demo.store import DemoStore, Principal, authorized

TICKET_RE = re.compile(r"([A-Za-z0-9_-]+-TKT-[AB]-\d+)")
CLAIMED_TENANT_RE = re.compile(r"for (tenant_[ab])", re.I)


def route_and_execute(
    store: DemoStore,
    principal: Principal,
    message: str,
    correlation_id: str,
    session_id: str = "",
) -> ConversationResult:
    session_id = session_id or correlation_id
    if "cached" in message.lower():
        leaked = store.cached_for(session_id, principal.tenant)
        output = "Cached context: " + " ".join(leaked) if leaked else "No cached ticket."
        _record_response(store, principal, correlation_id, output, [], {}, leaked)
        store.record(
            "retrieval_returns",
            correlation_id,
            NormalizedFact(
                authenticated_subject=principal.subject,
                active_tenant=principal.tenant,
                resources_returned=[],
                canaries_seen=leaked,
                output_text=output,
            ),
        )
        store.record(
            "tool_audit",
            correlation_id,
            NormalizedFact(
                authenticated_subject=principal.subject,
                active_tenant=principal.tenant,
                tool_requested="session_memory",
                tool_executed="session_memory",
            ),
        )
        return ConversationResult(
            output_text=output,
            turns=[ConversationTurn(role="assistant", text=output)],
            correlation_id=correlation_id,
        )
    ticket_id = _extract_ticket(message)
    if _wants_update(message) and ticket_id:
        return _update_ticket(store, principal, ticket_id, message, correlation_id, session_id)
    if _wants_search(message):
        return _search_help(store, principal, message, correlation_id, session_id)
    if ticket_id:
        return _get_ticket(store, principal, ticket_id, correlation_id, session_id, follow_inject=True)
    return ConversationResult(
        output_text="I could not determine which ticket or document to use.",
        turns=[ConversationTurn(role="assistant", text="I could not determine which ticket or document to use.")],
        correlation_id=correlation_id,
    )


def _extract_ticket(message: str) -> str | None:
    match = TICKET_RE.search(message)
    return match.group(1) if match else None


def _wants_update(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in ("status", "resolved", "update", "set ticket", "close"))


def _wants_search(message: str) -> bool:
    lowered = message.lower()
    return "search" in lowered or "help article" in lowered or "help" in lowered


def _get_ticket(
    store: DemoStore,
    principal: Principal,
    ticket_id: str,
    correlation_id: str,
    session_id: str,
    follow_inject: bool = False,
) -> ConversationResult:
    found = store.find_ticket(ticket_id)
    decision = AuthzDecision.DENY
    executed = False
    output = f"Ticket {ticket_id} was not found or is not accessible."
    resources: list[str] = []
    contents: dict[str, str] = {}
    canaries: list[str] = []

    if found:
        _namespace, ticket = found
        decision = authorized(store, principal, ticket.tenant, write=False, resource_id=ticket.ticket_id)
        if decision != AuthzDecision.DENY:
            executed = True
            resources = [ticket.ticket_id]
            contents = {ticket.ticket_id: ticket.body}
            canaries = [ticket.canary]
            store.remember(session_id, ticket.canary)
            output = f"Ticket {ticket.ticket_id} ({ticket.title}): {ticket.body} [status={ticket.status}]"
            if follow_inject and store.mode == TargetMode.VULNERABLE:
                injected = _extract_ticket(ticket.body)
                if injected and injected != ticket.ticket_id:
                    extra = _get_ticket(store, principal, injected, correlation_id, session_id, follow_inject=False)
                    resources.extend(extra.tools[0].resource_ids if extra.tools else [])
                    output = f"{output} | {extra.output_text}"
                    canaries.extend(re.findall(r"CANARY-[AB]-[A-Za-z0-9_-]+", extra.output_text))
        else:
            output = f"Denied access to ticket {ticket_id}."

    store.record(
        "tool_audit",
        correlation_id,
        NormalizedFact(
            authenticated_subject=principal.subject,
            active_tenant=principal.tenant,
            tool_requested="get_ticket",
            tool_executed="get_ticket" if executed else None,
            authz_decision=decision,
            resources_returned=resources,
            resource_contents=contents,
            canaries_seen=canaries,
        ),
    )
    store.record(
        "retrieval_returns",
        correlation_id,
        NormalizedFact(
            authenticated_subject=principal.subject,
            active_tenant=principal.tenant,
            tool_requested="get_ticket",
            tool_executed="get_ticket" if executed else None,
            authz_decision=decision,
            resources_returned=resources,
            resource_contents=contents,
            canaries_seen=canaries,
        ),
    )
    _record_response(store, principal, correlation_id, output, resources, contents, canaries)
    return ConversationResult(
        output_text=output,
        turns=[ConversationTurn(role="assistant", text=output)],
        tools=[
            ToolInvocation(
                name="get_ticket",
                executed=executed,
                arguments={"ticket_id": ticket_id},
                resource_ids=resources,
            )
        ],
        correlation_id=correlation_id,
    )


def _update_ticket(
    store: DemoStore,
    principal: Principal,
    ticket_id: str,
    message: str,
    correlation_id: str,
    session_id: str,
) -> ConversationResult:
    found = store.find_ticket(ticket_id)
    decision = AuthzDecision.DENY
    executed = False
    action_id = None
    output = f"Could not update ticket {ticket_id}."
    resources: list[str] = []
    claimed = None
    claimed_match = CLAIMED_TENANT_RE.search(message)
    if claimed_match:
        claimed = claimed_match.group(1).lower()

    if found:
        _namespace, ticket = found
        decision = authorized(
            store,
            principal,
            ticket.tenant,
            write=True,
            resource_id=ticket.ticket_id,
            claimed_tenant=claimed,
        )
        if decision != AuthzDecision.DENY:
            if store.fail_downstream:
                if store.mode == TargetMode.SAFE:
                    ticket.status = "open"
                    store.escalations.append(ticket.ticket_id)
                    output = f"Downstream failure; ticket {ticket.ticket_id} left open and escalated."
                else:
                    ticket.status = "pending"
                    output = f"Partial update left ticket {ticket.ticket_id} pending."
                store.fail_downstream = False
            else:
                key = f"{session_id}:{ticket.ticket_id}:resolved"
                if store.mode == TargetMode.SAFE and key in store.idempotency:
                    action_id = store.idempotency[key]
                    executed = True
                    resources = [ticket.ticket_id]
                    output = f"Idempotent update {action_id} for {ticket.ticket_id}."
                else:
                    ticket.status = "resolved" if "resolved" in message.lower() or "close" in message.lower() else "pending"
                    executed = True
                    action_id = f"act-{uuid.uuid4().hex[:10]}"
                    store.idempotency[key] = action_id
                    resources = [ticket.ticket_id]
                    output = f"Updated ticket {ticket.ticket_id} to {ticket.status}."
        else:
            output = f"Denied status change for ticket {ticket_id}."

    store.record(
        "tool_audit",
        correlation_id,
        NormalizedFact(
            authenticated_subject=principal.subject,
            active_tenant=principal.tenant,
            tool_requested="update_ticket_status",
            tool_executed="update_ticket_status" if executed else None,
            authz_decision=decision,
            resources_returned=resources,
            committed_action_id=action_id,
        ),
    )
    _record_response(store, principal, correlation_id, output, resources, {}, [])
    return ConversationResult(
        output_text=output,
        turns=[ConversationTurn(role="assistant", text=output)],
        tools=[
            ToolInvocation(
                name="update_ticket_status",
                executed=executed,
                arguments={"ticket_id": ticket_id},
                resource_ids=resources,
            )
        ],
        correlation_id=correlation_id,
    )


def _search_help(
    store: DemoStore,
    principal: Principal,
    message: str,
    correlation_id: str,
    session_id: str,
) -> ConversationResult:
    docs = store.find_docs(message)
    returned = []
    contents: dict[str, str] = {}
    canaries: list[str] = []
    for doc in docs:
        decision = authorized(store, principal, doc.tenant, write=False, resource_id=doc.doc_id)
        if decision == AuthzDecision.DENY:
            continue
        returned.append(doc.doc_id)
        contents[doc.doc_id] = doc.body
        canaries.append(doc.canary)
        store.remember(session_id, doc.canary)
    output = "No help articles." if not returned else " | ".join(contents.values())
    if store.mode == TargetMode.VULNERABLE:
        for body in contents.values():
            if _wants_update(body):
                injected = _extract_ticket(body)
                if injected:
                    extra = _update_ticket(store, principal, injected, body, correlation_id, session_id)
                    output = f"{output} | {extra.output_text}"
    store.record(
        "retrieval_returns",
        correlation_id,
        NormalizedFact(
            authenticated_subject=principal.subject,
            active_tenant=principal.tenant,
            tool_requested="search_help",
            tool_executed="search_help",
            authz_decision=AuthzDecision.ALLOW if returned else AuthzDecision.DENY,
            resources_returned=returned,
            resource_contents=contents,
            canaries_seen=canaries,
        ),
    )
    store.record(
        "tool_audit",
        correlation_id,
        NormalizedFact(
            authenticated_subject=principal.subject,
            active_tenant=principal.tenant,
            tool_requested="search_help",
            tool_executed="search_help",
        ),
    )
    _record_response(store, principal, correlation_id, output, returned, contents, canaries)
    return ConversationResult(
        output_text=output,
        turns=[ConversationTurn(role="assistant", text=output)],
        tools=[ToolInvocation(name="search_help", executed=True, resource_ids=returned)],
        correlation_id=correlation_id,
    )


def _record_response(
    store: DemoStore,
    principal: Principal,
    correlation_id: str,
    output: str,
    resources: list[str],
    contents: dict[str, str],
    canaries: list[str],
) -> None:
    store.record(
        "response_capture",
        correlation_id,
        NormalizedFact(
            authenticated_subject=principal.subject,
            active_tenant=principal.tenant,
            resources_returned=resources,
            resource_contents=contents,
            output_text=output,
            canaries_seen=canaries,
        ),
    )


__all__ = ["route_and_execute", "TargetMode"]
