"""TikTok OAuth 2.0 helper (console-only, no web server).

Flow:
1) Build and print authorization URL.
2) User opens URL in browser, authenticates, and copies redirect URL.
3) Script extracts authorization code and exchanges it for tokens.
4) Tokens are saved to tokens.json.
"""

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv


AUTHORIZATION_ENDPOINT = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_ENDPOINT = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = "https://jojolepopo.github.io/TiktokApp_LoisGenerator/"
SCOPES = ["user.info.basic", "video.upload"]
TOKENS_FILE = Path("tokens.json")


def build_authorization_url(client_key: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    """Build TikTok OAuth authorization URL."""
    params = {
        "client_key": client_key,
        "scope": ",".join(scopes),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def extract_code_from_redirect_input(user_input: str) -> str:
    """Extract code either from full redirect URL or from raw code input."""
    value = user_input.strip()
    if not value:
        raise ValueError("Entrée vide. Colle l'URL de redirection complète (ou le code seul).")

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        query_params = parse_qs(parsed.query)
        code_values = query_params.get("code")
        if not code_values or not code_values[0]:
            raise ValueError("Paramètre 'code' introuvable dans l'URL fournie.")
        return code_values[0]

    return value


def exchange_code_for_tokens(
    client_key: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    """Exchange authorization code for access/refresh tokens."""
    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    response = requests.post(
        TOKEN_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Réponse non JSON du endpoint token (HTTP {response.status_code}): {response.text}"
        ) from exc

    if response.status_code != 200:
        raise RuntimeError(
            "Échec échange token. "
            f"HTTP {response.status_code}. Réponse: {json.dumps(data, ensure_ascii=False)}"
        )

    # TikTok peut retourner soit un objet plat, soit un objet encapsulé sous "data".
    token_data = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(token_data, dict) or "access_token" not in token_data:
        raise RuntimeError(f"Format de réponse inattendu: {json.dumps(data, ensure_ascii=False)}")

    return data


def get_token_data(token_response: dict) -> dict:
    """Return the normalized token payload regardless of response shape."""
    nested = token_response.get("data")
    if isinstance(nested, dict):
        return nested
    return token_response


def save_tokens(token_response: dict, output_file: Path) -> None:
    """Persist token response into tokens.json with metadata."""
    payload = {
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "token_response": token_response,
    }
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    load_dotenv()

    client_key = os.getenv("CLIENT_KEY", "").strip()
    client_secret = os.getenv("CLIENT_SECRET", "").strip()

    if not client_key:
        client_key = input("CLIENT_KEY introuvable dans .env, saisis-le ici: ").strip()
    if not client_secret:
        client_secret = input("CLIENT_SECRET introuvable dans .env, saisis-le ici: ").strip()

    if not client_key or not client_secret:
        raise RuntimeError("CLIENT_KEY et CLIENT_SECRET sont requis pour l'échange de token.")

    state = secrets.token_urlsafe(24)
    authorization_url = build_authorization_url(client_key, REDIRECT_URI, SCOPES, state)

    print("\n=== URL d'autorisation TikTok ===")
    print(authorization_url)
    print("\n1) Copie cette URL dans ton navigateur.")
    print("2) Autorise l'application.")
    print("3) Copie l'URL de redirection finale et colle-la ci-dessous.\n")

    redirected = input("Colle ici l'URL de redirection complète (ou le code): ")
    code = extract_code_from_redirect_input(redirected)

    token_response = exchange_code_for_tokens(
        client_key=client_key,
        client_secret=client_secret,
        code=code,
        redirect_uri=REDIRECT_URI,
    )

    save_tokens(token_response, TOKENS_FILE)

    token_data = get_token_data(token_response)
    print("\n✅ Tokens récupérés et sauvegardés.")
    print(f"Fichier: {TOKENS_FILE.resolve()}")
    print(f"access_token présent: {'access_token' in token_data}")
    print(f"refresh_token présent: {'refresh_token' in token_data}")


if __name__ == "__main__":
    main()
