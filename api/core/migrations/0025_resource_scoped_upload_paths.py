import core.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_paymentsettlement_processing_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appuser",
            name="profile_photo",
            field=models.ImageField(blank=True, null=True, max_length=512, upload_to=core.models.profile_photo_upload_to),
        ),
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(max_length=512, upload_to=core.models.document_file_upload_to),
        ),
        migrations.AlterField(
            model_name="listingimage",
            name="file",
            field=models.ImageField(max_length=512, upload_to=core.models.listing_image_file_upload_to),
        ),
    ]
