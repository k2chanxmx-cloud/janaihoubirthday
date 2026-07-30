# じゃない方 生誕AIメーカー

## 写真の差し替え
`static/photos/` の `photo1.jpg`〜`photo4.jpg` を本人の写真に置き換えてください。

- photo1.jpg / photo2.jpg：かわいい写真
- photo3.jpg / photo4.jpg：変顔写真
- 正方形に近い画像がおすすめ

## Render
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --timeout 180`
- 環境変数: `OPENAI_API_KEY`

必要に応じて以下を変更できます。
- `OPENAI_IMAGE_MODEL=gpt-image-1-mini`
- `OPENAI_IMAGE_QUALITY=medium`
- `PER_IP_LIMIT=3`
- `TOTAL_LIMIT=80`

## ローカル起動
```bash
pip install -r requirements.txt
set OPENAI_API_KEY=sk-...
python app.py
```
