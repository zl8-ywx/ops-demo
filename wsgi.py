"""WSGI 入口，供 gunicorn 调用：gunicorn wsgi:app"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # 仅用于本地调试，生产环境请用 gunicorn
    app.run(host="0.0.0.0", port=8080)
