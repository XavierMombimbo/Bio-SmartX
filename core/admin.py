from django.contrib import admin
from .models import Prison

@admin.register(Prison)
class PrisonAdmin(admin.ModelAdmin):
    list_display = ('nom', 'localisation', 'capacite')
    search_fields = ('nom', 'localisation')

# Register your models here.
