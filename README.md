# OSM報酬最大化経路探索システム

OSM地図上で道路エッジに報酬を手動設定し、距離制約下で取得報酬を最大化する
経路を探索・表示するローカルツール。仕様は [docs/SPEC.md](docs/SPEC.md) を参照。

## セットアップ

Python 3.11 以上が必要。

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 起動

```bash
streamlit run app.py
```

初回起動時は OSM から対象地域（既定: 京都市下京区）の道路ネットワークを
取得するため、ネットワーク接続が必要です。取得したグラフは
`data/graph_{place_slug}.graphml` にキャッシュされ、2回目以降はローカルから
読み込みます。

対象地域は `config.yaml` の `place` で変更できます。

## テスト

```bash
pytest tests/
```

## 実装状況

- [x] Phase 0: 基盤（グラフ取得・graphmlキャッシュ・無向化・config）
- [ ] Phase 1: 報酬設定機能
- [ ] Phase 2: モードR探索（コア）
- [ ] Phase 3: 拡張探索
- [ ] Phase 4: 仕上げ
