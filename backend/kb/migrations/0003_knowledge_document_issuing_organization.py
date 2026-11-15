from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0002_documentchunk_page_number_and_unique_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgedocument",
            name="issuing_organization",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
