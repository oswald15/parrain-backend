from django.db import migrations


def migrate_barman_to_caissier(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.filter(role='barman').update(role='caissier')


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_user_can_transfer_stock_user_departments_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_barman_to_caissier, reverse_noop),
    ]
