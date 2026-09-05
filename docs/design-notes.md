# 設計ノート

## 抽出対象セクション (初期スコープ)
以下の2セクションのみを最初の実装対象とする。

- `security > policies`: from-zone/to-zone ごとのポリシールール
- `security > zones`: ゾーン名 ↔ インタフェース対応

除外 (将来対応): address-book、applications、NAT 等

## TTP 出力の JSON 構造 (確定)
```json
{
  "node": "site-a-fw-1",
  "pair": { "primary": "site-a-fw-1", "secondary": "site-a-fw-2" },
  "policies": [
    {
      "from_zone": "trust",
      "to_zone": "untrust",
      "rules": [
        {
          "name": "default-permit",
          "source_address": "any",
          "destination_address": "any",
          "application": "any",
          "action": "permit"
        }
      ]
    }
  ],
  "zones": [
    { "name": "trust", "interfaces": [] },
    { "name": "WAN", "interfaces": ["ge-0/0/1.0", "ge-7/0/1.0"] }
  ]
}
```

**現状の制約**: `source_address` / `destination_address` / `application` はスカラー値。
同一 match ブロックに複数行ある場合は最後の値だけが残り、それ以前は無音で上書きされる
(レビュー F-1 参照)。将来的にはリスト型への変更が必要。

## FW コンフィグ検出の設計判断
bgp-policy-parser は node_props.csv (外部クエリ結果) でノード種別を判定しているが、
本ツールでは configs dir に他ルータ・スイッチのコンフィグが混在するため、
ファイル内容のコメントパターンによる自動検出方式を採用した。

## node_pairs を REST で受け取る理由
SRX cluster の node0/node1 ペア情報はコンフィグファイル単体では判断できないため、
呼び出し元が明示的に渡す設計とした。

## configs dir のパス構造 (確定)
`MDDO_CONFIGS_DIR/<network>/<snapshot>/configs/` 以下を `os.walk` で再帰的に走査する。
bgp-policy-parser と同じ `configs/` サブディレクトリ構造を採用した。
実装・手動テストで動作確認済み。

## 将来検討: policy model 変換ステージ
現在のスコープは TTP パースまで (ttp_output への JSON 保存)。
bgp-policy-parser のように TTP raw JSON → 正規化 policy model への変換処理を
第2ステージとして追加することを想定しているが、初期実装には含めない。

## TTP テンプレートのインデント依存
TTP はテンプレート行のインデント（スペース数）を入力行と厳密に照合する。
現テンプレート (`src/template/juniper_srx.ttp`) は JunOS `display inheritance` 出力の
以下のインデントを前提としている:

| インデント | 対応する設定ブロック |
|---|---|
| 4 spaces | `host-name` (system ブロック内) |
| 8 spaces | `from-zone ... to-zone ...`, `security-zone` |
| 12 spaces | `policy NAME`, `interfaces {` |
| 20 spaces | `source-address`, `destination-address`, `application`, `permit`/`deny` |

インデントが異なる（タブ使用、スペース数違い等）場合は一切マッチせず、
エラーも警告も出ずに空の JSON が生成される点に注意。

## 将来検討: address-book / applications の対応
サンプルコンフィグには address-book や applications セクションが含まれないため
初期スコープ外とする。実コンフィグで必要になった時点で TTPテンプレートを拡張する。
