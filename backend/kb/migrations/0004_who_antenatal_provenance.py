from django.db import migrations


DOCUMENT_SHA256 = "338300b76172d410b91048209305fac53e1166c3be295a18b3f2c0c7c6b54182"
ISSUING_ORGANIZATION = "World Health Organization"
SOURCE_URL = "https://www.who.int/publications/i/item/9789241549912"


def populate_verified_provenance(apps, schema_editor):
    KnowledgeDocument = apps.get_model("kb", "KnowledgeDocument")
    KnowledgeDocument.objects.filter(
        sha256=DOCUMENT_SHA256,
        title="WHO recommendations on antenatal care",
    ).update(
        issuing_organization=ISSUING_ORGANIZATION,
        source_url=SOURCE_URL,
    )


def clear_verified_provenance(apps, schema_editor):
    KnowledgeDocument = apps.get_model("kb", "KnowledgeDocument")
    KnowledgeDocument.objects.filter(
        sha256=DOCUMENT_SHA256,
        title="WHO recommendations on antenatal care",
        issuing_organization=ISSUING_ORGANIZATION,
        source_url=SOURCE_URL,
    ).update(issuing_organization="", source_url="")


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0003_knowledge_document_issuing_organization"),
    ]

    operations = [
        migrations.RunPython(populate_verified_provenance, clear_verified_provenance),
    ]
