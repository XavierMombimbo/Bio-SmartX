from django import template

register = template.Library()

@register.filter
def floatval(value):
    """Convertit une valeur en float (utile si elle est une string dans le template)"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

@register.filter
def mul(value, arg):
    """Multiplie deux valeurs (ex: pour faire un pourcentage)"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0.0

@register.filter
def score_percent(value):
    """Transforme un score (0.0 - 1.0) en pourcentage (0 - 100)"""
    try:
        return round(float(value) * 100, 2)
    except (ValueError, TypeError):
        return 0.0
