# TiktokApp_LoisGenerator

Automatisation de création de vidéos TikTok d'actualités législatives.

Pipeline principal:
1. Récupération d'une actualité via le flux RSS Vie-Publique.
2. Réécriture en script court (Gemini API).
3. Génération d'un voiceover (TikTok TTS avec fallback Edge TTS).
4. Montage vidéo vertical 9:16 avec sous-titres synchronisés.

Le script principal est [tiktok_news.py](tiktok_news.py).

## Prérequis

- Python 3.10+
- ffmpeg disponible sur la machine (requis par MoviePy)
- Une clé API Gemini

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

1. Copier [.env.example](.env.example) en `.env`.
2. Renseigner au minimum:

```env
GEMINI_KEY=ta_cle_api
```

Variables optionnelles prises en charge par le script:

```env
EDGE_VOICE=fr-FR-RemyMultilingualNeural
TIKTOK_VOICE=FR_MALE_2
PRIMARY_TTS_PROVIDER=tiktok
FALLBACK_TTS_PROVIDER=edge
```

## Exécution

```bash
python tiktok_news.py
```

Le script lit/écrit notamment:

- Entrée locale: `background.mp4` (vidéo de fond)
- Sorties locales: `voiceover.mp3`, `tiktok_final.mp4`, `last_news.json`

## Sécurité (repo public)

Ce dépôt est préparé pour GitHub public:

- Les fichiers sensibles (`.env`, variantes `.env.*`, clés/certificats) sont ignorés par Git.
- Les environnements virtuels et caches locaux sont ignorés.
- Les artefacts médias générés sont ignorés.

Bonnes pratiques avant chaque push:

1. Vérifier que `.env` n'est jamais versionné.
2. Ne jamais coller de clé API dans le code source.
3. En cas de fuite, révoquer/rotater immédiatement la clé concernée.
4. Vérifier l'état Git avec `git status` avant commit.

## Arborescence minimale recommandée

- [tiktok_news.py](tiktok_news.py)
- [requirements.txt](requirements.txt)
- [.env.example](.env.example)
- [tiktok_voice](tiktok_voice)

## Attribution

Ce projet utilise le moteur TTS TikTok provenant du dépôt suivant:

- [mark-rez/TikTok-Voice-TTS](https://github.com/mark-rez/TikTok-Voice-TTS)

Le module intégré est présent dans [tiktok_voice](tiktok_voice). Pense à conserver cette attribution et à respecter les conditions de licence du projet source en cas de redistribution.
