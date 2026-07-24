from django.db import migrations


RESOURCE_FILE_COLUMNS = (
    ("core_appuser", "profile_photo"),
    ("core_document", "file"),
    ("core_listingimage", "file"),
)


def ensure_resource_file_column_lengths(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        for table_name, column_name in RESOURCE_FILE_COLUMNS:
            cursor.execute(f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" TYPE varchar(512)')


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0025_resource_scoped_upload_paths"),
    ]

    operations = [
        migrations.RunPython(ensure_resource_file_column_lengths, migrations.RunPython.noop),
    ]
