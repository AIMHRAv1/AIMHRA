"""Access-control helpers: who may see which patient profile."""


def patient_ids_for_healthcare_worker(user):
    from patients.models import PatientAssignment

    return set(
        PatientAssignment.objects.filter(healthcare_worker=user).values_list("patient_id", flat=True)
    )


def can_access_patient(user, patient_profile):
    """Admins: all. Patients: own profile. Workers: assigned patients only."""
    if not (user and user.is_authenticated):
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "PATIENT":
        return patient_profile.user_id == user.id
    if user.role == "HEALTHCARE_WORKER":
        from patients.models import PatientAssignment

        return PatientAssignment.objects.filter(
            healthcare_worker=user, patient=patient_profile
        ).exists()
    return False
