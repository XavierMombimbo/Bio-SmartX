import os
import cv2
import numpy as np
import logging
from insightface.app import FaceAnalysis
from core.models import Detenu, Visage

logger = logging.getLogger(__name__)

# Chargement du modèle InsightFace (ArcFace) une seule fois
face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0)

def extraire_embedding(image_rgb, save_debug=False, debug_path='debug_visage_detecte.jpg'):
    try:
        faces = face_app.get(image_rgb)
        if not faces:
            logger.info("😶 Aucun visage détecté.")
            return None

        face = faces[0]
        if face.det_score < 0.6:
            logger.warning("❗ Visage de faible qualité.")
            return None

        if abs(face.pose[0]) > 30 or abs(face.pose[1]) > 30:
            logger.warning(f"❗ Pose non frontale : {face.pose}")
            return None

        # Debug image avec rectangle et score
        if save_debug:
            image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
            box = face.bbox.astype(int)
            cv2.rectangle(image_bgr, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
            cv2.putText(image_bgr, f"Score: {face.det_score:.2f}", (box[0], box[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imwrite(debug_path, image_bgr)

        return face.embedding
    except Exception as e:
        logger.error(f"Erreur d'extraction d'embedding : {e}")
        return None

def cosine_similarity(a, b):
    if a is None or b is None:
        return 0.0
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return np.dot(a, b) / (norm_a * norm_b)

def verifier_image_visage(image_path, seuil=0.62, return_score=False):
    """
    Compare le visage de l'image donnée à tous les visages en base (table Visage).
    Retourne le détenu correspondant s'il y a une correspondance.
    """
    try:
        image_bgr = cv2.imread(image_path)
        if image_bgr is None:
            logger.error("❌ Image introuvable.")
            return None

        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        embedding_input = extraire_embedding(image_rgb, save_debug=True)
        if embedding_input is None:
            logger.warning("🚫 Aucun embedding extrait.")
            return None

        meilleur_score = 0.0
        meilleur_visage = None
        meilleur_detenu = None

        for visage in Visage.objects.exclude(embedding__isnull=True).exclude(embedding=b''):
            try:
                emb_ref = np.frombuffer(visage.embedding, dtype=np.float32)
                score = cosine_similarity(embedding_input, emb_ref)
                logger.info(f"🔍 Score avec visage {visage.id} (détenu {visage.detenu.nom}) : {score:.4f}")

                if score > meilleur_score and score > seuil:
                    meilleur_score = score
                    meilleur_visage = visage
                    meilleur_detenu = visage.detenu
            except Exception as e:
                logger.warning(f"⚠️ Erreur avec le visage {visage.id} : {e}")

        if return_score:
            if meilleur_detenu:
                logger.info(f"✅ Correspondance : {meilleur_detenu.nom} {meilleur_detenu.postnom} (score {meilleur_score:.4f})")
                return meilleur_detenu, meilleur_score
            else:
                logger.info("❌ Aucune correspondance trouvée.")
                return None, None
        else:
            return meilleur_detenu

    except Exception as e:
        logger.error(f"Erreur générale dans la vérification visage : {e}")
        return None

# ============================================================
# NOUVELLE FONCTION POUR LE MATCHING DIRECT PAR EMBEDDING
# ============================================================

def verifier_embedding_direct(embedding, seuil=0.62):
    """
    Compare un embedding (numpy array) avec tous les embeddings de la table Visage.
    Retourne (detenu, score) où score est la similarité cosinus max.
    """
    if embedding is None:
        return None, 0.0

    meilleur_score = 0.0
    meilleur_detenu = None

    # Normalisation de l'embedding d'entrée
    norm_input = np.linalg.norm(embedding)
    if norm_input > 0:
        embedding = embedding / norm_input

    for visage in Visage.objects.exclude(embedding__isnull=True).exclude(embedding=b''):
        try:
            emb_ref = np.frombuffer(visage.embedding, dtype=np.float32)
            # Normalisation de l'embedding de référence
            norm_ref = np.linalg.norm(emb_ref)
            if norm_ref > 0:
                emb_ref = emb_ref / norm_ref
            score = np.dot(embedding, emb_ref)  # similarité cosinus
            if score > meilleur_score and score > seuil:
                meilleur_score = score
                meilleur_detenu = visage.detenu
        except Exception as e:
            logger.warning(f"⚠️ Erreur avec le visage {visage.id} : {e}")
            continue

    return meilleur_detenu, meilleur_score