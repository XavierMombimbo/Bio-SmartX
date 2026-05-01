import os
import subprocess

from core.models import Detenu
 # Use absolute import if models.py is in the same directory

def identifier_empreinte(image_fp_path: str, liste_tpl_existants: list, seuil: int = 40):
    meilleur_score = -1
    meilleur_index = None

    temp_prefix = os.path.splitext(image_fp_path)[0]
    temp_xyt_path = temp_prefix + '.xyt'

    try:
        subprocess.run(['mindtct', image_fp_path, temp_prefix], check=True)
        if not os.path.exists(temp_xyt_path):
            return None, 0

        for idx, ref_path in enumerate(liste_tpl_existants):
            result = subprocess.run(
                ['bozorth3', '-T', str(seuil), '-p', temp_xyt_path, ref_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            score_str = result.stdout.strip()
            score = int(score_str) if score_str.isdigit() else 0

            if score > meilleur_score:
                meilleur_score = score
                meilleur_index = idx

            if score >= seuil:
                break

    except Exception:
        return None, 0
    finally:
        if os.path.exists(temp_xyt_path):
            os.remove(temp_xyt_path)

    if meilleur_score >= seuil:
        # retourne le détenu correspondant à l'empreinte
        return Detenu.objects.exclude(empreinte_xyt__isnull=True).exclude(empreinte_xyt='')[meilleur_index], meilleur_score

    return None, 0

def extraire_minuties_avec_mindtct(image_path, dossier_sortie):
    """
    Extrait les minuties d'une image d'empreinte digitale avec NBIS/mindtct.
    Retourne le chemin du fichier .xyt généré.
    """
    try:
        os.makedirs(dossier_sortie, exist_ok=True)
        cmd = ["mindtct", image_path, os.path.join(dossier_sortie, "empreinte")]
        subprocess.run(cmd, check=True)
        return os.path.join(dossier_sortie, "empreinte.xyt")
    except subprocess.CalledProcessError as e:
        print(f"Erreur lors de l'extraction des minuties : {e}")
        return None