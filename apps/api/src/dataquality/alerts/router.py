from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from dataquality.alerts import service
from dataquality.alerts.schemas import (
    ChannelCreated,
    ChannelIn,
    ChannelOut,
    ChannelUpdate,
    ExplainOut,
    IncidentDetail,
    IncidentOut,
    RuleIn,
    RuleOut,
    RuleUpdate,
)
from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.core.schemas import Ack
from dataquality.projects.access import Editor, Viewer

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["alerts"])


@router.get("/alert-channels", response_model=list[ChannelOut], summary="Where alerts go")
async def list_channels(p: Viewer, session: SessionDep) -> list[ChannelOut]:
    return [service.channel_out(c) for c in await service.list_channels(session, p.project_id)]


@router.post(
    "/alert-channels",
    response_model=ChannelCreated,
    status_code=201,
    summary="Add an email, Slack or webhook channel",
)
async def create_channel(
    body: ChannelIn, p: Editor, session: SessionDep, container: ContainerDep
) -> ChannelCreated:
    return await service.create_channel(container, session, p, body)


@router.patch("/alert-channels/{channel_id}", response_model=ChannelOut, summary="Change a channel")
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
) -> ChannelOut:
    c = await service.get_channel(session, p.project_id, channel_id)
    return service.channel_out(await service.update_channel(container, session, p, c, body))


@router.delete("/alert-channels/{channel_id}", status_code=204, summary="Delete a channel")
async def delete_channel(channel_id: uuid.UUID, p: Editor, session: SessionDep) -> Response:
    await service.delete_channel(
        session, p, await service.get_channel(session, p.project_id, channel_id)
    )
    return Response(status_code=204)


@router.post(
    "/alert-channels/{channel_id}/test", response_model=Ack, summary="Send a test message now"
)
async def test_channel(
    channel_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> Ack:
    c = await service.get_channel(session, p.project_id, channel_id)
    return Ack(message=await service.test_channel(container, c))


@router.get("/alert-rules", response_model=list[RuleOut], summary="When to alert")
async def list_rules(p: Viewer, session: SessionDep) -> list[RuleOut]:
    return [RuleOut.model_validate(r) for r in await service.list_rules(session, p.project_id)]


@router.post("/alert-rules", response_model=RuleOut, status_code=201, summary="Add an alert rule")
async def create_rule(body: RuleIn, p: Editor, session: SessionDep) -> RuleOut:
    return RuleOut.model_validate(await service.create_rule(session, p, body))


@router.patch("/alert-rules/{rule_id}", response_model=RuleOut, summary="Change an alert rule")
async def update_rule(
    rule_id: uuid.UUID, body: RuleUpdate, p: Editor, session: SessionDep
) -> RuleOut:
    r = await service.get_rule(session, p.project_id, rule_id)
    return RuleOut.model_validate(await service.update_rule(session, p, r, body))


@router.delete(
    "/alert-rules/{rule_id}", status_code=204, summary="Delete an alert rule and its incidents"
)
async def delete_rule(rule_id: uuid.UUID, p: Editor, session: SessionDep) -> Response:
    await service.delete_rule(session, p, await service.get_rule(session, p.project_id, rule_id))
    return Response(status_code=204)


@router.get("/incidents", response_model=list[IncidentOut], summary="Incidents, most recent first")
async def list_incidents(
    p: Viewer,
    session: SessionDep,
    status: str | None = Query(None, pattern=r"^(active|open|acknowledged|resolved)$"),
    dataset_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[IncidentOut]:
    return await service.list_incidents(session, p.project_id, status, dataset_id, limit)


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetail,
    summary="An incident and its notifications",
)
async def get_incident(incident_id: uuid.UUID, p: Viewer, session: SessionDep) -> IncidentDetail:
    return await service.incident_detail(
        session, await service.get_incident(session, p.project_id, incident_id)
    )


@router.post(
    "/incidents/{incident_id}/acknowledge",
    response_model=IncidentDetail,
    summary="Acknowledge an incident",
)
async def acknowledge(incident_id: uuid.UUID, p: Editor, session: SessionDep) -> IncidentDetail:
    i = await service.acknowledge(
        session, p, await service.get_incident(session, p.project_id, incident_id)
    )
    return await service.incident_detail(session, i)


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=IncidentDetail,
    summary="Resolve an incident by hand",
)
async def resolve(incident_id: uuid.UUID, p: Editor, session: SessionDep) -> IncidentDetail:
    i = await service.resolve(
        session, p, await service.get_incident(session, p.project_id, incident_id)
    )
    return await service.incident_detail(session, i)


@router.post(
    "/incidents/{incident_id}/explain",
    response_model=ExplainOut,
    summary="Explain an incident (optional AI)",
)
async def explain(
    incident_id: uuid.UUID, p: Viewer, session: SessionDep, container: ContainerDep
) -> ExplainOut:
    from dataquality.ai import service as ai

    i = await service.get_incident(session, p.project_id, incident_id)
    return await ai.explain_incident(container, session, p, i)
