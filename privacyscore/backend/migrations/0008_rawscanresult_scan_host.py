# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-03 14:47
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0007_auto_20170603_0910'),
    ]

    operations = [
        migrations.AddField(
            model_name='rawscanresult',
            name='scan_host',
            field=models.CharField(default='', max_length=80),
            preserve_default=False,
        ),
    ]
