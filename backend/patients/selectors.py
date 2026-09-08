"""Access-control helpers: who may see which patient profile."""


def patient_ids_for_healthcare_worker(user):
    """All patient ids a healthcare worker may access.

    Access = patients the worker created themselves OR patients explicitly
    assigned to them by an administrator. Admins use the all-patient path and
    never call this helper.
    """
    from patients.models import PatientAssignment, PatientProfile

    created = set(
        PatientProfile.objects.filter(created_by=user).values_list("id", flat=True)
    )
    assigned = set(
        PatientAssignment.objects.filter(healthcare_worker=user).values_list("patient_id", flat=True)
    )
    return created | assigned


def can_access_patient(user, patient_profile):
    """Admins: all patients. Workers: patients they created or that are
    explicitly assigned to them. Anything else is denied."""
    if not (user and user.is_authenticated):
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "HEALTHCARE_WORKER":
        from patients.models import PatientAssignment

        if patient_profile.created_by_id == user.id:
            return True
        return PatientAssignment.objects.filter(
            healthcare_worker=user, patient=patient_profile
        ).exists()
    return False


def scoped_patient_queryset(user):
    """Patient records visible to the authenticated user."""
    from patients.models import PatientProfile

    qs = PatientProfile.objects.select_related("created_by").order_by("-created_at", "-id").all()
    if user.role == "ADMIN":
        return qs
    if user.role == "HEALTHCARE_WORKER":
        return qs.filter(id__in=patient_ids_for_healthcare_worker(user))
    return PatientProfile.objects.none()


def patient_summaries(patient_ids):
    """Aggregated clinical summaries for the given patient ids.

    Returns {patient_id: {...}} with current risk (latest stored prediction),
    assessment count, last assessment date and open rule-alert count. This is
    descriptive analytics over stored data only - never a future prediction.
    """
    if not patient_ids:
        return {}

    from assessments.models import Alert, Assessment, Prediction

    assessments = Assessment.objects.filter(patient_id__in=patient_ids).values(
        "patient_id", "visit_date", "id"
    )
    last_assessment = {}
    counts = {}
    for row in assessments:
        pid = row["patient_id"]
        counts[pid] = counts.get(pid, 0) + 1
        key = (row["visit_date"], row["id"])
        if pid not in last_assessment or key > last_assessment[pid][0]:
            last_assessment[pid] = (key, row["visit_date"])

    latest_pred = {}
    series = {}
    for row in (
        Prediction.objects.filter(assessment__patient_id__in=patient_ids)
        .select_related("assessment")
        .order_by("assessment__visit_date", "assessment__id")
    ):
        latest_pred[row.assessment.patient_id] = {
            "risk_level": row.risk_level,
            "probability": row.probability,
        }
        series.setdefault(row.assessment.patient_id, []).append({"risk_level": row.risk_level})

    from assessments.trends import compute_trend

    trends = {}
    for pid, hist in series.items():
        trends[pid] = compute_trend(hist)

    open_alerts = {}
    for row in Alert.objects.filter(patient_id__in=patient_ids, status="OPEN").values("patient_id"):
        open_alerts[row["patient_id"]] = open_alerts.get(row["patient_id"], 0) + 1

    summaries = {}
    for pid in patient_ids:
        last = latest_pred.get(pid)
        last_date = last_assessment.get(pid, (None, None))[1]
        summaries[pid] = {
            "current_risk": last["risk_level"] if last else None,
            "current_confidence": round(last["probability"], 4) if last else None,
            "current_trend_status": trends.get(pid, {}).get("status"),
            "current_trend_direction": trends.get(pid, {}).get("direction"),
            "assessment_count": counts.get(pid, 0),
            "last_assessment_date": last_date.isoformat() if last_date else None,
            "open_alert_count": open_alerts.get(pid, 0),
        }
    return summaries
