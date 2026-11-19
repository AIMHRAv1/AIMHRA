"""Create clearly labeled synthetic demo patients with longitudinal assessments.

Usage: python manage.py create_demo_patients --patients 12 --visits 4
"""
from calendar import monthrange
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from assessments.models import Assessment
from assessments.services import create_assessment
from patients.models import PatientProfile

DEMO_PATIENT_NAMES = [
    "Ram Pariyar",
    "Shyam Khadka",
    "Krishna Bishwakarma",
    "Sujit Gaiju",
    "Rabin Shrestha",
    "Sabin Thapa",
    "Aarati Gurung",
    "Sita Tamang",
    "Maya Rai",
    "Nisha Karki",
    "Anusha Magar",
    "Laxmi Bhandari",
    "Sunita Poudel",
    "Gita Lama",
    "Pratima Basnet",
]

DEMO_WORKERS = [
    ("demo.hw.nepali01", "DEMO - Anisha Thapa (Synthetic Account)"),
    ("demo.hw.nepali02", "DEMO - Sushma Gurung (Synthetic Account)"),
    ("demo.hw.nepali03", "DEMO - Binita Shrestha (Synthetic Account)"),
]


class Command(BaseCommand):
    help = "Create labeled synthetic demo patients and model-generated assessments."

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=12)
        parser.add_argument("--visits", type=int, default=4)
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Apply Nepali demo names and demo-worker attribution to marked synthetic patients.",
        )

    def handle(self, *args, **options):
        patient_count = options["patients"]
        visit_count = options["visits"]
        if not 1 <= patient_count <= 15:
            raise CommandError("--patients must be between 1 and 15.")
        if not 1 <= visit_count <= 4:
            raise CommandError("--visits must be between 1 and 4.")

        existing = PatientProfile.objects.filter(
            additional_notes__startswith="SYNTHETIC DEMO RECORD."
        ).count()
        if existing and not options["update_existing"]:
            raise CommandError(
                f"Found {existing} existing demo patient(s); refusing to create "
                "duplicates. Use --update-existing to relabel marked synthetic records."
            )
        if options["update_existing"] and not existing:
            raise CommandError("No explicitly marked synthetic demo patients were found to update.")
        if existing > len(DEMO_PATIENT_NAMES):
            raise CommandError(
                f"Found {existing} marked demo records; this command supports at most "
                f"{len(DEMO_PATIENT_NAMES)}."
            )

        today = timezone.localdate()
        assessments_created = 0
        with transaction.atomic():
            workers = []
            for username, full_name in DEMO_WORKERS:
                worker, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "email": f"{username}@example.invalid",
                        "full_name": full_name,
                        "role": User.ROLE_HEALTHCARE_WORKER,
                        "is_active": True,
                    },
                )
                if worker.role != User.ROLE_HEALTHCARE_WORKER:
                    raise CommandError(f"Demo username {username} is already used by another role.")
                if not worker.full_name.startswith("DEMO - "):
                    raise CommandError(f"Demo username {username} belongs to a non-demo account.")
                if created:
                    worker.set_unusable_password()
                    worker.save(update_fields=["password"])
                workers.append(worker)

            if options["update_existing"]:
                patients = list(
                    PatientProfile.objects.filter(
                        additional_notes__startswith="SYNTHETIC DEMO RECORD."
                    ).order_by("id")
                )
                for patient_index, patient in enumerate(patients):
                    patient.full_name = (
                        f"DEMO - {DEMO_PATIENT_NAMES[patient_index]} (Synthetic Patient)"
                    )
                    patient.created_by = workers[patient_index % len(workers)]
                    patient.save(update_fields=["full_name", "created_by"])
                    for visit_index, assessment in enumerate(
                        Assessment.objects.filter(patient=patient).order_by("visit_date", "id")
                    ):
                        assessment.created_by = workers[
                            (patient_index + visit_index) % len(workers)
                        ]
                        assessment.save(update_fields=["created_by"])
                        assessments_created += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {len(patients)} synthetic demo patient names and attributed "
                        f"{assessments_created} existing assessments across {len(workers)} "
                        "non-login demo healthcare-worker accounts."
                    )
                )
                self.stdout.write(
                    "Names and visits remain explicitly marked DEMO/Synthetic; these are "
                    "not real people or real data-entry records."
                )
                return

            for patient_index in range(1, patient_count + 1):
                age = 21 + (patient_index % 16)
                birth_year = today.year - age
                birth_day = min(today.day, monthrange(birth_year, today.month)[1])
                date_of_birth = date(birth_year, today.month, birth_day)
                worker = workers[(patient_index - 1) % len(workers)]
                patient = PatientProfile.objects.create(
                    full_name=(
                        f"DEMO - {DEMO_PATIENT_NAMES[patient_index - 1]} "
                        "(Synthetic Patient)"
                    ),
                    date_of_birth=date_of_birth,
                    created_by=worker,
                    additional_notes=(
                        "SYNTHETIC DEMO RECORD. Not a real patient; "
                        "do not use for clinical decisions."
                    ),
                )

                for visit_index in range(visit_count):
                    weeks_before_today = (visit_count - visit_index - 1) * 3
                    visit_date = today - timedelta(weeks=weeks_before_today)
                    payload = {
                        "visit_date": visit_date,
                        "gestational_week": 12 + visit_index * 3,
                        "age": age,
                        "body_temperature": round(
                            98.2 + ((patient_index + visit_index) % 5) * 0.1, 1
                        ),
                        "heart_rate": 74 + ((patient_index * 3 + visit_index * 2) % 16),
                        "systolic_bp": 108 + ((patient_index * 7 + visit_index * 3) % 25),
                        "diastolic_bp": 68 + ((patient_index * 5 + visit_index * 2) % 18),
                        "bmi": round(
                            19.2 + ((patient_index * 4 + visit_index * 3) % 100) / 10, 1
                        ),
                        # Stored in the model's training units: mmol/mol and mmol/L.
                        "hba1c": 33 + ((patient_index * 3 + visit_index) % 14),
                        "fasting_glucose": round(
                            4.2 + ((patient_index * 7 + visit_index * 2) % 25) / 10, 1
                        ),
                        "symptoms": [],
                        "notes": (
                            "Synthetic demo assessment; values are fictional "
                            "and are not for clinical use."
                        ),
                    }
                    create_assessment(patient, payload)
                    visit_worker = workers[(patient_index - 1 + visit_index) % len(workers)]
                    Assessment.objects.filter(
                        patient=patient, visit_date=visit_date
                    ).update(created_by=visit_worker)
                    assessments_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {patient_count} synthetic demo patients and "
                f"{assessments_created} model-generated assessments."
            )
        )
        self.stdout.write(
            f"Records are labeled DEMO and attributed across {len(workers)} "
            "synthetic healthcare-worker accounts (these accounts cannot log in). "
            "These are not real people or real data-entry records."
        )
