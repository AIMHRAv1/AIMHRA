from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentchunk",
            name="page_number",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="documentchunk",
            constraint=models.UniqueConstraint(
                fields=("document", "chunk_index"),
                name="kb_unique_document_chunk",
            ),
        ),
    ]
