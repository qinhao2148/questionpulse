import json
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.routes.shared import (
    Authorization,
    Database,
    feedback_summary,
    question_view,
    require_session,
    require_teacher,
)
from app.models.classroom import (
    AIDecision,
    AIRun,
    CheckQuestion,
    CheckResponse,
    CheckTarget,
    Cluster,
    ClusterEvent,
    Participant,
    Question,
)
from app.schemas.classroom import (
    ReportAIInsight,
    ReportCluster,
    ReportTimelineEvent,
    SessionReport,
)

router = APIRouter()



@router.get("/sessions/{session_id}/report", response_model=SessionReport)
async def get_report(
    session_id: str, db: Database, authorization: Authorization = None
) -> SessionReport:
    classroom = await require_session(db, session_id)
    require_teacher(classroom, authorization)
    clusters = list(await db.scalars(select(Cluster).where(Cluster.session_id == session_id)))
    questions = list(await db.scalars(select(Question).where(Question.session_id == session_id)))
    roster = [
        item
        for item in await db.scalars(
            select(Participant).where(Participant.session_id == session_id)
        )
        if item.source == "student"
    ]
    # 观看人数只算从学生端课堂码进来的人。POLYV 同步提问派生的影子身份
    # 属于直播平台的 viewer id，和学生端身份是两套编号，算进来只会把分母撑大。
    viewer_ids = {item.id for item in roster}
    asker_ids = {
        question.participant_id
        for question in questions
        if question.participant_id in viewer_ids
    }
    viewer_count = len(viewer_ids)
    asker_count = len(asker_ids)
    # 加入课堂后又真的打开课堂页的人。学生端每 3 秒拉一次快照，会留下心跳。
    active_viewer_count = sum(1 for item in roster if item.last_seen_at is not None)
    report_clusters = []
    for cluster in clusters:
        members = [question for question in questions if question.cluster_id == cluster.id]
        report_clusters.append(
            ReportCluster(
                id=cluster.id,
                title=cluster.title,
                status=cluster.status,
                participant_count=len({question.participant_id for question in members}),
                question_count=len(members),
                feedback=await feedback_summary(db, cluster),
                feedback_history=[
                    await feedback_summary(db, cluster, round_number=round_number)
                    for round_number in range(1, cluster.feedback_round + 1)
                ],
                questions=[question_view(question) for question in members],
            )
        )
    report_clusters.sort(key=lambda item: (-item.participant_count, -item.question_count))
    summaries = [item.feedback for item in report_clusters]
    targets = sum(item.targets for item in summaries)
    responses = sum(item.responses for item in summaries)
    checks = list(
        await db.scalars(select(CheckQuestion).where(CheckQuestion.session_id == session_id))
    )
    check_ids = [item.id for item in checks]
    check_targets = 0
    check_responses = []
    if check_ids:
        check_targets = (
            await db.scalar(
                select(func.count())
                .select_from(CheckTarget)
                .where(CheckTarget.check_question_id.in_(check_ids))
            )
            or 0
        )
        check_responses = list(
            await db.scalars(
                select(CheckResponse).where(CheckResponse.check_question_id.in_(check_ids))
            )
        )
    check_correct = sum(item.is_correct for item in check_responses)
    cluster_titles = {item.id: item.title for item in clusters}
    timeline = [
        ReportTimelineEvent(
            kind="question_received",
            cluster_id=question.cluster_id,
            cluster_title=cluster_titles.get(question.cluster_id),
            detail=f"收到问题：{question.content}",
            occurred_at=question.occurred_at or question.created_at,
        )
        for question in questions
    ]
    events = list(
        await db.scalars(
            select(ClusterEvent)
            .where(ClusterEvent.session_id == session_id)
            .order_by(ClusterEvent.created_at)
        )
    )
    status_labels = {
        "open": "重新打开疑问",
        "addressing": "教师开始讲解",
        "awaiting_feedback": "讲解结束并收集反馈",
        "closed": "疑问处理完成",
    }
    for event in events:
        payload = json.loads(event.payload_json or "{}")
        if event.event_type == "status_changed":
            detail = status_labels.get(payload.get("to"), "疑问状态发生变化")
        elif event.event_type == "question_detached":
            detail = "教师将问题拆分为独立疑问"
        else:
            detail = event.event_type
        timeline.append(
            ReportTimelineEvent(
                kind=event.event_type,
                cluster_id=event.cluster_id,
                cluster_title=cluster_titles.get(event.cluster_id),
                detail=detail,
                occurred_at=event.created_at,
            )
        )
    timeline.extend(
        ReportTimelineEvent(
            kind="check_created",
            cluster_id=check.cluster_id,
            cluster_title=cluster_titles.get(check.cluster_id),
            detail=f"生成理解检测（{check.source}）",
            occurred_at=check.created_at,
        )
        for check in checks
    )
    timeline.sort(
        key=lambda item: item.occurred_at.replace(tzinfo=None)
        if item.occurred_at.tzinfo
        else item.occurred_at
    )
    decision_rows = list(
        (
            await db.execute(
                select(AIDecision, AIRun)
                .join(AIRun, AIDecision.ai_run_id == AIRun.id)
                .where(
                    AIRun.session_id == session_id,
                    AIRun.provider == "deepseek",
                    AIRun.status == "succeeded",
                    AIDecision.cluster_id.is_not(None),
                )
                .order_by(AIDecision.created_at.desc())
            )
        ).all()
    )
    report_by_cluster = {item.id: item for item in report_clusters}
    ai_insights = []
    seen_insight_clusters = set()
    for decision, run in decision_rows:
        if decision.cluster_id in seen_insight_clusters:
            continue
        cluster_report = report_by_cluster.get(decision.cluster_id)
        if cluster_report is None:
            continue
        if cluster_report.feedback.still_confused > 0:
            recommendation = "结合学生仍困惑反馈重新讲解，并用具体反例后再次检测。"
        elif cluster_report.status != "closed":
            recommendation = "完成本轮讲解与理解反馈，再依据检测结果决定是否关闭。"
        else:
            recommendation = "该疑问已完成闭环，可在下节课开头用一道迁移题快速复核。"
        ai_insights.append(
            ReportAIInsight(
                cluster_id=cluster_report.id,
                cluster_title=cluster_report.title,
                normalized_intent=decision.normalized_intent,
                semantic_reason=decision.reason,
                recommendation=recommendation,
                model=run.model,
            )
        )
        seen_insight_clusters.add(decision.cluster_id)
    return SessionReport(
        id=classroom.id,
        title=classroom.title,
        status=classroom.status,
        ended_at=classroom.ended_at,
        generated_at=datetime.now(UTC),
        question_count=len(questions),
        viewer_count=viewer_count,
        active_viewer_count=active_viewer_count,
        asker_count=asker_count,
        silent_viewer_count=max(viewer_count - asker_count, 0),
        ask_rate=round(asker_count / viewer_count, 4) if viewer_count else 0.0,
        participant_count=asker_count,
        cluster_count=len(clusters),
        status_counts=dict(Counter(cluster.status for cluster in clusters)),
        feedback_targets=targets,
        feedback_responses=responses,
        feedback_coverage=round(responses / targets, 4) if targets else 0.0,
        understood=sum(item.understood for item in summaries),
        still_confused=sum(item.still_confused for item in summaries),
        check_targets=check_targets,
        check_responses=len(check_responses),
        check_correct=check_correct,
        check_accuracy=(round(check_correct / len(check_responses), 4) if check_responses else 0.0),
        clusters=report_clusters,
        follow_ups=[item for item in report_clusters if item.feedback.still_confused > 0],
        timeline=timeline,
        ai_insights=ai_insights,
    )
