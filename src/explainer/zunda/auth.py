"""One-time YouTube authorization on your own PC (opens the browser).

python main.py zunda-auth --client-id ID --client-secret SECRET
"""

import http.server
import os
import secrets
import threading
import webbrowser
from pathlib import Path

from . import youtube


def auth_youtube(client_id, client_secret, output, port=8765):
    """Desktop OAuth: open the consent page, catch the code on localhost, save the
    refresh token to a private file. Then: gh secret set YOUTUBE_REFRESH_TOKEN < FILE"""
    redirect = f"http://127.0.0.1:{port}/"
    expected = secrets.token_urlsafe(16)
    caught = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            from urllib.parse import parse_qs, urlsplit

            query = parse_qs(urlsplit(self.path).query)
            caught.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "認可を受け取りました。このタブは閉じて構いません。".encode()
            )

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    url = youtube.authorize_url(client_id, redirect, expected)
    print(
        "ブラウザで次のURLを開き、投稿するチャンネルのアカウントで許可してください:\n"
        + url
    )
    webbrowser.open(url)
    thread.join(timeout=600)
    server.server_close()
    if caught.get("state") != expected or "code" not in caught:
        raise SystemExit("認可を受け取れませんでした（タイムアウトまたは拒否）")
    token = youtube.exchange_code(client_id, client_secret, caught["code"], redirect)
    path = Path(output).expanduser()
    path.write_text(token, encoding="utf-8")
    os.chmod(path, 0o600)
    print(
        f"保存しました: {path}\n登録: gh secret set YOUTUBE_REFRESH_TOKEN --repo nyu1791-collab/3D- < {path}"
    )
    print("登録後はこのファイルを削除してください。")
