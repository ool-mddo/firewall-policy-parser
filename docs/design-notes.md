# 設計ノート

## 抽出対象セクション (初期スコープ)
以下の2セクションのみを最初の実装対象とする。

- `security > policies`: from-zone/to-zone ごとのポリシールール
- `security > zones`: ゾーン名 ↔ インタフェース対応

除外 (将来対応): address-book、applications、NAT 等

## TTP 出力の JSON 構造 (暫定)
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
          "match": {
            "source_address": ["any"],
            "destination_address": ["any"],
            "application": ["any"]
          },
          "action": "permit"
        }
      ]
    }
  ],
  "zones": [
    { "name": "WAN", "interfaces": ["ge-0/0/1.0", "ge-7/0/1.0"] }
  ]
}
```

## FW コンフィグ検出の設計判断
bgp-policy-parser は node_props.csv (外部クエリ結果) でノード種別を判定しているが、
本ツールでは configs dir に他ルータ・スイッチのコンフィグが混在するため、
ファイル内容のコメントパターンによる自動検出方式を採用した。

## node_pairs を REST で受け取る理由
SRX cluster の node0/node1 ペア情報はコンフィグファイル単体では判断できないため、
呼び出し元が明示的に渡す設計とした。

## configs dir のパス構造 (未確定)
`MDDO_CONFIGS_DIR/<network>/<snapshot>/` 以下のどのサブディレクトリにコンフィグが置かれるか、
実際の運用ディレクトリ構造によって walk の対象範囲を調整が必要。
bgp-policy-parser では `configs/<network>/<snapshot>/configs/` を使用している。

## 将来検討: policy model 変換ステージ
現在のスコープは TTP パースまで (ttp_output への JSON 保存)。
bgp-policy-parser のように TTP raw JSON → 正規化 policy model への変換処理を
第2ステージとして追加することを想定しているが、初期実装には含めない。

## 将来検討: address-book / applications の対応
サンプルコンフィグには address-book や applications セクションが含まれないため
初期スコープ外とする。実コンフィグで必要になった時点で TTPテンプレートを拡張する。
