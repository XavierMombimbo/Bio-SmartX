from datetime import timedelta
from django.utils import timezone
from core.models import TentativeConnexion

# Configurations
NOMBRE_MAX_TENTATIVES = 5
DUREE_BLOCAGE_MINUTES = 60

def est_bloque(username, ip):
    maintenant = timezone.now()
    limite = maintenant - timedelta(minutes=DUREE_BLOCAGE_MINUTES)

    tentatives_recents = TentativeConnexion.objects.filter(
        username=username,
        adresse_ip=ip,
        timestamp__gte=limite
    )

    if tentatives_recents.count() >= NOMBRE_MAX_TENTATIVES:
        return True
    return False
