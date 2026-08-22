from django.db import migrations


def copy_department_family_values(apps, schema_editor):
    Department = apps.get_model('organisations', 'Department')
    DepartmentFamily = apps.get_model('organisations', 'DepartmentFamily')

    for department in Department.objects.exclude(family__isnull=True).exclude(family=''):
        DepartmentFamily.objects.get_or_create(
            department=department,
            name=department.family,
            defaults={'is_active': True}
        )


class Migration(migrations.Migration):

    dependencies = [
        ('organisations', '0004_departmentfamily'),
    ]

    operations = [
        migrations.RunPython(copy_department_family_values, migrations.RunPython.noop),
    ]
