"""
Automatisation de vidéos TikTok "Nouvelles Lois"
-------------------------------------------------
Pipeline : RSS Vie-Publique → Gemini → TTS → Montage vidéo → Export
"""

import os
import sys
import textwrap
import time
import re
import json

from dotenv import load_dotenv
import requests
import feedparser
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import numpy as np
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
)

try:
    from tiktok_voice import tts as tiktok_tts, Voice as TikTokVoice
except ImportError:
    tiktok_tts = None
    TikTokVoice = None

# ============================================================
# 🔑  CLÉS API — Chargées depuis le fichier .env
# ============================================================
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")

VIE_PUBLIQUE_RSS = "https://www.vie-publique.fr/lois-feeds.xml"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


# ============================================================
# 📰  ÉTAPE 1 — Récupération des actualités législatives (RSS Vie-Publique)
# ============================================================

def _gemini_request(prompt: str) -> str:
    """Envoie un prompt à Gemini avec retry en cas de rate-limit."""
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_KEY,
    }
    payload = {
        "model": "gemini-3.1-flash-lite-preview",
        "input": [{"role": "user", "content": prompt}],
    }

    for attempt in range(5):
        resp = requests.post(GEMINI_URL, json=payload, headers=headers, timeout=60)
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"   ⏳ Rate-limit Gemini, nouvelle tentative dans {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    else:
        raise RuntimeError("Rate-limit Gemini dépassé après 5 tentatives.")

    data = resp.json()
    try:
        for item in data["outputs"]:
            if item.get("type") == "text":
                return item["text"].strip()
        raise KeyError("Aucun élément de type 'text' dans outputs")
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Réponse Gemini inattendue : {data}") from exc


def fetch_lois() -> dict:
    """Récupère une actualité législative via le flux RSS de Vie-Publique.
    Parcourt les 5 derniers articles et filtre ceux contenant 'Loi' ou 'Décret'.
    """
    feed = feedparser.parse(VIE_PUBLIQUE_RSS)
    if not feed.entries:
        raise RuntimeError(
            "Aucune entrée dans le flux RSS Vie-Publique. "
            f"Erreur éventuelle : {feed.get('bozo_exception', 'inconnue')}"
        )

    pattern = re.compile(r"\b(loi|décret)\b", re.IGNORECASE)
    filtered = []
    for entry in feed.entries[:5]:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        if pattern.search(title) or pattern.search(summary):
            filtered.append(entry)

    if not filtered:
        raise RuntimeError(
            "Aucun article contenant 'Loi' ou 'Décret' dans les 5 derniers "
            "articles du flux RSS Vie-Publique."
        )

    article = filtered[0]
    return {
        "title": article.get("title", "Sans titre"),
        "summary": article.get("summary", ""),
        "link": article.get("link", ""),
        "published": article.get("published", ""),
    }


# ============================================================
# ✍️  ÉTAPE 2 — Réécriture en script TikTok via Gemini
# ============================================================

def rewrite_with_gemini(loi: dict) -> str:
    """Appelle Gemini pour transformer l'actualité législative en script TikTok."""
    prompt = (
        "Tu es un créateur TikTok populaire spécialisé en vulgarisation juridique.\n"
        "Ton style est ALERTE, percutant et accessible à tous.\n"
        "Transforme l'actualité législative suivante en un script TikTok \n"
        "L'objectif est de rendre le sujet captivant et compréhensible pour un public non spécialisé. \n"
        "Le script DOIT contenir :\n"
        "1. Une ACCROCHE impactante, en mentionnant le titre de la loi : 'Une nouvelle loi vient d'être votée, '"
        "laisse moi t'expliquer en moins d'une minute !'.\n"
        "2. Un RÉSUMÉ CLAIR, rapide et accessible de ce que ça change concrètement, le texte doit faire environ 110 mots (pas plus de 150), et être rédigé de manière à ce que même quelqu'un sans aucune connaissance juridique puisse comprendre les impacts majeurs de la loi\n"
        "Un exemple concret d'application de la loi dans la vie quotidienne pour rendre ça plus vivant.\n"
        "3. Une QUESTION finale engageante pour pousser les commentaires.\n\n"
        "Renvoie UNIQUEMENT le texte du script, sans indication de section, "
        "sans hashtag, sans emoji superflu.\n\n"
        f"Titre : {loi['title']}\n"
        f"Résumé : {loi['summary']}\n"
        f"Date de publication : {loi['published']}\n"
        f"Lien : {loi['link']}"
    )

    return _gemini_request(prompt)


# ============================================================
# 🔊  ÉTAPE 3 — Génération audio TTS (TikTok principal + fallback Edge)
# ============================================================

AUDIO_PATH = "voiceover.mp3"
# Voix françaises naturelles : fr-FR-VivienneMultilingualNeural (femme),
#                               fr-FR-RemyMultilingualNeural (homme)
EDGE_VOICE = os.getenv("EDGE_VOICE", "fr-FR-VivienneMultilingualNeural")
TIKTOK_VOICE = os.getenv("TIKTOK_VOICE", "FR_MALE_2")
PRIMARY_TTS_PROVIDER = os.getenv("PRIMARY_TTS_PROVIDER", "edge").strip().lower()
FALLBACK_TTS_PROVIDER = os.getenv("FALLBACK_TTS_PROVIDER", "tiktok").strip().lower()


def _extract_source_words_with_punctuation(text: str) -> list:
    """Extrait les tokens du texte source en splitant sur les espaces,
    ce qui correspond a la granularite des evenements WordBoundary de l'API TTS.
    Les apostrophes et tirets restent attaches au mot (ex: c'est, aujourd'hui).
    """
    return [t for t in text.split() if t]


def _estimate_word_timings(text: str, audio_duration_s: float) -> list:
    """Construit des timings approximatifs mot a mot sur la duree audio totale."""
    tokens = _extract_source_words_with_punctuation(text)
    if not tokens or audio_duration_s <= 0:
        return []

    duration_per_word = audio_duration_s / len(tokens)
    timings = []
    for idx, token in enumerate(tokens):
        start = idx * duration_per_word
        end = (idx + 1) * duration_per_word
        timings.append({"start": start, "end": end, "text": token})
    return timings


def _generate_audio_with_edge(text: str) -> tuple:
    """Backend Edge TTS avec timings WordBoundary reels."""
    word_timings = []

    async def _run():
        communicate = edge_tts.Communicate(
            text, EDGE_VOICE, rate="+10%", boundary="WordBoundary"
        )
        with open(AUDIO_PATH, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    offset_s = chunk["offset"] / 10_000_000
                    duration_s = chunk["duration"] / 10_000_000
                    word_timings.append({
                        "start": offset_s,
                        "end": offset_s + duration_s,
                        "text": chunk["text"],
                    })

    asyncio.run(_run())

    # Remappe les mots sur le texte source pour préserver accents et ponctuation.
    source_tokens = _extract_source_words_with_punctuation(text)
    mapped_count = min(len(word_timings), len(source_tokens))
    for i in range(mapped_count):
        word_timings[i]["text"] = source_tokens[i]
    # Si le texte source contient plus de tokens que les événements TTS,
    # on attache les mots restants au dernier timing pour qu'ils soient visibles.
    if word_timings and len(source_tokens) > len(word_timings):
        leftover = " ".join(source_tokens[len(word_timings):])
        word_timings[-1]["text"] += " " + leftover

    return AUDIO_PATH, word_timings


def _generate_audio_with_tiktok(text: str) -> tuple:
    """Backend TikTok TTS avec timings approximatifs (pas de WordBoundary natif)."""
    if tiktok_tts is None or TikTokVoice is None:
        raise RuntimeError(
            "Module 'tiktok_voice' introuvable. "
            "Ajoute le dossier tiktok_voice du repo TikTok-Voice-TTS dans le projet."
        )

    voice = TikTokVoice.from_string(TIKTOK_VOICE)
    if voice is None:
        raise ValueError(
            f"Voix TikTok invalide: {TIKTOK_VOICE}. "
            "Exemple valide: FR_MALE_2"
        )

    tiktok_tts(text, voice, AUDIO_PATH, play_sound=False)
    if not os.path.isfile(AUDIO_PATH) or os.path.getsize(AUDIO_PATH) == 0:
        raise RuntimeError("TikTok TTS n'a pas genere de fichier audio valide.")

    audio_clip = AudioFileClip(AUDIO_PATH)
    duration = audio_clip.duration
    audio_clip.close()
    return AUDIO_PATH, _estimate_word_timings(text, duration)


def generate_audio(text: str) -> tuple:
    """Genere l'audio avec provider principal puis fallback.
    Retourne (chemin_audio, liste_timings_mots).
    """
    providers = {
        "tiktok": _generate_audio_with_tiktok,
        "edge": _generate_audio_with_edge,
    }

    order = [PRIMARY_TTS_PROVIDER]
    if FALLBACK_TTS_PROVIDER != PRIMARY_TTS_PROVIDER:
        order.append(FALLBACK_TTS_PROVIDER)

    last_error = None
    for provider_name in order:
        provider = providers.get(provider_name)
        if provider is None:
            print(f"⚠️ Provider inconnu: {provider_name}")
            continue
        try:
            print(f"🔊 TTS provider: {provider_name}")
            audio_path, word_timings = provider(text)
            print(f"✅ Audio généré via {provider_name} → {audio_path}")
            return audio_path, word_timings
        except Exception as exc:
            last_error = exc
            print(f"⚠️ Échec provider {provider_name}: {exc}")

    raise RuntimeError(f"Aucun provider TTS disponible. Dernière erreur: {last_error}")


# ============================================================
# 🎬  ÉTAPE 4 — Montage vidéo (MoviePy)
# ============================================================

BACKGROUND_VIDEO = "background.mp4"  # Vidéo de fond 9:16 à fournir
OUTPUT_VIDEO = "tiktok_final.mp4"
LAST_NEWS_FILE = "last_news.json"  # Fichier pour stocker la dernière actualité traitée


def _make_subtitle_image(text: str, font):
    """Crée une image de sous-titre avec contour noir sur fond transparent."""
    wrapped = "\n".join(textwrap.wrap(text, width=28))

    dummy_img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    txt_w = int(bbox[2] - bbox[0]) + 40
    txt_h = int(bbox[3] - bbox[1]) + 40

    txt_img = Image.new("RGBA", (txt_w, txt_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_img)
    x = (txt_w - (bbox[2] - bbox[0])) // 2
    y = (txt_h - (bbox[3] - bbox[1])) // 2
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            draw.multiline_text((x + dx, y + dy), wrapped, font=font,
                                fill=(0, 0, 0, 255), align="center")
    draw.multiline_text((x, y), wrapped, font=font,
                        fill=(255, 255, 255, 255), align="center")

    return np.array(txt_img)


def build_video(script_text: str, audio_path: str, word_timings: list) -> str:
    """Monte la vidéo TikTok finale : fond + audio + sous-titres synchronisés."""

    if not os.path.isfile(BACKGROUND_VIDEO):
        raise FileNotFoundError(
            f"Place une vidéo de fond nommée '{BACKGROUND_VIDEO}' (format 9:16) "
            "dans le même dossier que ce script."
        )

    # --- Chargement audio pour connaître la durée ---
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    # --- Vidéo de fond coupée à la durée de l'audio ---
    video_clip = VideoFileClip(BACKGROUND_VIDEO)
    if video_clip.duration < duration:
        from moviepy.editor import concatenate_videoclips
        loops = int(duration // video_clip.duration) + 1
        video_clip = concatenate_videoclips([video_clip] * loops)
    video_clip = video_clip.subclip(0, duration)

    # Redimensionne en 1080×1920 (9:16) si nécessaire
    video_clip = video_clip.resize((1080, 1920))

    # --- Sous-titres synchronisés mot par mot ---
    font_size = 60
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    # Regrouper les mots par paquets de 10
    WORDS_PER_GROUP = 10
    groups = []
    for i in range(0, len(word_timings), WORDS_PER_GROUP):
        chunk = word_timings[i:i + WORDS_PER_GROUP]
        text = " ".join(w["text"] for w in chunk)
        start = chunk[0]["start"]
        # Chaque groupe dure jusqu'au début du groupe suivant (pas de trou)
        groups.append({"start": start, "text": text})

    sub_clips = []
    for idx, group in enumerate(groups):
        start = group["start"]
        if idx + 1 < len(groups):
            end = groups[idx + 1]["start"]
        else:
            end = duration
        img = _make_subtitle_image(group["text"], font)
        clip = (
            ImageClip(img)
            .set_position("center")
            .set_start(start)
            .set_duration(end - start)
        )
        sub_clips.append(clip)

    # --- Composition finale ---
    final = CompositeVideoClip([video_clip] + sub_clips)
    final = final.set_audio(audio_clip)

    final.write_videofile(
        OUTPUT_VIDEO,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
    )

    # Nettoyage
    audio_clip.close()
    video_clip.close()
    for c in sub_clips:
        c.close()
    final.close()

    print(f"🎬 Vidéo exportée → {OUTPUT_VIDEO}")
    return OUTPUT_VIDEO


# ============================================================
# 🚀  PIPELINE PRINCIPAL
# ============================================================

def get_last_processed_news() -> dict:
    """Récupère les infos de la dernière actualité traitée depuis le fichier."""
    if not os.path.isfile(LAST_NEWS_FILE):
        return None
    try:
        with open(LAST_NEWS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_processed_news(loi: dict) -> None:
    """Sauvegarde les infos de l'actualité actuelle pour la prochaine vérification."""
    news_info = {
        "title": loi["title"],
        "link": loi["link"],
        "published": loi["published"],
    }
    with open(LAST_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(news_info, f, ensure_ascii=False, indent=2)


def is_new_news(current_loi: dict) -> bool:
    """Vérifie si l'actualité actuelle est nouvelle (différente de la dernière traitée)."""
    last_news = get_last_processed_news()
    
    if last_news is None:
        return True  # Première exécution
    
    # Compare les infos principales : title et link
    if (current_loi["title"] != last_news.get("title") or 
        current_loi["link"] != last_news.get("link")):
        return True
    
    return False

def main():
    print("📰 Récupération des actualités législatives (RSS Vie-Publique)…")
    loi = fetch_lois()
    print(f"   → {loi['title']}")
    print(f"   → {loi['summary'][:120]}…")

    # Vérification si c'est une nouvelle actualité
    if not is_new_news(loi):
        print("ℹ️  Aucune nouvelle actualité détectée.")
        print("❌ Création de vidéo non nécessaire.")
        return

    print("✍️  Réécriture en script TikTok (Gemini)…")
    script = rewrite_with_gemini(loi)
    print(f"   → {script}")

    print("🔊 Génération de l'audio...")
    audio, word_timings = generate_audio(script)

    print("🎬 Montage de la vidéo...")
    build_video(script, audio, word_timings)

    # Sauvegarde les infos de cette actualité pour la prochaine vérification
    save_processed_news(loi)

    print("✅ Terminé ! Ouvre tiktok_final.mp4 pour voir le résultat.")


if __name__ == "__main__":
    main()
